"""The installed package must carry every `.nd` workflow (2026-11-02).

`include-package-data = true` with no MANIFEST.in ships no data files, so the image's installed
`apps` had no `nodus/` folders. The api imports `/app/apps` and never noticed; a scheduled job's
callback imports the installed copy, registered nothing, and every scheduled `.nd` run fell back to
Python ("is not registered"), which #510 had been meant to end. Tests run from the repo, where the
files exist, so only building the wheel shows it.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.app_profile


def test_every_nd_file_is_in_the_wheel(tmp_path):
    expected = {p.relative_to(ROOT).as_posix() for p in (ROOT / "apps").rglob("*.nd")}
    assert expected, "no .nd workflows found under apps/"

    # Build from a clean copy: a leftover `*.egg-info` in the checkout lists the files its last build
    # saw, and setuptools reuses it, which made this test pass against the broken config.
    src = tmp_path / "src"
    shutil.copytree(ROOT / "apps", src / "apps", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(ROOT / name, src / name)
    out = tmp_path / "wheel"
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(src), "--no-deps", "--no-build-isolation",
         "-q", "-w", str(out)],
        capture_output=True, text=True, timeout=600, cwd=src,
    )
    assert build.returncode == 0, build.stderr[-2000:]
    (wheel,) = out.glob("*.whl")
    shipped = {name for name in zipfile.ZipFile(wheel).namelist() if name.endswith(".nd")}
    assert expected <= shipped, sorted(expected - shipped)


def test_a_missing_workflow_says_where_it_looked(monkeypatch, tmp_path):
    import apps._shared.nodus as nodus
    import AINDY.runtime.nodus_workflow_registry as nwr

    monkeypatch.setattr(nwr, "get_nodus_workflow", lambda name: None)
    monkeypatch.setattr(nodus, "register_domain_nodus_workflows", lambda *a, **k: [])
    with pytest.raises(LookupError, match=r"no share_drafts_v1\.nd in .*rippletrace.nodus"):
        nodus.ensure_domain_nodus_workflow("rippletrace", "share_drafts_v1")
