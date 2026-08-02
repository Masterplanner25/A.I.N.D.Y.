"""Genesis as a conversational partner: the transcript it remembers.

Genesis previously sent the model a six-field summary plus the new message and nothing
else, so it could not build on anything said earlier — the reason a "strategic partner"
behaved like a form-filler with a chat interface. These tests cover the window that gets
replayed and the trimming that keeps a never-ending session from growing without bound.

The window builder is deliberately total: a malformed transcript row must be skipped,
not raised on, because a corrupt entry would otherwise make the whole session unusable.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

genesis_ai = pytest.importorskip("apps.masterplan.services.genesis_ai")
handlers = pytest.importorskip("apps.masterplan.syscalls.syscall_handlers")


def _turns(count: int, *, content: str = "hello") -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"{content} {i}", "at": "x"}
        for i in range(count)
    ]


# ── the replay window ─────────────────────────────────────────────────────────


def test_window_preserves_order_and_strips_bookkeeping():
    window = genesis_ai.build_transcript_window(_turns(4))
    assert [m["role"] for m in window] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in window] == ["hello 0", "hello 1", "hello 2", "hello 3"]
    # `at` is storage bookkeeping; the chat API rejects unknown keys.
    assert all(set(m) == {"role", "content"} for m in window)


def test_window_keeps_the_most_recent_turns():
    """Trimmed from the front — the near past is what the current decision needs."""
    window = genesis_ai.build_transcript_window(_turns(30), max_turns=5)
    assert len(window) == 5
    assert [m["content"] for m in window] == [
        "hello 25", "hello 26", "hello 27", "hello 28", "hello 29",
    ]


def test_window_respects_a_character_budget():
    window = genesis_ai.build_transcript_window(
        [{"role": "user", "content": "x" * 100} for _ in range(10)],
        max_turns=10,
        max_chars=250,
    )
    assert len(window) == 2


def test_window_skips_malformed_entries_rather_than_raising():
    transcript = [
        {"role": "user", "content": "kept"},
        {"role": "system", "content": "wrong role"},
        {"role": "assistant", "content": ""},
        {"role": "assistant"},
        {"content": "no role"},
        "not a dict",
        None,
        {"role": "assistant", "content": "also kept"},
    ]
    window = genesis_ai.build_transcript_window(transcript)
    assert [m["content"] for m in window] == ["kept", "also kept"]


@pytest.mark.parametrize("empty", [None, []])
def test_window_of_an_empty_transcript_is_empty(empty):
    assert genesis_ai.build_transcript_window(empty) == []


# ── storage trimming ──────────────────────────────────────────────────────────


def test_transcript_is_trimmed_to_the_cap_keeping_the_newest():
    cap = handlers.MAX_TRANSCRIPT_ENTRIES_STORED
    trimmed = handlers._trim_transcript(_turns(cap + 10))
    assert len(trimmed) == cap
    assert trimmed[-1]["content"] == f"hello {cap + 9}"


def test_short_transcripts_are_left_alone():
    entries = _turns(4)
    assert handlers._trim_transcript(entries) is entries


def test_transcript_entry_shape():
    entry = handlers._transcript_entry("user", "hi")
    assert entry["role"] == "user"
    assert entry["content"] == "hi"
    assert entry["at"]  # ISO timestamp, so the UI can order/label turns


# ── the partner contract in the prompt ────────────────────────────────────────


def test_prompt_tells_the_model_to_decide_readiness_itself():
    """Defect #5 was that Genesis never signalled readiness — the user had to say a phrase.

    The prompt gave no criteria for synthesis_ready, so the model never set it. These
    assertions are deliberately about *behaviour the prompt must ask for*, not wording.
    """
    prompt = genesis_ai.GENESIS_SYSTEM_PROMPT.lower()
    assert "synthesis_ready" in prompt
    assert "do not wait to be asked" in prompt
    assert "0.6" in prompt  # an explicit confidence bar, not a vibe


def test_prompt_asks_for_partner_behaviour_not_form_filling():
    prompt = genesis_ai.GENESIS_SYSTEM_PROMPT.lower()
    assert "never re-ask" in prompt
    assert "push back" in prompt
    # The distinguishing instruction: probe the weak part, not the next empty field.
    assert "rather than the next empty field" in prompt
