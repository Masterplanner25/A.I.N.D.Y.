from __future__ import annotations

from pathlib import Path
import tomllib

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[2]


def test_apps_repo_declares_bounded_runtime_dependency():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    requirements = [Requirement(item) for item in pyproject["project"]["dependencies"]]
    runtime_requirement = next(req for req in requirements if req.name == "aindy-runtime")

    assert str(runtime_requirement.specifier) == "<3.0,>=2.4.1"
    assert any(spec.operator == "<" for spec in runtime_requirement.specifier)
    assert any(spec.operator == ">=" for spec in runtime_requirement.specifier)
