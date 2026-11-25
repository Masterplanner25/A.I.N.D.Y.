"""OFF_LAPTOP_DEPLOYMENT_SPEC phase E: the server's setup and nightly backup scripts (`scripts/server/`)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.app_profile

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "scripts" / "server"
SETUP = SERVER / "setup_host.sh"
NIGHTLY = SERVER / "nightly_backup.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="no bash")
@pytest.mark.parametrize("script", [SETUP, NIGHTLY], ids=lambda p: p.name)
def test_the_script_parses(script):
    # relative to the repo root: on Windows `bash` may be WSL's, which cannot read a C: path
    subprocess.run(["bash", "-n", script.relative_to(ROOT).as_posix()], cwd=ROOT, check=True)


def test_the_timer_runs_the_nightly_script_as_aindy():
    text = SETUP.read_text(encoding="utf-8")
    assert "User=${USER_NAME}" in text and 'USER_NAME="aindy"' in text
    assert "scripts/server/nightly_backup.sh" in text and "Persistent=true" in text


def test_nothing_opens_a_port_beyond_ssh():
    text = SETUP.read_text(encoding="utf-8")
    allows = [line.strip() for line in text.splitlines() if line.strip().startswith("ufw allow")]
    assert allows == ["ufw allow in on tailscale0 to any port 22 proto tcp", "ufw allow OpenSSH"]
    assert "0.0.0.0" not in text


def test_the_nightly_copy_is_encrypted_restic_and_tests_on_sundays():
    text = NIGHTLY.read_text(encoding="utf-8")
    assert "scripts/backup_stack.py" in text and "scripts/restore_stack.py" in text
    assert "restic backup" in text and "restic forget" in text and "--prune" in text
    assert "restic check" in text
