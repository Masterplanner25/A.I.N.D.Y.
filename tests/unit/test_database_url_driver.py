"""Every engine we create names its driver (runtime 2.38.0, SQLAlchemy 2.1, DEC-134).

On SQLAlchemy 2.1 a bare `postgresql://` means psycopg 3, which nothing installs, so an engine built from a bare
`DATABASE_URL` fails with `No module named 'psycopg'`. `docker/entrypoint.sh` runs `scripts/ensure_pgvector.py` first:
one missed site there and the container never boots. Each `create_engine(...)` must take
`normalize_database_url(...)` or a literal SQLite URL; workflow YAML gets a line scan, since inline Python is invisible
to the AST walk (the runtime's first CI run missed one there).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.app_profile

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("apps", "scripts", "alembic", "tests", "docker")
SKIP_PARTS = {"node_modules", "venv", ".venv", "__pycache__"}


def _python_files():
    for top in SCANNED:
        for path in (ROOT / top).rglob("*.py"):
            if not SKIP_PARTS.intersection(path.parts):
                yield path


def _url_is_named(arg: ast.expr) -> bool:
    if isinstance(arg, ast.Call):
        func = arg.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        return name == "normalize_database_url"
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value.startswith("sqlite")
    if isinstance(arg, ast.JoinedStr) and arg.values:  # f"sqlite:///{path}"
        head = arg.values[0]
        return isinstance(head, ast.Constant) and str(head.value).startswith("sqlite")
    return False


def _bare_engine_calls(source: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "create_engine" or not node.args:
            continue
        if not _url_is_named(node.args[0]):
            lines.append(node.lineno)
    return lines


# The URL is normalised where it is read, not at the call: `env.py` wraps `database_url` once for both its sites.
NORMALISED_UPSTREAM = {"alembic/alembic/env.py"}


def test_every_python_engine_names_its_driver():
    offenders = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if rel in NORMALISED_UPSTREAM:
            assert "normalize_database_url(database_url)" in source, rel
            continue
        offenders += [f"{rel}:{line}" for line in _bare_engine_calls(source)]
    assert offenders == [], f"wrap the URL in AINDY.config.normalize_database_url: {offenders}"


def test_every_inline_workflow_engine_names_its_driver():
    pattern = re.compile(r"create_engine\((?!normalize_database_url\(|['\"]sqlite)")
    offenders = [
        f"{path.name}:{n}"
        for path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line) and not line.lstrip().startswith("#")
    ]
    assert offenders == [], offenders


def test_the_guard_catches_a_bare_engine():
    assert _bare_engine_calls('create_engine(os.environ["DATABASE_URL"])') == [1]
    assert _bare_engine_calls('create_engine(normalize_database_url(url))') == []
    assert _bare_engine_calls('create_engine("sqlite://")') == []
    assert _bare_engine_calls('create_engine(f"sqlite:///{p}")') == []
    assert _bare_engine_calls('create_engine(f"postgresql://{p}")') == [1]
