"""The draft loop: analyse, edit, re-analyse, and see what moved.

`SEO_EDITING_AID_SPEC` §4 — the last unbuilt piece. Everything the SEO tool does is a
measurement, and until a draft existed as a unit each one was taken once and forgotten:
`search_history` rows existed, but nothing said two of them were the same piece at different
times, so the before/after question could not be asked at all.

★ **Retention is proposed, never enforced.** Owner's call, 2026-09-07: *"every analysis with a
prune/deletion every so often prompted by the system."* Most of the tests below are about that
boundary, because the failure mode is quiet: a silent cap would delete the *earliest* analyses
— exactly the ones a comparison is measured against — and it would do it at the moment the
history first became long enough to be interesting.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.search.models.seo_draft import SeoDraft, SeoDraftAnalysis
from apps.search.services import draft_service

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
OTHER_USER = uuid.uuid4()


def _make_draft(db, **kwargs):
    payload = {"name": "Ethics and Accountability", "content": "Some body text.", **kwargs}
    return draft_service.create_draft(db, user_id=kwargs.pop("user_id", USER), **payload)


def _record(db, draft_id, *, word_count=900, readability=55.0, score=0.6, at=None, user_id=USER):
    """Record an analysis, optionally back-dating it so ordering is deterministic."""
    recorded = draft_service.record_analysis(
        db,
        user_id=user_id,
        draft_id=draft_id,
        result={
            "word_count": word_count,
            "readability": readability,
            "search_score": score,
            "title_analysis": {"characters": 42},
        },
    )
    if at is not None and recorded:
        row = db.query(SeoDraftAnalysis).filter(SeoDraftAnalysis.id == recorded["id"]).first()
        row.created_at = at
        db.commit()
    return recorded


# ── the draft is the unit ─────────────────────────────────────────────────────────────

def test_a_draft_is_named_by_the_writer(db_session):
    draft = _make_draft(db_session, name="  The Missing Layer  ")

    # A list of "Analysis 2026-09-07 14:32" is the pile of dated scorecards this replaces.
    assert draft["name"] == "The Missing Layer"


def test_a_draft_without_a_name_is_refused(db_session):
    with pytest.raises(ValueError):
        draft_service.create_draft(db_session, user_id=USER, name="   ")


def test_target_keywords_are_remembered_on_the_draft(db_session):
    """★ §5 open question 1, answered by the unit rather than by a policy.

    Retyping targets on every analysis is how they end up subtly different between runs — and
    two analyses measured against different targets cannot be compared, silently, because
    nothing would say so.
    """
    draft = _make_draft(db_session, target_keywords=["runtime framework", "nodus"])
    fetched = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])

    assert fetched["target_keywords"] == ["runtime framework", "nodus"]


def test_a_draft_carries_the_published_url_from_the_start(db_session):
    """The one field that makes a draft matchable to the drop point it becomes.

    Adding it later would leave it null for every draft written before someone thought of it.
    """
    draft = _make_draft(db_session)
    draft_service.update_draft(
        db_session, user_id=USER, draft_id=draft["id"],
        published_url="https://example.com/piece",
    )
    fetched = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])

    assert fetched["published_url"] == "https://example.com/piece"


def test_an_omitted_field_is_not_wiped(db_session):
    """`None` means "not supplied" — only an explicit empty value clears something."""
    draft = _make_draft(db_session, title="A Title", target_keywords=["alpha"])
    draft_service.update_draft(db_session, user_id=USER, draft_id=draft["id"], content="new body")
    fetched = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])

    assert fetched["title"] == "A Title"
    assert fetched["target_keywords"] == ["alpha"]
    assert fetched["content"] == "new body"


def test_a_draft_belongs_to_its_owner(db_session):
    draft = _make_draft(db_session)

    assert draft_service.get_draft(db_session, user_id=OTHER_USER, draft_id=draft["id"]) is None
    assert draft_service.update_draft(
        db_session, user_id=OTHER_USER, draft_id=draft["id"], name="theirs"
    ) is None
    assert draft_service.delete_draft(db_session, user_id=OTHER_USER, draft_id=draft["id"]) is False


def test_deleting_a_draft_takes_its_analyses(db_session):
    """An orphaned analysis is unreachable, not merely untidy."""
    draft = _make_draft(db_session)
    _record(db_session, draft["id"])

    assert draft_service.delete_draft(db_session, user_id=USER, draft_id=draft["id"]) is True
    assert db_session.query(SeoDraftAnalysis).filter(
        SeoDraftAnalysis.draft_id == draft["id"]
    ).count() == 0


def test_a_listing_omits_the_body_text(db_session):
    """The largest field, and a picker does not need it."""
    _make_draft(db_session, content="x" * 5000)
    listing = draft_service.list_drafts(db_session, user_id=USER)

    assert listing and "content" not in listing[0]
    assert listing[0]["analysis_count"] == 0


# ── the comparison, which is the whole point ──────────────────────────────────────────

def test_one_analysis_has_nothing_to_compare_against(db_session):
    draft = _make_draft(db_session)
    _record(db_session, draft["id"])
    fetched = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])

    assert fetched["deltas"]["available"] is False
    assert fetched["deltas"]["reason"]


def test_the_first_analysis_becomes_the_baseline(db_session):
    """Not a user-set flag: "before" is only meaningful against the earliest reading."""
    draft = _make_draft(db_session)
    first = _record(db_session, draft["id"])
    second = _record(db_session, draft["id"])

    assert first["is_baseline"] is True
    assert second["is_baseline"] is False


def test_deltas_report_both_since_last_time_and_since_the_start(db_session):
    """★ Both, deliberately.

    "Since last time" is what you act on during a session; "since the baseline" is what tells
    you whether the session went anywhere. A tool that reports only the first can show four
    consecutive improvements that net to nothing.
    """
    now = datetime.now(timezone.utc)
    draft = _make_draft(db_session)
    _record(db_session, draft["id"], word_count=500, readability=40.0, at=now - timedelta(days=2))
    _record(db_session, draft["id"], word_count=900, readability=60.0, at=now - timedelta(days=1))
    _record(db_session, draft["id"], word_count=950, readability=58.0, at=now)

    deltas = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])["deltas"]

    assert deltas["available"] is True
    assert deltas["since_previous"]["word_count"] == 50
    assert deltas["since_baseline"]["word_count"] == 450
    assert deltas["since_previous"]["readability"] == -2.0
    assert deltas["since_baseline"]["readability"] == 18.0


def test_a_metric_missing_from_the_older_reading_is_null_not_zero(db_session):
    """★ A metric that did not exist yet has not "stayed the same".

    Title analysis and coverage both arrived after the first version of this tool, so old rows
    genuinely lack them, and reporting 0 would read as "no change".
    """
    now = datetime.now(timezone.utc)
    draft = _make_draft(db_session)
    old = draft_service.record_analysis(
        db_session, user_id=USER, draft_id=draft["id"], result={"word_count": 500}
    )
    row = db_session.query(SeoDraftAnalysis).filter(SeoDraftAnalysis.id == old["id"]).first()
    row.created_at = now - timedelta(days=1)
    db_session.commit()
    _record(db_session, draft["id"], at=now)

    deltas = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])["deltas"]
    assert deltas["since_previous"]["title_characters"] is None
    assert deltas["since_previous"]["word_count"] == 400


# ── ★ retention: the system proposes, the person decides ──────────────────────────────

def _fill(db_session, draft_id, count):
    now = datetime.now(timezone.utc)
    for index in range(count):
        _record(db_session, draft_id, word_count=500 + index, at=now - timedelta(minutes=count - index))


def test_a_short_history_is_never_mentioned(db_session):
    """The prompt must not appear during a normal editing session."""
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 5)
    retention = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])["retention"]

    assert retention["prune_suggested"] is False
    assert retention["total"] == 5


def test_the_system_raises_the_subject_past_the_threshold(db_session):
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], draft_service.PRUNE_PROMPT_AFTER + 6)
    retention = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])["retention"]

    assert retention["prune_suggested"] is True
    assert retention["prunable_count"] > 0


def test_the_proposal_names_what_would_go(db_session):
    """★ "Delete 14 old analyses" asks for consent to something the person cannot see."""
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 40)
    retention = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])["retention"]

    assert len(retention["prunable_ids"]) == retention["prunable_count"]
    assert retention["oldest_prunable"]
    # The recent window and the baseline are both excluded, and it says so.
    assert retention["keeps_recent"] == draft_service.PRUNE_KEEP_RECENT
    assert retention["keeps_baseline"] is True


def test_the_baseline_is_never_offered_for_deletion(db_session):
    """Pruning it would destroy the comparison the pruning was making room for."""
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 40)
    detail = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])
    baseline_id = next(a["id"] for a in detail["analyses"] if a["is_baseline"])

    assert baseline_id not in detail["retention"]["prunable_ids"]


def test_nothing_is_deleted_without_being_asked(db_session):
    """★ The load-bearing test. Reading a draft must never remove anything.

    A silent cap would delete the earliest analyses — exactly the ones a before/after
    comparison is measured against — at the moment the history first became interesting.
    """
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 60)

    for _ in range(3):
        draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])

    assert db_session.query(SeoDraftAnalysis).filter(
        SeoDraftAnalysis.draft_id == draft["id"]
    ).count() == 60


def test_pruning_deletes_exactly_what_was_confirmed(db_session):
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 40)
    retention = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])["retention"]
    chosen = retention["prunable_ids"][:5]

    result = draft_service.prune_analyses(
        db_session, user_id=USER, draft_id=draft["id"], analysis_ids=chosen
    )

    assert result["deleted"] == 5
    assert db_session.query(SeoDraftAnalysis).filter(
        SeoDraftAnalysis.draft_id == draft["id"]
    ).count() == 35


def test_pruning_uses_the_ids_it_was_given_not_a_recomputed_set(db_session):
    """★ Between a proposal and its answer, a new analysis may have been recorded.

    A prune that re-derived "what is prunable" would delete something the person was never
    shown — which is the same consent failure as a silent cap, arriving one step later.
    """
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 40)
    proposal = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])["retention"]
    chosen = proposal["prunable_ids"][:3]

    _record(db_session, draft["id"])  # the history moved while the person was deciding

    result = draft_service.prune_analyses(
        db_session, user_id=USER, draft_id=draft["id"], analysis_ids=chosen
    )
    remaining = {
        a.id for a in db_session.query(SeoDraftAnalysis).filter(
            SeoDraftAnalysis.draft_id == draft["id"]
        ).all()
    }

    assert result["deleted"] == 3
    assert not (set(chosen) & remaining)
    assert len(remaining) == 38


def test_a_prune_refuses_the_baseline_even_when_asked(db_session):
    """The service does not rely on the proposal having excluded it."""
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 40)
    detail = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])
    baseline_id = next(a["id"] for a in detail["analyses"] if a["is_baseline"])

    result = draft_service.prune_analyses(
        db_session, user_id=USER, draft_id=draft["id"], analysis_ids=[baseline_id]
    )

    assert result["deleted"] == 0
    assert result["refused"] == 1
    assert db_session.query(SeoDraftAnalysis).filter(
        SeoDraftAnalysis.id == baseline_id
    ).count() == 1


def test_an_empty_prune_request_does_nothing(db_session):
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 30)

    result = draft_service.prune_analyses(
        db_session, user_id=USER, draft_id=draft["id"], analysis_ids=[]
    )

    assert result["deleted"] == 0
    assert db_session.query(SeoDraftAnalysis).count() == 30


def test_an_id_that_no_longer_exists_is_reported_not_raised(db_session):
    """Answering a stale proposal is normal, not an error."""
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 30)

    result = draft_service.prune_analyses(
        db_session, user_id=USER, draft_id=draft["id"], analysis_ids=["not-a-real-id"]
    )

    assert result["deleted"] == 0
    assert result["not_found"] == 1


def test_pruning_another_persons_draft_does_nothing(db_session):
    draft = _make_draft(db_session)
    _fill(db_session, draft["id"], 30)

    result = draft_service.prune_analyses(
        db_session, user_id=OTHER_USER, draft_id=draft["id"], analysis_ids=["anything"]
    )

    assert result["deleted"] == 0
    assert db_session.query(SeoDraftAnalysis).count() == 30


# ── recording ─────────────────────────────────────────────────────────────────────────

def test_an_analysis_denormalises_what_comparison_needs(db_session):
    """Comparing two analyses is the point of the table; unpacking JSON per read makes the
    common operation the expensive one."""
    draft = _make_draft(db_session)
    recorded = _record(db_session, draft["id"], word_count=1234, readability=61.5, score=0.71)

    assert recorded["word_count"] == 1234
    assert recorded["readability"] == 61.5
    assert recorded["title_characters"] == 42
    # `search_score` is no longer recorded or served (spec §5 Q3, dropped 2026-09-11); the
    # column exists, nullable, for the analyses that recorded it before then.
    assert "search_score" not in recorded


def test_the_full_result_is_kept_alongside_the_scalars(db_session):
    """The analysis shape grows — title analysis, coverage and repetition all arrived later —
    so a historical row must stay readable on its own terms."""
    draft = _make_draft(db_session)
    _record(db_session, draft["id"])
    detail = draft_service.get_draft(db_session, user_id=USER, draft_id=draft["id"])

    assert detail["latest"]["result"]["title_analysis"]["characters"] == 42


def test_recording_against_a_draft_that_is_not_yours_returns_nothing(db_session):
    draft = _make_draft(db_session)

    assert draft_service.record_analysis(
        db_session, user_id=OTHER_USER, draft_id=draft["id"], result={}
    ) is None
    assert db_session.query(SeoDraftAnalysis).count() == 0


def test_a_draft_is_bounded(db_session):
    draft = draft_service.create_draft(
        db_session, user_id=USER, name="Long", content="x" * (draft_service.MAX_DRAFT_CHARS + 500)
    )
    stored = db_session.query(SeoDraft).filter(SeoDraft.id == draft["id"]).first()

    assert len(stored.content) == draft_service.MAX_DRAFT_CHARS
