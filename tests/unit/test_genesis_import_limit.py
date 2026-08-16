"""The size of plan Genesis will accept for import.

The cap exists to bound an LLM call, not to bound a plan. It was originally 20,000
characters, which is smaller than a real MasterPlan — so the feature rejected the
documents it was built for. Measured against the owner's own corpus on 2026-08-16:

    V1   8,184 chars     V2  65,671     V3  50,900     V4  22,749

V4 — the version anyone would actually import — missed the old cap by 2,749 characters.

These tests pin the two properties that matter and are easy to regress in opposite
directions: the cap must clear a real plan, and it must still exist.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

handlers = pytest.importorskip("apps.masterplan.syscalls.syscall_handlers")

# Real measurements, so a future change to the cap is checked against actual documents
# rather than against a number someone liked.
MEASURED_PLAN_SIZES = {"V1": 8_184, "V2": 65_671, "V3": 50_900, "V4": 22_749}


def test_cap_clears_every_measured_plan_version():
    largest = max(MEASURED_PLAN_SIZES.values())
    assert handlers.MAX_IMPORT_CHARS >= largest, (
        f"cap {handlers.MAX_IMPORT_CHARS} rejects a real plan version ({largest} chars). "
        "The cap bounds the LLM call; it must not bound the user's plan."
    )


def test_cap_clears_the_version_actually_imported_with_headroom():
    # V4 is the live plan. A cap that only just clears it regresses the moment the plan
    # is edited, which is the failure this test exists to prevent.
    v4 = MEASURED_PLAN_SIZES["V4"]
    assert handlers.MAX_IMPORT_CHARS >= v4 * 2, (
        f"cap {handlers.MAX_IMPORT_CHARS} leaves under 2x headroom over V4 ({v4} chars); "
        "editing the plan would silently break import again."
    )


def test_cap_still_exists_and_is_bounded():
    # Unbounded input to an LLM is a cost and latency hazard, on a path that already has
    # one (FR-15). Raising the ceiling must not become removing it.
    assert isinstance(handlers.MAX_IMPORT_CHARS, int)
    assert 0 < handlers.MAX_IMPORT_CHARS <= 200_000


def test_cap_fits_the_model_that_reads_it():
    # call_genesis_import_llm uses gpt-4o-mini (128k-token context). At the conservative
    # ~4 chars/token rule the cap must stay well inside that, leaving room for the system
    # prompt and the JSON response.
    approx_tokens = handlers.MAX_IMPORT_CHARS / 4
    assert approx_tokens < 100_000, (
        f"cap is ~{approx_tokens:.0f} tokens, too close to the model's 128k context"
    )


def test_oversized_import_is_refused_with_both_numbers():
    """A refusal has to say what was sent and what is allowed, or it is unactionable."""
    payload = {"content": "x" * (handlers.MAX_IMPORT_CHARS + 1)}

    with pytest.raises(ValueError) as excinfo:
        handlers._handle_genesis_import_plan(payload, ctx=None)

    message = str(excinfo.value)
    assert str(handlers.MAX_IMPORT_CHARS) in message, "refusal must state the limit"
    assert str(handlers.MAX_IMPORT_CHARS + 1) in message, "refusal must state the actual size"


def test_empty_import_is_refused_before_any_size_check():
    with pytest.raises(ValueError, match="requires 'content'"):
        handlers._handle_genesis_import_plan({"content": "   "}, ctx=None)
