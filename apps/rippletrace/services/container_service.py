"""Detecting container candidates, and acting only on the ones a person confirmed.

`TITLE_AS_CONTAINER_SPEC` §4 and §8 question 1, answered by the owner 2026-09-07:
**confirmed, not inferred.**

The corpus can measure which words recur across a catalogue. It cannot tell you that
"2025 ChatGPT Case Study Series" is *a work someone made* rather than four words that happen to
co-occur — and `influence_graph`, `causal_engine` and `strategy_engine` all reason from
`tagged_entities` as though it were a fact about the author's body of work. So detection
proposes and a person decides.

★ **Detection reconstructs a name, not a term set.** `_discounted_terms()` (the corpus-aware
theme fix, #306) returns `{chatgpt, case, study, series}` — enough to know something is there,
useless as a question to ask a human. "Is `{chatgpt, case, series, study}` a series of yours?"
is not answerable; "Is *2025 ChatGPT Case Study Series* a series of yours?" is. So candidates
are the longest token sequences that actually recur across titles, rendered with the casing the
author used.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.rippletrace.container import (
    CONTAINER_CONFIRMED,
    CONTAINER_DISMISSED,
    ContainerDB,
)
from apps.rippletrace.drop import DropPointDB

logger = logging.getLogger(__name__)

# A container has to recur to be one. Both floors must clear: a share alone would propose a
# two-word phrase from a two-drop corpus, and a count alone would propose a phrase from 6 titles
# out of 4,000, which is a coincidence rather than a series.
MIN_CONTAINER_DROPS = 4
MIN_CONTAINER_SHARE = 0.10

# Long enough to be a name rather than a phrase; bounded because scanning every n-gram width
# over a large catalogue is the expensive part.
MIN_CONTAINER_WORDS = 2
MAX_CONTAINER_WORDS = 10

MAX_CANDIDATES = 5

_WORD = re.compile(r"[\w']+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _normalize(name: str) -> str:
    return " ".join(_tokens(name))


def _original_case(title: str, phrase_tokens: list[str]) -> str:
    """Render a detected phrase the way the author wrote it.

    The name is an identity, and "2025 chatgpt case study series" is not what anybody called
    their series. Falls back to the lowercased form if the span cannot be located, which only
    happens when the title's punctuation splits differently from the token stream.
    """
    words = _WORD.findall(title or "")
    lowered = [w.lower() for w in words]
    width = len(phrase_tokens)
    for index in range(len(lowered) - width + 1):
        if lowered[index:index + width] == phrase_tokens:
            return " ".join(words[index:index + width])
    return " ".join(phrase_tokens)


def _decided(db: Session, uid) -> dict[str, ContainerDB]:
    rows = db.query(ContainerDB).filter(ContainerDB.user_id == uid).all()
    return {row.normalized: row for row in rows}


def detect_candidates(db: Session, user_id: Any, *, limit: int = MAX_CANDIDATES) -> list[dict]:
    """Phrases recurring across enough of this author's titles to be worth asking about.

    Longest first, and a shorter phrase wholly inside a longer one is dropped: "ChatGPT Case
    Study" and "Case Study Series" are both real n-grams of "2025 ChatGPT Case Study Series",
    and offering all three as separate candidates asks the same question three times.
    """
    uid = parse_user_id(user_id)
    if uid is None:
        return []

    rows = (
        db.query(DropPointDB)
        .filter(DropPointDB.user_id == uid, DropPointDB.title.isnot(None))
        .all()
    )
    titles = [row.title for row in rows if (row.title or "").strip()]
    corpus_size = len(titles)
    if corpus_size < MIN_CONTAINER_DROPS:
        return []

    floor = max(MIN_CONTAINER_DROPS, int(corpus_size * MIN_CONTAINER_SHARE))
    tokenized = [_tokens(title) for title in titles]

    # Document frequency per phrase: how many TITLES contain it, not how many times it occurs.
    # A phrase repeated three times in one title is a tic; a phrase in three titles is a series.
    found: list[tuple[tuple[str, ...], int]] = []
    for width in range(MAX_CONTAINER_WORDS, MIN_CONTAINER_WORDS - 1, -1):
        seen: dict[tuple[str, ...], int] = {}
        for tokens in tokenized:
            for phrase in {
                tuple(tokens[i:i + width]) for i in range(len(tokens) - width + 1)
            }:
                seen[phrase] = seen.get(phrase, 0) + 1
        for phrase, count in seen.items():
            if count < floor:
                continue
            if any(_contains(longer, phrase) for longer, _ in found):
                continue
            found.append((phrase, count))

    decided = _decided(db, uid)
    candidates: list[dict] = []
    for phrase, count in found:
        normalized = " ".join(phrase)
        if normalized in decided:
            # Confirmed or dismissed — either way it is an answered question.
            continue
        example_titles = [t for t, toks in zip(titles, tokenized) if _contains(tuple(toks), phrase)]
        candidates.append({
            "name": _original_case(example_titles[0], list(phrase)) if example_titles else normalized,
            "normalized": normalized,
            "drop_count": count,
            "corpus_size": corpus_size,
            "share": round(count / corpus_size * 100, 1),
            # The evidence, so the question is answerable. "Is this a series of yours?" needs
            # the titles it was drawn from far more than it needs a percentage.
            "examples": example_titles[:3],
        })

    candidates.sort(key=lambda item: (-item["drop_count"], -len(item["normalized"])))
    return candidates[:max(1, limit)]


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    width = len(needle)
    return any(haystack[i:i + width] == needle for i in range(len(haystack) - width + 1))


# ── acting on a decision ──────────────────────────────────────────────────────────────

def _serialize(row: ContainerDB, *, drop_count: int | None = None) -> dict:
    payload = {
        "id": row.id,
        "name": row.name,
        "normalized": row.normalized,
        "status": row.status,
        "drop_count_at_decision": row.drop_count_at_decision,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if drop_count is not None:
        payload["drop_count"] = drop_count
    return payload


def confirm_container(
    db: Session, user_id: Any, *, name: str, note: str | None = None
) -> dict | None:
    """Record the decision, then tag every drop whose title carries the container.

    Tagging happens on confirmation rather than at read time so the three engines that read
    `tagged_entities` see it without knowing this feature exists.
    """
    uid = parse_user_id(user_id)
    if uid is None:
        return None
    normalized = _normalize(name)
    if not normalized:
        return None

    row = (
        db.query(ContainerDB)
        .filter(ContainerDB.user_id == uid, ContainerDB.normalized == normalized)
        .first()
    )
    tagged = apply_container(db, uid, normalized=normalized, name=name.strip())
    if row is None:
        row = ContainerDB(
            user_id=uid,
            name=name.strip()[:300],
            normalized=normalized[:300],
            status=CONTAINER_CONFIRMED,
            drop_count_at_decision=tagged,
            note=note,
        )
        db.add(row)
    else:
        # A dismissed container being confirmed is a change of mind, not a new thing.
        row.status = CONTAINER_CONFIRMED
        row.name = name.strip()[:300]
        row.drop_count_at_decision = tagged
        if note is not None:
            row.note = note
    db.commit()
    db.refresh(row)
    return _serialize(row, drop_count=tagged)


def dismiss_container(db: Session, user_id: Any, *, name: str) -> dict | None:
    """Record that this is not a container.

    Stored rather than simply ignored: without it the system re-proposes a rejected candidate
    every time anyone looks, which turns an answered question into a nag.
    """
    uid = parse_user_id(user_id)
    if uid is None:
        return None
    normalized = _normalize(name)
    if not normalized:
        return None

    row = (
        db.query(ContainerDB)
        .filter(ContainerDB.user_id == uid, ContainerDB.normalized == normalized)
        .first()
    )
    if row is None:
        row = ContainerDB(
            user_id=uid,
            name=name.strip()[:300],
            normalized=normalized[:300],
            status=CONTAINER_DISMISSED,
        )
        db.add(row)
    else:
        row.status = CONTAINER_DISMISSED
        # The entity stays on drops already tagged. Removing it would silently rewrite history
        # the engines have already reasoned over; a dismissal says "stop proposing this", not
        # "pretend it was never true".
    db.commit()
    db.refresh(row)
    return _serialize(row)


def apply_container(db: Session, uid, *, normalized: str, name: str) -> int:
    """Add the container to `tagged_entities` on every drop whose title carries it.

    Additive and idempotent: a drop can belong to more than one container, and re-confirming
    must not duplicate the entry.
    """
    phrase = tuple(normalized.split())
    if not phrase:
        return 0

    rows = (
        db.query(DropPointDB)
        .filter(DropPointDB.user_id == uid, DropPointDB.title.isnot(None))
        .all()
    )
    tagged = 0
    for row in rows:
        if not _contains(tuple(_tokens(row.title)), phrase):
            continue
        existing = [e.strip() for e in (row.tagged_entities or "").split(",") if e.strip()]
        if any(_normalize(entry) == normalized for entry in existing):
            tagged += 1
            continue
        row.tagged_entities = ",".join(existing + [name])
        tagged += 1
    db.commit()
    return tagged


def list_containers(db: Session, user_id: Any) -> list[dict]:
    uid = parse_user_id(user_id)
    if uid is None:
        return []
    rows = (
        db.query(ContainerDB)
        .filter(ContainerDB.user_id == uid)
        .order_by(ContainerDB.created_at.desc())
        .all()
    )
    return [_serialize(row) for row in rows]


def tag_drop_with_confirmed_containers(db: Session, row: DropPointDB) -> list[str]:
    """Apply already-confirmed containers to one newly-ingested drop.

    ★ No new confirmation is asked for. The container was confirmed as an identity, and a new
    piece that carries its name belongs to it — asking again per article would make the answer
    a chore rather than a decision. A container that has never been confirmed still tags
    nothing, which is the whole point.
    """
    if row.user_id is None or not (row.title or "").strip():
        return []
    confirmed = (
        db.query(ContainerDB)
        .filter(
            ContainerDB.user_id == row.user_id,
            ContainerDB.status == CONTAINER_CONFIRMED,
        )
        .all()
    )
    if not confirmed:
        return []

    title_tokens = tuple(_tokens(row.title))
    existing = [e.strip() for e in (row.tagged_entities or "").split(",") if e.strip()]
    normalized_existing = {_normalize(entry) for entry in existing}
    added: list[str] = []
    for container in confirmed:
        phrase = tuple(container.normalized.split())
        if not phrase or container.normalized in normalized_existing:
            continue
        if _contains(title_tokens, phrase):
            existing.append(container.name)
            normalized_existing.add(container.normalized)
            added.append(container.name)
    if added:
        row.tagged_entities = ",".join(existing)
    return added


# ── performance: aggregation over the tag, not a second record ────────────────────────
#
# ★ Owner's call, 2026-09-07: aggregate now, decide ownership later. Every performance
# question about a series is already answerable from the drops that carry its tag — measured
# before deciding, on the live corpus:
#
#     46 drops · avg narrative 32.4 · Feb 2025 → Jun 2025 · 87 pings
#
# So a `Work` record would not buy measurement. What it would buy is INTENT — a target ("52
# planned, 46 done"), a lifecycle ("finished", so a dormant series stops reading as a failing
# one), a purpose. That is the declared-vs-measured split again, and it is a decision to make
# against a real view rather than ahead of one.

# Below this a series has not been running long enough for halves to mean anything: with four
# pieces, "the second half is better" is two data points against two.
MIN_DROPS_FOR_TRAJECTORY = 6


def _container_drops(db: Session, uid, normalized: str) -> list[DropPointDB]:
    """Drops carrying this container, matched on the stored normalized form.

    Matched rather than joined: `tagged_entities` is a comma-joined string, which is what the
    three engines already read, and adding a join table would be a second source of truth for
    membership.
    """
    rows = (
        db.query(DropPointDB)
        .filter(DropPointDB.user_id == uid)
        .order_by(DropPointDB.date_dropped.asc())
        .all()
    )
    return [
        row
        for row in rows
        if any(
            _normalize(entry) == normalized
            for entry in (row.tagged_entities or "").split(",")
            if entry.strip()
        )
    ]


def _ping_counts(db: Session, drop_ids: list[str]) -> dict[str, int]:
    from sqlalchemy import func

    from apps.rippletrace.drop import PingDB

    if not drop_ids:
        return {}
    rows = (
        db.query(PingDB.drop_point_id, func.count(PingDB.id))
        .filter(PingDB.drop_point_id.in_(drop_ids))
        .group_by(PingDB.drop_point_id)
        .all()
    )
    return {drop_id: count for drop_id, count in rows}


def container_performance(db: Session, uid, container: ContainerDB, *, members: bool = False) -> dict:
    """What this body of work has actually done.

    Computed, never stored. A stored summary is a second copy of numbers that move every time a
    ping lands, and it would be wrong more often than it was right.
    """
    drops = _container_drops(db, uid, container.normalized)
    pings = _ping_counts(db, [d.id for d in drops])
    scores = [d.narrative_score or 0.0 for d in drops]
    dates = [d.date_dropped for d in drops if d.date_dropped]

    payload = _serialize(container, drop_count=len(drops))
    payload["performance"] = {
        "drops": len(drops),
        "pings": sum(pings.values()),
        "avg_narrative": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "first_published": dates[0].isoformat() if dates else None,
        "last_published": dates[-1].isoformat() if dates else None,
        "span_days": (dates[-1] - dates[0]).days if len(dates) > 1 else 0,
        "platforms": sorted({d.platform for d in drops if d.platform}),
        "cadence_days": round((dates[-1] - dates[0]).days / (len(dates) - 1), 1)
        if len(dates) > 1
        else None,
        "trajectory": _trajectory(drops),
    }
    if members:
        # Best-travelled first: "which pieces worked" is the question a writer actually has
        # about a series, and date order buries the answer.
        payload["pieces"] = sorted(
            (
                {
                    "id": d.id,
                    "title": d.title,
                    "url": d.url,
                    "platform": d.platform,
                    "published": d.date_dropped.isoformat() if d.date_dropped else None,
                    "narrative_score": round(d.narrative_score or 0.0, 1),
                    "pings": pings.get(d.id, 0),
                }
                for d in drops
            ),
            key=lambda item: (-item["pings"], -item["narrative_score"]),
        )
    return payload


def _trajectory(drops: list[DropPointDB]) -> dict:
    """Is the series getting more or less traction over time?

    ★ Reported as unavailable rather than as 0 when there is not enough of it. An average
    across a whole series answers "was it good"; the halves answer "is it working", which is
    the question that changes what you do next — but only once there are enough pieces for a
    half to be more than a couple of data points.
    """
    dated = [d for d in drops if d.date_dropped]
    if len(dated) < MIN_DROPS_FOR_TRAJECTORY:
        return {
            "available": False,
            "reason": f"needs at least {MIN_DROPS_FOR_TRAJECTORY} dated pieces",
        }

    midpoint = len(dated) // 2
    early = [d.narrative_score or 0.0 for d in dated[:midpoint]]
    late = [d.narrative_score or 0.0 for d in dated[midpoint:]]
    early_avg = sum(early) / len(early)
    late_avg = sum(late) / len(late)
    return {
        "available": True,
        "early_avg": round(early_avg, 1),
        "late_avg": round(late_avg, 1),
        "change": round(late_avg - early_avg, 1),
        # Both halves are shown, not just the delta: "+4.2" says nothing about whether the
        # series started at 3 or at 40.
        "early_count": len(early),
        "late_count": len(late),
    }


def list_container_performance(db: Session, user_id: Any) -> list[dict]:
    """Every confirmed container, with what it has done. Dismissed ones are not works."""
    uid = parse_user_id(user_id)
    if uid is None:
        return []
    rows = (
        db.query(ContainerDB)
        .filter(ContainerDB.user_id == uid, ContainerDB.status == CONTAINER_CONFIRMED)
        .order_by(ContainerDB.created_at.desc())
        .all()
    )
    return [container_performance(db, uid, row) for row in rows]


def get_container_detail(db: Session, user_id: Any, container_id: str) -> dict | None:
    uid = parse_user_id(user_id)
    if uid is None:
        return None
    row = (
        db.query(ContainerDB)
        .filter(ContainerDB.id == str(container_id), ContainerDB.user_id == uid)
        .first()
    )
    if row is None:
        return None
    return container_performance(db, uid, row, members=True)
