"""Rebuilding strategies must replace the current set, not stack another generation on it.

`build_strategies` upserts by name and previously deleted nothing, so every rebuild left the
previous run's rows in place. After the corpus-aware theme fix on 2026-09-07 the live table
held **five** momentum plays — three derived from the pre-fix themes (`chatgpt`, `case`,
`series`) plus two from the corrected ones — listed side by side as though all five were
current advice.

**Why deleting is safe for these rows specifically.** `strategies` is shared with the
flow-engine strategy-learning path (`apps/rippletrace/flow_strategy.py`), which selects on
`intent_type` and increments `success_count` / `failure_count` on what it picks. Those rows
carry real accumulated learning and must never be touched here.

RippleTrace's momentum plays carry none. They are pure derivations of drop points and pings,
recomputed in full on every run, and `flow_strategy` can never select one because it filters
`intent_type == <a concrete value>` while theirs is NULL. `usage_count` on a momentum play is
a rebuild counter, not learning.

So `intent_type IS NULL` is the discriminator, and the tests below pin both halves: our stale
rows go, and flow-engine rows survive untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from apps.rippletrace.drop import DropPointDB
from apps.rippletrace.services import strategy_engine
from apps.rippletrace.strategy import StrategyDB

pytestmark = pytest.mark.app_profile

USER_ID = uuid.uuid4()
_BASE_DATE = datetime(2026, 1, 1)


def _drop(db, *, index: int, themes: str) -> DropPointDB:
    """A published drop that cleared SUCCESS_NARRATIVE_THRESHOLD."""
    row = DropPointDB(
        id=f"dp-{uuid.uuid4()}",
        title=f"Piece {index}",
        platform="Substack",
        url=f"https://example.com/{index}",
        date_dropped=_BASE_DATE + timedelta(days=index * 20),
        core_themes=themes,
        intent="published",
        user_id=USER_ID,
        narrative_score=strategy_engine.SUCCESS_NARRATIVE_THRESHOLD + 10.0,
    )
    db.add(row)
    return row


def _seed_successful_drops(db, themes: list[str]) -> None:
    """MIN_SUCCESSFUL_DROPS worth of published work carrying the given themes."""
    assert len(themes) >= strategy_engine.MIN_SUCCESSFUL_DROPS
    for index, theme in enumerate(themes):
        _drop(db, index=index, themes=theme)
    db.commit()


def _momentum_play(db, name: str) -> StrategyDB:
    """A stale RippleTrace strategy: pattern_description set, intent_type NULL."""
    row = StrategyDB(
        id=str(uuid.uuid4()),
        name=name,
        pattern_description="a play built from themes that no longer rank",
        conditions="{}",
        success_rate=0.5,
        usage_count=3,
    )
    db.add(row)
    db.commit()
    return row


def _flow_strategy(db, *, intent_type: str = "content_publish") -> StrategyDB:
    """A flow-engine strategy: intent_type set, real learning counters."""
    row = StrategyDB(
        id=str(uuid.uuid4()),
        name="Flow Learned Strategy",
        intent_type=intent_type,
        flow={"steps": ["a", "b"]},
        score=2.5,
        success_count=11,
        failure_count=2,
        usage_count=13,
    )
    db.add(row)
    db.commit()
    return row


def _names(db) -> set[str]:
    db.expire_all()  # re-read rather than trusting the identity map
    return {row.name for row in db.query(StrategyDB).all()}


# ── the defect ─────────────────────────────────────────────────────────────────────────

def test_a_play_whose_theme_stopped_ranking_is_retired(db_session):
    _seed_successful_drops(db_session, ["ethics", "accountability", "proving"])
    _momentum_play(db_session, "Chatgpt Momentum Play")

    strategy_engine.build_strategies(db_session)

    assert "Chatgpt Momentum Play" not in _names(db_session)


def test_the_table_holds_exactly_one_generation_after_a_rebuild(db_session):
    """The live symptom: five rows, three of them from a superseded theme set."""
    _seed_successful_drops(db_session, ["ethics", "accountability", "proving"])
    for stale in ("Chatgpt Momentum Play", "Case Momentum Play", "Series Momentum Play"):
        _momentum_play(db_session, stale)

    created = strategy_engine.build_strategies(db_session)

    assert created, "fixture produced no strategies"
    assert _names(db_session) == {item["name"] for item in created}


def test_the_retirement_is_committed(db_session):
    """The deletes were originally written after `db.commit()` and would never have landed."""
    _seed_successful_drops(db_session, ["ethics", "accountability", "proving"])
    _momentum_play(db_session, "Chatgpt Momentum Play")

    strategy_engine.build_strategies(db_session)
    db_session.rollback()  # discard anything still uncommitted in this session

    survivors = (
        db_session.query(StrategyDB).filter(StrategyDB.name == "Chatgpt Momentum Play").all()
    )
    assert survivors == []


# ── the rows that must survive ─────────────────────────────────────────────────────────

def test_flow_engine_strategies_are_never_touched(db_session):
    """They carry real learning: flow_strategy increments success/failure on what it picks."""
    _seed_successful_drops(db_session, ["ethics", "accountability", "proving"])
    flow = _flow_strategy(db_session)
    flow_id = flow.id

    strategy_engine.build_strategies(db_session)
    db_session.expire_all()

    survivor = db_session.query(StrategyDB).filter(StrategyDB.id == flow_id).first()
    assert survivor is not None, "a flow-engine strategy was retired as if it were ours"
    assert (survivor.success_count, survivor.failure_count) == (11, 2)


def test_a_play_that_still_ranks_is_updated_not_recreated(db_session):
    """Retirement must not become delete-and-recreate, which would reset usage_count."""
    _seed_successful_drops(db_session, ["ethics", "ethics", "ethics"])
    created = strategy_engine.build_strategies(db_session)
    names = {item["name"] for item in created}
    assert names, "fixture produced no strategies"

    def _usage() -> dict[str, int]:
        db_session.expire_all()
        return {
            row.name: row.usage_count
            for row in db_session.query(StrategyDB).filter(StrategyDB.name.in_(names)).all()
        }

    before = _usage()
    strategy_engine.build_strategies(db_session)
    after = _usage()

    assert after == {name: count + 1 for name, count in before.items()}


def test_nothing_is_retired_when_the_corpus_cannot_build_strategies(db_session):
    """Below MIN_SUCCESSFUL_DROPS `build_strategies` returns early.

    It must not read "no strategies were built" as "nothing ranks any more" and empty the
    table — a quiet week would otherwise delete everything the system had learned to say.
    """
    _momentum_play(db_session, "Chatgpt Momentum Play")

    assert strategy_engine.build_strategies(db_session) == []

    assert "Chatgpt Momentum Play" in _names(db_session)
