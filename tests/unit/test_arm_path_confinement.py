"""ARM path confinement — walk log item 20.

ARM analyzes files on the **server's** filesystem (no upload, no repo connection), so the
only question that matters is whether a requested path belongs to this application. Before
this guard existed the validator answered a different question — is the suffix allowed, does
the path contain a blocked segment — which let anything with an allowlisted extension through
from anywhere on the host, and its contents were then sent to an external LLM provider.

The escapes asserted below are the ones verified live against the running container and
recorded in the walk log:

    /usr/local/lib/python3.11/this.py  -> ALLOWED   (site-packages source)
    /app/apps/arm/models.py            -> ALLOWED   (correctly, it is ours)
    /etc/hostname                      -> blocked, but only for lacking an extension

`/etc/passwd` and `../../etc/hosts` were likewise refused for the *wrong reason* — no
allowlisted suffix — which is why an extension guess is not a containment control.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.app_profile


# Imported lazily, NOT at module scope. A module-level `import apps.arm...` runs at pytest
# COLLECTION time — before any test executes — which pulls the `apps.arm` chain in ahead of
# the plugin bootstrap. Doing that here made `test_reasoning_nodus_apply` fail: its Nodus
# workflow was no longer registered by the time it ran, so the VM path silently fell back
# and returned `{'data': {}}`. The failure surfaced in a different file, with nothing in it
# changed — worth knowing before adding another `apps.*` import to a test module header.
@pytest.fixture
def SecurityValidator():
    from apps.arm.services.deepseek.security_deepseek import SecurityValidator as _SV
    return _SV


@pytest.fixture
def resolve_project_root():
    from apps.arm.services.deepseek.security_deepseek import resolve_project_root as _r
    return _r


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root with one legitimately analyzable file."""
    root = tmp_path / "app"
    (root / "apps" / "arm").mkdir(parents=True)
    (root / "apps" / "arm" / "models.py").write_text("x = 1\n", encoding="utf-8")
    return root


@pytest.fixture
def validator(project: Path, SecurityValidator):
    return SecurityValidator({"project_root": str(project)})


def test_file_inside_the_root_is_allowed(validator, project):
    resolved = validator.validate_file_path(str(project / "apps" / "arm" / "models.py"))
    assert resolved == (project / "apps" / "arm" / "models.py").resolve()


def test_allowlisted_extension_outside_the_root_is_refused(validator, tmp_path):
    """The core escape: a .py file elsewhere on the host used to pass every check."""
    outside = tmp_path / "elsewhere" / "this.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("import this\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        validator.validate_file_path(str(outside))
    assert exc.value.status_code == 403
    assert "outside the analyzable project root" in str(exc.value.detail)


def test_refusal_is_for_containment_not_for_the_suffix(validator, tmp_path):
    """A .yaml outside the root must be refused as 403, not 422.

    422 would mean the extension guard caught it, which is the pre-fix behaviour dressed
    up — it would still let a .py through.
    """
    outside = tmp_path / "elsewhere" / "deploy.yaml"
    outside.parent.mkdir(parents=True)
    outside.write_text("secret: not-really\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        validator.validate_file_path(str(outside))
    assert exc.value.status_code == 403


def test_traversal_out_of_the_root_is_refused(validator, project, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        validator.validate_file_path(str(project / "apps" / ".." / ".." / "outside.py"))
    assert exc.value.status_code == 403


def test_containment_is_checked_before_existence(validator, tmp_path):
    """A non-existent path outside the root reports 403, not 404.

    404-before-403 would turn the validator into a filesystem existence oracle for paths
    the caller has no business asking about.
    """
    with pytest.raises(HTTPException) as exc:
        validator.validate_file_path(str(tmp_path / "nope" / "absent.py"))
    assert exc.value.status_code == 403


def test_symlink_escaping_the_root_is_refused(validator, project, tmp_path):
    """`.resolve()` follows symlinks, so a link inside the root pointing out is caught."""
    target = tmp_path / "secret_source.py"
    target.write_text("x = 1\n", encoding="utf-8")
    link = project / "apps" / "link.py"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")

    with pytest.raises(HTTPException) as exc:
        validator.validate_file_path(str(link))
    assert exc.value.status_code == 403


def test_blocked_segments_still_apply_inside_the_root(validator, project):
    """Containment is the primary control; the existing allowlist stays as a second layer."""
    env_dir = project / "secrets"
    env_dir.mkdir()
    target = env_dir / "config.json"
    target.write_text("{}", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        validator.validate_file_path(str(target))
    assert exc.value.status_code == 403
    assert "secrets" in str(exc.value.detail)


def test_root_defaults_to_cwd_and_honours_the_env_override(tmp_path, monkeypatch, SecurityValidator, resolve_project_root):
    monkeypatch.delenv("AINDY_ARM_PROJECT_ROOT", raising=False)
    assert resolve_project_root() == Path.cwd().resolve()

    monkeypatch.setenv("AINDY_ARM_PROJECT_ROOT", str(tmp_path))
    assert resolve_project_root() == tmp_path.resolve()
    assert SecurityValidator().project_root == tmp_path.resolve()

    # An explicit config value wins over the environment.
    other = tmp_path / "other"
    other.mkdir()
    assert SecurityValidator({"project_root": str(other)}).project_root == other.resolve()


def test_package_and_module_export_one_implementation(SecurityValidator):
    """The duplicate in __init__.py was importable and would have missed this fix."""
    from apps.arm.services.deepseek import SecurityValidator as FromPackage

    assert FromPackage is SecurityValidator
