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
