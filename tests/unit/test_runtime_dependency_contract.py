from __future__ import annotations

from pathlib import Path
import tomllib

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[2]


def test_apps_repo_declares_bounded_runtime_dependency():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    requirements = [Requirement(item) for item in pyproject["project"]["dependencies"]]
    runtime_requirement = next(req for req in requirements if req.name == "aindy-runtime")

    assert str(runtime_requirement.specifier) == "<3.0,>=2.11.0"
    assert any(spec.operator == "<" for spec in runtime_requirement.specifier)
    assert any(spec.operator == ">=" for spec in runtime_requirement.specifier)


# ── RUNTIME-PIN-FLOAT-1: the build pin, and keeping it honest ──────────────────────────
#
# `pyproject.toml` declares a RANGE — correct for a published package, wrong for a build,
# because pip resolves it to whatever is newest on PyPI on the day. `constraints.txt` pins
# the exact version this repo has adopted, and the Dockerfile and all four CI workflows
# install with `-c constraints.txt` so an image stops depending on its build date.
#
# The failure mode these guard is the pin and the floor drifting apart: a floor raised
# during an adoption pass while the constraint is forgotten leaves CI and the image
# silently validating a runtime nobody adopted. That is the original defect wearing a
# different hat, so it fails here instead.


def _constraint_pins() -> dict[str, str]:
    """Parse constraints.txt into {name: exact version}, ignoring comments and blanks."""
    text = (ROOT / "constraints.txt").read_text(encoding="utf-8")
    pins: dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        specs = list(requirement.specifier)
        assert len(specs) == 1 and specs[0].operator == "==", (
            f"constraints.txt must pin exactly, got {line!r} — a range here defeats the point"
        )
        pins[requirement.name] = specs[0].version
    return pins


def test_constraints_file_pins_the_runtime_exactly():
    pins = _constraint_pins()
    assert "aindy-runtime" in pins, "constraints.txt must pin aindy-runtime"


def test_constraint_pin_satisfies_the_declared_range():
    """The pinned build version must be legal under the published compatibility range.

    Pinning a version the package declares itself incompatible with would ship an image
    that its own metadata forbids.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [Requirement(item) for item in pyproject["project"]["dependencies"]]
    runtime_requirement = next(req for req in requirements if req.name == "aindy-runtime")

    pinned = _constraint_pins()["aindy-runtime"]
    assert runtime_requirement.specifier.contains(pinned), (
        f"constraints.txt pins aindy-runtime=={pinned}, which is outside "
        f"pyproject's {runtime_requirement.specifier}"
    )


def test_constraint_pin_equals_the_floor():
    """The pin must BE the floor, not merely satisfy it.

    Stricter than the test above on purpose. The floor is raised by an adoption pass, and
    the adopted version is the one that was tested — so the pin and the floor are the same
    fact written twice. Allowing the pin to sit above the floor would let the image ship a
    runtime no adoption pass covered while every check still passed.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [Requirement(item) for item in pyproject["project"]["dependencies"]]
    runtime_requirement = next(req for req in requirements if req.name == "aindy-runtime")

    floor = next(
        spec.version for spec in runtime_requirement.specifier if spec.operator == ">="
    )
    assert _constraint_pins()["aindy-runtime"] == floor, (
        "constraints.txt and the pyproject floor disagree — raise both in the same "
        "adoption pass, or the image ships an unadopted runtime"
    )


def test_build_paths_install_with_the_constraints_file():
    """The Dockerfile and every CI workflow must actually USE the pin.

    A constraints file nothing passes `-c` to is decoration. This is the assertion that
    makes the file load-bearing rather than aspirational.
    """
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "-c constraints.txt" in dockerfile, "Dockerfile does not install with the pin"
    assert "COPY pyproject.toml README.md constraints.txt" in dockerfile, (
        "Dockerfile must COPY constraints.txt before installing, or the -c flag hits a "
        "missing file and the build fails"
    )

    workflows = ROOT / ".github" / "workflows"
    unpinned: list[str] = []
    for path in sorted(workflows.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            # Only lines that install THIS package; other pip installs (ruff, tooling)
            # are irrelevant to the runtime pin.
            if stripped.startswith("python -m pip install -e ."):
                if "-c constraints.txt" not in stripped:
                    unpinned.append(f"{path.name}: {stripped}")
    assert not unpinned, "CI installs this package without the runtime pin:\n" + "\n".join(unpinned)
