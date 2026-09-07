"""A container is confirmed, never inferred.

`TITLE_AS_CONTAINER_SPEC` §4, and §8 question 1 answered by the owner 2026-09-07:
**"confirmed not inferred."**

`drop_points.tagged_entities` has existed since RippleTrace was built and three engines read it
— `influence_graph` links drops by shared entity, `causal_engine` feeds them into causal
reasons, and `strategy_engine` builds `{entity} Influence Spike` strategies from them. It held
**one row out of 215**, so that last path had never once fired. The missing input was not a
table; it was a classification nobody had made.

★ The corpus can measure that four words recur across a catalogue. It cannot tell you that
"2025 ChatGPT Case Study Series" is *a work someone made* — and three engines will treat
whatever lands in `tagged_entities` as a fact about the author's body of work. So most of what
follows asserts that detection **proposes** and never writes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.rippletrace.container import ContainerDB
from apps.rippletrace.drop import DropPointDB
from apps.rippletrace.services import container_service

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
OTHER = uuid.uuid4()

SERIES = "2025 ChatGPT Case Study Series"
SUBJECTS = [
    "Ethics and Accountability", "Prompt Engineering", "Educational Psychology",
    "Proving Speed Wins", "Business in the Future", "The Missing Layer",
]


def _drop(db, title, *, user_id=USER, entities=""):
    row = DropPointDB(
        id=f"dp-{uuid.uuid4()}",
        title=title,
        platform="Substack",
        url=f"https://example.com/{uuid.uuid4()}",
        date_dropped=datetime(2026, 1, 1),
        core_themes="",
        tagged_entities=entities,
        intent="published",
        user_id=user_id,
    )
    db.add(row)
    return row


def _seed_series(db, count=6, prefix=SERIES):
    for subject in SUBJECTS[:count]:
        _drop(db, f"{prefix}: {subject}")
    db.commit()


def _entities(db, user_id=USER):
    return {
        row.title: [e for e in (row.tagged_entities or "").split(",") if e]
        for row in db.query(DropPointDB).filter(DropPointDB.user_id == user_id).all()
    }


# ── detection proposes a NAME, not a term set ─────────────────────────────────────────

def test_the_series_is_detected_from_the_titles(db_session):
    _seed_series(db_session)
    candidates = container_service.detect_candidates(db_session, USER)

    assert candidates
    assert candidates[0]["normalized"] == "2025 chatgpt case study series"


def test_the_candidate_is_named_the_way_the_author_wrote_it(db_session):
    """★ A name is an identity, and "2025 chatgpt case study series" is not what anyone
    called their series.

    This is also what makes the question answerable: "is `{chatgpt, case, series, study}` a
    series of yours?" cannot be answered by a person; the reconstructed name can.
    """
    _seed_series(db_session)
    candidates = container_service.detect_candidates(db_session, USER)

    assert candidates[0]["name"] == SERIES


def test_a_candidate_carries_the_evidence_it_was_drawn_from(db_session):
    """"Is this a series of yours?" needs the titles far more than it needs a percentage."""
    _seed_series(db_session)
    candidate = container_service.detect_candidates(db_session, USER)[0]

    assert candidate["drop_count"] == 6
    assert candidate["corpus_size"] == 6
    assert len(candidate["examples"]) == 3
    assert all(SERIES in title for title in candidate["examples"])


def test_shorter_phrases_inside_a_longer_one_are_not_offered_separately(db_session):
    """"ChatGPT Case Study" and "Case Study Series" are both real n-grams of the same name.

    Offering all three asks the same question three times.
    """
    _seed_series(db_session)
    names = {c["normalized"] for c in container_service.detect_candidates(db_session, USER)}

    assert "chatgpt case study" not in names
    assert "case study series" not in names


def test_a_corpus_with_no_repeated_structure_yields_nothing(db_session):
    """★ The keyword-style author, handled by the same rule for free.

    Someone whose titles are what they were ranking for has no container, and that is the
    correct answer rather than a failure. The corpus decides, not a setting.
    """
    for title in ("How to Fix Slow Postgres Queries", "A Note on Rust Lifetimes",
                  "Why Latency Budgets Slip", "Reading a Flame Graph", "Sharding Without Tears"):
        _drop(db_session, title)
    db_session.commit()

    assert container_service.detect_candidates(db_session, USER) == []


def test_a_phrase_in_too_few_titles_is_not_a_series(db_session):
    _seed_series(db_session, count=2)
    for title in ("Unrelated One", "Unrelated Two", "Unrelated Three", "Unrelated Four",
                  "Unrelated Five", "Unrelated Six", "Unrelated Seven", "Unrelated Eight"):
        _drop(db_session, title)
    db_session.commit()

    names = {c["normalized"] for c in container_service.detect_candidates(db_session, USER)}
    assert "2025 chatgpt case study series" not in names


def test_detection_sees_only_your_own_drops(db_session):
    _seed_series(db_session)
    assert container_service.detect_candidates(db_session, OTHER) == []


# ── ★ detection never writes ──────────────────────────────────────────────────────────

def test_detecting_a_candidate_tags_nothing(db_session):
    """★ The load-bearing test.

    Three engines treat `tagged_entities` as a fact about the author's body of work. Detection
    is a measurement of recurring words; only a person can say it is a work they made.
    """
    _seed_series(db_session)
    container_service.detect_candidates(db_session, USER)

    assert all(not tags for tags in _entities(db_session).values())
    assert db_session.query(ContainerDB).count() == 0


def test_detection_creates_no_record(db_session):
    """An unanswered question is just a measurement of the current corpus.

    Storing candidates would let the list drift out of step with the drops it came from.
    """
    _seed_series(db_session)
    container_service.detect_candidates(db_session, USER)

    assert db_session.query(ContainerDB).count() == 0


# ── confirming ────────────────────────────────────────────────────────────────────────

def test_confirming_tags_every_drop_that_carries_the_name(db_session):
    _seed_series(db_session)
    result = container_service.confirm_container(db_session, USER, name=SERIES)

    assert result["drop_count"] == 6
    assert all(tags == [SERIES] for tags in _entities(db_session).values())


def test_confirming_leaves_drops_that_do_not_carry_it_alone(db_session):
    _seed_series(db_session)
    _drop(db_session, "A Standalone Essay")
    db_session.commit()
    container_service.confirm_container(db_session, USER, name=SERIES)

    assert _entities(db_session)["A Standalone Essay"] == []


def test_confirming_is_additive_a_drop_can_belong_to_two_containers(db_session):
    _seed_series(db_session)
    container_service.confirm_container(db_session, USER, name=SERIES)
    container_service.confirm_container(db_session, USER, name="Case Study")

    tags = _entities(db_session)[f"{SERIES}: Ethics and Accountability"]
    assert SERIES in tags and "Case Study" in tags


def test_confirming_twice_does_not_duplicate_the_entry(db_session):
    _seed_series(db_session)
    container_service.confirm_container(db_session, USER, name=SERIES)
    container_service.confirm_container(db_session, USER, name=SERIES)

    assert _entities(db_session)[f"{SERIES}: Prompt Engineering"] == [SERIES]
    assert db_session.query(ContainerDB).count() == 1


def test_an_existing_publisher_tag_is_preserved(db_session):
    """Publisher tags are labels the author typed; a container must not overwrite them."""
    _drop(db_session, f"{SERIES}: Ethics and Accountability", entities="chatgpt")
    for subject in SUBJECTS[1:]:
        _drop(db_session, f"{SERIES}: {subject}")
    db_session.commit()
    container_service.confirm_container(db_session, USER, name=SERIES)

    tags = _entities(db_session)[f"{SERIES}: Ethics and Accountability"]
    assert tags == ["chatgpt", SERIES]


# ── dismissing ────────────────────────────────────────────────────────────────────────

def test_a_dismissed_candidate_stops_being_proposed(db_session):
    """★ Without this the system re-proposes a rejected candidate every time anyone looks,
    which turns an answered question into a nag."""
    _seed_series(db_session)
    container_service.dismiss_container(db_session, USER, name=SERIES)

    names = {c["normalized"] for c in container_service.detect_candidates(db_session, USER)}
    assert "2025 chatgpt case study series" not in names


def test_a_confirmed_container_stops_being_proposed_too(db_session):
    _seed_series(db_session)
    container_service.confirm_container(db_session, USER, name=SERIES)

    names = {c["normalized"] for c in container_service.detect_candidates(db_session, USER)}
    assert "2025 chatgpt case study series" not in names


def test_dismissing_tags_nothing(db_session):
    _seed_series(db_session)
    container_service.dismiss_container(db_session, USER, name=SERIES)

    assert all(not tags for tags in _entities(db_session).values())


def test_dismissing_after_confirming_leaves_existing_tags_in_place(db_session):
    """★ A dismissal says "stop asking", not "pretend it was never true".

    Silently rewriting history the engines have already reasoned over is the failure this
    whole feature exists to avoid.
    """
    _seed_series(db_session)
    container_service.confirm_container(db_session, USER, name=SERIES)
    container_service.dismiss_container(db_session, USER, name=SERIES)

    assert all(tags == [SERIES] for tags in _entities(db_session).values())


def test_confirming_after_dismissing_is_a_change_of_mind_not_a_new_thing(db_session):
    _seed_series(db_session)
    container_service.dismiss_container(db_session, USER, name=SERIES)
    container_service.confirm_container(db_session, USER, name=SERIES)

    rows = db_session.query(ContainerDB).filter(ContainerDB.user_id == USER).all()
    assert len(rows) == 1
    assert rows[0].status == "confirmed"


def test_a_nameless_decision_is_refused(db_session):
    assert container_service.confirm_container(db_session, USER, name="   ") is None
    assert container_service.dismiss_container(db_session, USER, name="") is None
    assert db_session.query(ContainerDB).count() == 0


# ── new drops join a container already confirmed ──────────────────────────────────────

def test_a_new_drop_joins_a_confirmed_container_without_being_asked_again(db_session):
    """★ The identity was decided once. Asking per article makes the answer a chore."""
    _seed_series(db_session)
    container_service.confirm_container(db_session, USER, name=SERIES)

    fresh = _drop(db_session, f"{SERIES}: A Brand New Piece")
    db_session.commit()
    added = container_service.tag_drop_with_confirmed_containers(db_session, fresh)
    db_session.commit()

    assert added == [SERIES]
    assert _entities(db_session)[f"{SERIES}: A Brand New Piece"] == [SERIES]


def test_a_new_drop_joins_nothing_when_no_container_was_confirmed(db_session):
    """The whole point: an unconfirmed container tags nothing, ever."""
    _seed_series(db_session)
    fresh = _drop(db_session, f"{SERIES}: A Brand New Piece")
    db_session.commit()

    assert container_service.tag_drop_with_confirmed_containers(db_session, fresh) == []


def test_a_dismissed_container_never_tags_a_new_drop(db_session):
    _seed_series(db_session)
    container_service.dismiss_container(db_session, USER, name=SERIES)
    fresh = _drop(db_session, f"{SERIES}: A Brand New Piece")
    db_session.commit()

    assert container_service.tag_drop_with_confirmed_containers(db_session, fresh) == []


def test_another_persons_container_does_not_tag_your_drop(db_session):
    _seed_series(db_session)
    container_service.confirm_container(db_session, USER, name=SERIES)
    theirs = _drop(db_session, f"{SERIES}: Their Piece", user_id=OTHER)
    db_session.commit()

    assert container_service.tag_drop_with_confirmed_containers(db_session, theirs) == []


def test_an_unowned_drop_is_left_alone(db_session):
    """`log_ripple_event` creates system drops with user_id=None; they belong to nobody."""
    _seed_series(db_session)
    container_service.confirm_container(db_session, USER, name=SERIES)
    orphan = _drop(db_session, f"{SERIES}: System Event", user_id=None)
    db_session.commit()

    assert container_service.tag_drop_with_confirmed_containers(db_session, orphan) == []


# ── what the engines then see ─────────────────────────────────────────────────────────

def test_the_entity_reaches_the_strategy_engine(db_session):
    """★ `{entity} Influence Spike` had never once fired, because entity_counter was empty.

    This is the point of the feature: the classification unblocks code that was already
    written and wired.
    """
    from apps.rippletrace.services import strategy_engine

    for subject in SUBJECTS[:4]:
        row = _drop(db_session, f"{SERIES}: {subject}")
        row.narrative_score = strategy_engine.SUCCESS_NARRATIVE_THRESHOLD + 10
    db_session.commit()
    container_service.confirm_container(db_session, USER, name=SERIES)

    created = strategy_engine.build_strategies(db_session)

    assert any("Influence Spike" in item["name"] for item in created), [
        item["name"] for item in created
    ]
