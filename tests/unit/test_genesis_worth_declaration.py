"""Worth declared in Genesis must come from the user's mouth, or not exist.

The Worth axis of the Infinity score has held **0 declarations** since it was built. The
storage, the per-kind scoring and the API were all correct; nothing ever called them
(`TECH_DEBT.md` → `SOAK-THEN-FLIP-1`). Genesis is where the owner already says what matters,
so the number is captured there as a by-product rather than solicited by a form.

★ **These tests are almost entirely about what must NOT be recorded.** An LLM asked to fill in
a worth field will fill it in, and a fabricated declaration is indistinguishable from a real
one once it is a row — nothing downstream can tell them apart, the Worth axis simply moves and
the score looks healthier. That is worse than the honest zero it replaces, and it is a failure
this repo has already shipped once in a different costume (`SOAK_AUDIT_2026-08-15` §3: a
learned calibrator "winning" by memorising a constant, reported as a 0.0000 MAE).

So the defence is code, not prompt text: every declaration carries the user's words, and those
words must be found in a **user** turn of the transcript. Prompt rules drift between model
versions; a substring check does not.
"""

from __future__ import annotations

import os
import pathlib
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

genesis_worth = pytest.importorskip("apps.masterplan.services.genesis_worth")
from apps.analytics.value_declaration import (  # noqa: E402
    VALID_TARGET_TYPES,
    WORTH_ORDINAL_LEVELS,
)

merge_declared_worth = genesis_worth.merge_declared_worth
normalize_entry = genesis_worth.normalize_entry
quote_is_supported = genesis_worth.quote_is_supported
supported_declarations = genesis_worth.supported_declarations


SAID = "the ethics framework is the one that actually matters — the whole thing is pointless without it"


def _transcript(*turns: tuple[str, str]) -> list[dict]:
    return [{"role": role, "content": content} for role, content in turns]


def _entry(**overrides):
    entry = {
        "label": "Ethical AI Framework",
        "kind": "strategic",
        "value": "critical",
        "quote": "the whole thing is pointless without it",
    }
    entry.update(overrides)
    return entry


# ── quote or it did not happen ─────────────────────────────────────────────────────────

def test_a_quote_the_user_actually_said_is_supported():
    assert quote_is_supported(
        "the whole thing is pointless without it", _transcript(("user", SAID))
    )


def test_a_quote_nobody_said_is_not():
    assert not quote_is_supported(
        "this is critical to everything I am building", _transcript(("user", SAID))
    )


def test_the_assistants_own_words_do_not_count():
    """★ The load-bearing case.

    Genesis reflects understanding back in its own words by design, so its replies are full of
    plausible statements about what matters. Quoting itself would be fabrication *with a
    citation* — which is worse than fabrication without one, because it survives review.
    """
    transcript = _transcript(
        ("user", "let's talk about the framework"),
        ("assistant", "So the ethics framework sounds absolutely critical to the whole plan."),
    )

    assert not quote_is_supported("absolutely critical to the whole plan", transcript)


def test_an_ellipsis_elides_rather_than_paraphrases():
    """The model is told to elide long passages; each fragment is checked independently."""
    assert quote_is_supported("the ethics framework…pointless without it", _transcript(("user", SAID)))


def test_fragments_must_come_from_one_turn():
    """Words said on different days, spliced together, are not a quote."""
    transcript = _transcript(
        ("user", "the ethics framework is where I keep coming back to"),
        ("user", "revenue is what keeps the lights on around here"),
    )

    assert not quote_is_supported("the ethics framework…keeps the lights on", transcript)


def test_curly_punctuation_does_not_break_a_real_quote():
    """Quoting is retyping, and models normalise apostrophes while doing it.

    Matching raw would reject genuine quotes over a curly apostrophe — quote-or-drop would
    discard everything and read as the feature not working.
    """
    transcript = _transcript(("user", "it’s the piece I can’t ship without — genuinely critical"))

    assert quote_is_supported("it's the piece I can't ship without", transcript)


def test_a_quote_too_short_to_be_evidence_is_rejected():
    """"critical" appears in half the transcript; matching it proves nothing."""
    assert not quote_is_supported("critical", _transcript(("user", SAID)))


def test_a_missing_quote_is_rejected():
    for missing in (None, "", "   ", 42):
        assert not quote_is_supported(missing, _transcript(("user", SAID)))


# ── the value contract ─────────────────────────────────────────────────────────────────

def test_an_ordinal_kind_takes_a_level_not_a_number():
    """8 is not "high".

    Coercing it would let the false precision the ordinal scale exists to remove back in
    through the side door, and silently — the caller would think it had said something
    finer-grained than the scale supports.
    """
    assert normalize_entry(_entry(kind="strategic", value=8)) is None
    assert normalize_entry(_entry(kind="strategic", value="high")) is not None


def test_every_ordinal_level_is_accepted():
    for level in WORTH_ORDINAL_LEVELS:
        assert normalize_entry(_entry(kind="intrinsic", value=level)) is not None


def test_a_cardinal_kind_takes_a_number_not_a_level():
    assert normalize_entry(_entry(kind="monetary_potential", value="critical")) is None
    assert normalize_entry(_entry(kind="monetary_potential", value=50000))["value"] == 50000.0


def test_a_negative_figure_is_rejected():
    assert normalize_entry(_entry(kind="monetary_potential", value=-5)) is None


def test_an_invented_kind_is_rejected():
    assert normalize_entry(_entry(kind="vibes")) is None


def test_an_entry_without_a_quote_is_rejected_before_anything_else():
    assert normalize_entry(_entry(quote=None)) is None


def test_the_model_cannot_award_itself_verification():
    """`verified` is set by our code alone.

    `normalize_entry` rebuilds each entry from label/kind/value/quote, so a model emitting
    `"verified": true` has it discarded before anything looks at it.
    """
    assert "verified" not in normalize_entry(_entry(verified=True))


# ── accumulating across turns ──────────────────────────────────────────────────────────

def test_worth_survives_a_turn_about_something_else():
    """★ The failure that would have made this feature look like it worked and hold nothing.

    Every other field in `summarized_state` is REPLACED on each turn. Each turn's extraction
    reports only what that turn established, so a turn about anything else returns `[]` — which
    under replacement wipes every prior declaration. A single-turn test would still pass.
    """
    transcript = _transcript(("user", SAID))
    after_first = merge_declared_worth([], [_entry()], transcript)
    assert len(after_first) == 1

    after_second = merge_declared_worth(after_first, [], _transcript(("user", "anyway, about timing")))

    assert len(after_second) == 1


def test_restating_the_same_kind_updates_it():
    transcript = _transcript(("user", SAID))
    first = merge_declared_worth([], [_entry(value="high")], transcript)
    second = merge_declared_worth(first, [_entry(value="critical")], transcript)

    assert len(second) == 1
    assert second[0]["value"] == "critical"


def test_the_same_thing_can_hold_several_kinds_at_once():
    """A domain both strategically critical and worth real money is the normal case.

    (label, kind) is the merge key precisely because #289 made it the DB's upsert key too.
    """
    said = "the framework is critical, and honestly it could be worth 50000 on its own"
    transcript = _transcript(("user", said))
    entries = merge_declared_worth(
        [],
        [
            _entry(kind="strategic", value="critical", quote="the framework is critical"),
            _entry(kind="monetary_potential", value=50000, quote="it could be worth 50000 on its own"),
        ],
        transcript,
    )

    assert {e["kind"] for e in entries} == {"strategic", "monetary_potential"}


def test_verification_happens_on_the_turn_the_words_arrive():
    """The transcript is trimmed to its most recent entries.

    Verifying only at lock would silently discard a real declaration from early in a long
    session — for a reason that has nothing to do with whether the user said it.
    """
    live = merge_declared_worth([], [_entry()], _transcript(("user", SAID)))
    assert live[0]["verified"] is True

    # …and the turn later falls out of the window entirely.
    trimmed = _transcript(("user", "much later, about something else"))
    supported, dropped = supported_declarations(live, trimmed)

    assert len(supported) == 1
    assert dropped == []


def test_an_unverified_entry_is_checked_at_lock():
    """State written before this existed, or edited by hand, gets no free pass."""
    forged = [_entry(quote="I said no such thing at any point")]

    supported, dropped = supported_declarations(forged, _transcript(("user", SAID)))

    assert supported == []
    assert len(dropped) == 1


def test_an_unsupported_extraction_is_never_marked_verified():
    entries = merge_declared_worth(
        [], [_entry(quote="a plausible sentence nobody typed")], _transcript(("user", SAID))
    )

    assert entries[0]["verified"] is False


# ── the target contract ────────────────────────────────────────────────────────────────

def test_domain_is_a_valid_target_type():
    """A core domain is what Genesis actually talks about; `other` loses that it is one."""
    assert "domain" in VALID_TARGET_TYPES


def test_the_worth_vocabulary_matches_analytics():
    """★ The cost of the boundary, paid deliberately.

    Masterplan reaches analytics through `sys.v1.analytics.declare_worth` and must not import
    `apps.analytics.*` — `test_import_boundaries` pins that, and the syscall migration behind it
    is why masterplan's task and automation integrations are call-time syscalls too. So the
    kinds and levels are restated in `genesis_worth`, and a copy is a thing that drifts.

    Validating locally is what buys the duplication: an invalid kind or level is dropped at
    extraction, on the turn it was made, instead of raising from a syscall at lock — by which
    point the words that would let anyone check it are three screens up.
    """
    from apps.analytics import value_declaration as canonical

    assert set(genesis_worth.VALID_WORTH_KINDS) == canonical.VALID_WORTH_KINDS
    assert set(genesis_worth.ORDINAL_WORTH_KINDS) == canonical.ORDINAL_WORTH_KINDS
    assert set(genesis_worth.CARDINAL_WORTH_KINDS) == canonical.CARDINAL_WORTH_KINDS
    assert set(genesis_worth.WORTH_ORDINAL_LEVELS) == set(canonical.WORTH_ORDINAL_LEVELS)


def test_genesis_worth_does_not_import_analytics():
    """The boundary itself, not just its consequence."""
    source = (
        pathlib.Path(genesis_worth.__file__).read_text(encoding="utf-8")
    )
    assert "from apps.analytics" not in source
    assert "import apps.analytics" not in source


@pytest.fixture
def recorder(monkeypatch):
    """Capture what would be written, without a database.

    `record_genesis_declarations` resolves `_declare_worth` — the `sys.v1.analytics.declare_worth`
    shim — as a module global, so patching the attribute is enough, and it keeps the boundary
    being tested explicit.
    """
    calls: list[dict] = []

    def _record(_db, **kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(genesis_worth, "_declare_worth", _record)
    return calls


def _record_one(declared_worth, *, masterplan_id=1):
    return genesis_worth.record_genesis_declarations(
        None,
        user_id=uuid.uuid4(),
        masterplan_id=masterplan_id,
        declared_worth=declared_worth,
        transcript=_transcript(("user", SAID)),
    )


def test_a_labelled_declaration_targets_a_domain_and_an_unlabelled_one_the_plan(recorder):
    _record_one([_entry(verified=True), _entry(label=None, verified=True)], masterplan_id=17)

    assert [call["target_type"] for call in recorder] == ["domain", "masterplan"]
    assert recorder[0]["target_id"] == "ethical ai framework"
    assert recorder[1]["target_id"] == "17"


def test_the_quote_is_stored_as_the_audit_trail(recorder):
    """A declaration must stay checkable after its session scrolls out of the window."""
    _record_one([_entry(verified=True)])

    assert "the whole thing is pointless without it" in recorder[0]["note"]


def test_a_fabricated_declaration_never_reaches_the_recorder(recorder):
    """The end of the line for §4's failure mode: no quote in a user turn, no row."""
    result = _record_one([_entry(quote="a plausible sentence nobody typed")])

    assert recorder == []
    assert result["recorded"] == []
    assert len(result["dropped"]) == 1


def test_a_failed_write_is_reported_not_raised(monkeypatch):
    """Locking a plan is the user's act; a worth row must not be able to undo it."""

    def _boom(_db, **_kwargs):
        raise RuntimeError("declare_worth syscall failed")

    monkeypatch.setattr(genesis_worth, "_declare_worth", _boom)
    result = _record_one([_entry(verified=True)])

    assert result["recorded"] == []
    assert len(result["dropped"]) == 1


def test_nothing_declared_records_nothing():
    """The honest zero. An empty conversation must not produce a row."""
    for empty in (None, [], "not a list"):
        supported, dropped = supported_declarations(empty, _transcript(("user", SAID)))
        assert (supported, dropped) == ([], [])


# ── the state merge: where the previous two instances of this shape lost the data ──────

handlers = pytest.importorskip("apps.masterplan.syscalls.syscall_handlers")


def test_a_session_created_before_this_field_existed_still_captures_worth():
    """★ The regression this feature was one line away from being.

    The generic state merge is `if key in current_state and value is not None` — it only
    copies keys ALREADY PRESENT. Every existing Genesis session's `summarized_state` predates
    `declared_worth`, so every declaration made in one would have been dropped on the way in,
    silently, and the feature would have looked like it simply never fired.

    This is the third instance of one shape in this repo: Genesis captures it, the schema drops
    it. Phases lost their identity; success criteria never became goals; worth was never
    captured at all.
    """
    legacy_state = {
        "vision_summary": "a thing", "time_horizon": None, "mechanism_summary": None,
        "assets_summary": None, "inferred_domains": [], "inferred_phases": [],
        "confidence": 0.4,
    }
    assert "declared_worth" not in legacy_state

    merged = handlers._apply_declared_worth(
        dict(legacy_state),
        {"declared_worth": [_entry()]},
        _transcript(("user", SAID)),
    )

    assert len(merged["declared_worth"]) == 1
    assert merged["declared_worth"][0]["verified"] is True


def test_the_seeded_state_carries_the_field():
    """Belt and braces: a new session should not depend on the guard above."""
    merged = handlers._apply_declared_worth({}, {}, [])

    assert merged["declared_worth"] == []


def test_an_absent_state_update_does_not_clear_what_was_declared():
    state = handlers._apply_declared_worth(
        {"declared_worth": []}, {"declared_worth": [_entry()]}, _transcript(("user", SAID))
    )
    later = handlers._apply_declared_worth(state, {}, _transcript(("user", "unrelated turn")))

    assert len(later["declared_worth"]) == 1


# ── the seam itself ────────────────────────────────────────────────────────────────────

def test_the_declare_worth_syscall_is_registered():
    """★ A mis-registered syscall would fail silently, which is the whole problem again.

    `record_genesis_declarations` never raises — locking a plan must not fail because a worth
    row did not persist. So a syscall registered under the wrong name, or not registered at
    all, produces a lock that records nothing and says nothing, which is indistinguishable from
    a conversation in which no worth was stated.
    """
    from AINDY.kernel.syscall_registry import get_registered_syscalls
    from tests.helpers.app_profile import bootstrap_app_models

    bootstrap_app_models(required=True)
    from apps.analytics.syscalls import register_analytics_syscall_handlers

    register_analytics_syscall_handlers()

    registered = get_registered_syscalls()
    names = set(registered) if isinstance(registered, dict) else {
        getattr(entry, "name", entry) for entry in registered
    }
    assert "sys.v1.analytics.declare_worth" in names


def test_a_declaration_dispatched_through_the_syscall_becomes_a_row(db_session):
    """The full seam: masterplan's shim → the syscall → an `intent_value_declarations` row.

    Everything above this point tests the filtering. This tests that a declaration which
    survives it actually reaches storage — the half that four layers of non-fatal error
    handling would otherwise let fail quietly.
    """
    from apps.analytics.syscalls import register_analytics_syscall_handlers
    from apps.analytics.value_declaration import IntentValueDeclaration
    from tests.helpers.app_profile import bootstrap_app_models

    bootstrap_app_models(required=True)
    register_analytics_syscall_handlers()

    user_id = uuid.uuid4()
    result = genesis_worth.record_genesis_declarations(
        db_session,
        user_id=user_id,
        masterplan_id=1,
        declared_worth=[_entry(), _entry(quote="a plausible sentence nobody typed")],
        transcript=_transcript(("user", SAID)),
    )

    assert len(result["recorded"]) == 1
    assert len(result["dropped"]) == 1

    rows = (
        db_session.query(IntentValueDeclaration)
        .filter(IntentValueDeclaration.user_id == user_id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].target_type == "domain"
    assert rows[0].target_id == "ethical ai framework"
    assert rows[0].ordinal_level == "critical"
    assert "pointless without it" in (rows[0].note or "")
