"""The draft loop: analyse, edit, re-analyse, and see what moved.

`SEO_EDITING_AID_SPEC` §4. Everything the SEO tool does is a measurement; until a draft exists
as a unit, each measurement was taken once and forgotten. You could learn that a phrase repeats
and a target is thin, act on both, re-run — and the tool had no memory that the first reading
happened.

★ **Retention is proposed, never enforced.** Owner's call, 2026-09-07: *"every analysis with a
prune/deletion every so often prompted by the system."* Same shape as masterplan phase advance
and worth declaration — the system notices and offers, a person decides.

That is not politeness. A silent cap would delete the *earliest* analyses, which are the ones a
before/after comparison is measured against, and it would do it precisely when the history first
became long enough to be interesting. The unbounded-growth risk is real (`HEALTH-EVENT-VOLUME-1`,
3.6 GB of health events); the answer is a prompt, not a cap.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.search.models.seo_draft import SeoDraft, SeoDraftAnalysis

logger = logging.getLogger(__name__)

MAX_DRAFT_NAME = 200
MAX_DRAFT_CHARS = 400_000     # roughly 60k words; a bound, not a working limit

# How many analyses a draft may accumulate before the system raises the subject. High enough
# that a normal editing session never sees the prompt, low enough that a year of use does.
PRUNE_PROMPT_AFTER = 25

# What a proposal offers to keep: the baseline (always) plus the most recent this many. The
# middle of a long history is the part that is genuinely redundant — consecutive readings of a
# draft being edited differ by very little, and the arc is legible from its ends.
PRUNE_KEEP_RECENT = 10


def _serialize_draft(draft: SeoDraft, *, analysis_count: int | None = None) -> dict[str, Any]:
    payload = {
        "id": draft.id,
        "name": draft.name,
        "title": draft.title or "",
        "target_keywords": list(draft.target_keywords or []),
        "published_url": draft.published_url,
        "content": draft.content or "",
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }
    if analysis_count is not None:
        payload["analysis_count"] = analysis_count
    return payload


def _serialize_analysis(row: SeoDraftAnalysis, *, include_result: bool = False) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "word_count": row.word_count,
        "readability": row.readability,
        "search_score": row.search_score,
        "title_characters": row.title_characters,
        "is_baseline": bool(row.is_baseline),
    }
    if include_result:
        payload["result"] = row.result
    return payload


def create_draft(
    db: Session,
    *,
    user_id: Any,
    name: str,
    content: str = "",
    title: str | None = None,
    target_keywords: list[str] | None = None,
) -> dict[str, Any]:
    uid = parse_user_id(user_id)
    if uid is None:
        raise ValueError("a valid user_id is required")
    cleaned_name = " ".join((name or "").split())[:MAX_DRAFT_NAME]
    if not cleaned_name:
        # Named by the writer, not by a timestamp: a list of "Analysis 2026-09-07 14:32" is the
        # pile of dated scorecards this model exists to replace.
        raise ValueError("a draft needs a name")

    draft = SeoDraft(
        id=str(uuid.uuid4()),
        user_id=uid,
        name=cleaned_name,
        content=(content or "")[:MAX_DRAFT_CHARS],
        title=(title or None),
        target_keywords=list(target_keywords or []) or None,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft, analysis_count=0)


def list_drafts(db: Session, *, user_id: Any, limit: int = 50) -> list[dict[str, Any]]:
    uid = parse_user_id(user_id)
    if uid is None:
        return []
    drafts = (
        db.query(SeoDraft)
        .filter(SeoDraft.user_id == uid)
        .order_by(SeoDraft.updated_at.desc().nullslast(), SeoDraft.created_at.desc())
        .limit(max(1, min(int(limit or 50), 200)))
        .all()
    )
    if not drafts:
        return []
    counts = _count_by_draft(db, [d.id for d in drafts])
    # Body text is deliberately omitted from a listing: it is the largest field and a picker
    # does not need it.
    return [
        {k: v for k, v in _serialize_draft(d, analysis_count=counts.get(d.id, 0)).items()
         if k != "content"}
        for d in drafts
    ]


def _count_by_draft(db: Session, draft_ids: list[str]) -> dict[str, int]:
    from sqlalchemy import func

    rows = (
        db.query(SeoDraftAnalysis.draft_id, func.count(SeoDraftAnalysis.id))
        .filter(SeoDraftAnalysis.draft_id.in_(draft_ids))
        .group_by(SeoDraftAnalysis.draft_id)
        .all()
    )
    return {draft_id: count for draft_id, count in rows}


def _owned_draft(db: Session, draft_id: str, uid) -> SeoDraft | None:
    return (
        db.query(SeoDraft)
        .filter(SeoDraft.id == str(draft_id), SeoDraft.user_id == uid)
        .first()
    )


def get_draft(db: Session, *, user_id: Any, draft_id: str) -> dict[str, Any] | None:
    """A draft, its analyses newest-first, and the deltas between consecutive readings."""
    uid = parse_user_id(user_id)
    if uid is None:
        return None
    draft = _owned_draft(db, draft_id, uid)
    if draft is None:
        return None

    analyses = (
        db.query(SeoDraftAnalysis)
        .filter(SeoDraftAnalysis.draft_id == draft.id)
        .order_by(SeoDraftAnalysis.created_at.desc())
        .all()
    )
    payload = _serialize_draft(draft, analysis_count=len(analyses))
    payload["analyses"] = [_serialize_analysis(a) for a in analyses]
    if analyses:
        payload["latest"] = _serialize_analysis(analyses[0], include_result=True)
    payload["deltas"] = compute_deltas(analyses)
    payload["retention"] = prune_proposal(analyses)
    return payload


def update_draft(
    db: Session,
    *,
    user_id: Any,
    draft_id: str,
    name: str | None = None,
    content: str | None = None,
    title: str | None = None,
    target_keywords: list[str] | None = None,
    published_url: str | None = None,
) -> dict[str, Any] | None:
    """Update the fields supplied and leave the rest alone.

    `None` means "not supplied" throughout — an explicit empty string still clears a field, so
    a title can be removed, but omitting a key never silently wipes it.
    """
    uid = parse_user_id(user_id)
    if uid is None:
        return None
    draft = _owned_draft(db, draft_id, uid)
    if draft is None:
        return None

    if name is not None:
        cleaned = " ".join(name.split())[:MAX_DRAFT_NAME]
        if cleaned:
            draft.name = cleaned
    if content is not None:
        draft.content = content[:MAX_DRAFT_CHARS]
    if title is not None:
        draft.title = title or None
    if target_keywords is not None:
        draft.target_keywords = list(target_keywords) or None
    if published_url is not None:
        draft.published_url = published_url or None

    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft)


def delete_draft(db: Session, *, user_id: Any, draft_id: str) -> bool:
    uid = parse_user_id(user_id)
    if uid is None:
        return False
    draft = _owned_draft(db, draft_id, uid)
    if draft is None:
        return False
    # Analyses first: they hold the foreign key, and an orphaned analysis is unreachable rather
    # than merely untidy.
    db.query(SeoDraftAnalysis).filter(SeoDraftAnalysis.draft_id == draft.id).delete(
        synchronize_session=False
    )
    db.delete(draft)
    db.commit()
    return True


def record_analysis(
    db: Session, *, user_id: Any, draft_id: str, result: dict[str, Any]
) -> dict[str, Any] | None:
    """Attach one analysis to a draft.

    The first analysis of a draft becomes its baseline. That is not a user-set flag: "before"
    is only meaningful against the earliest reading, so whatever came first is what the
    comparison is measured from.
    """
    uid = parse_user_id(user_id)
    if uid is None:
        return None
    draft = _owned_draft(db, draft_id, uid)
    if draft is None:
        return None

    existing = (
        db.query(SeoDraftAnalysis).filter(SeoDraftAnalysis.draft_id == draft.id).count()
    )
    title_analysis = (result or {}).get("title_analysis") or {}
    row = SeoDraftAnalysis(
        id=str(uuid.uuid4()),
        draft_id=draft.id,
        user_id=uid,
        result=result or {},
        word_count=(result or {}).get("word_count"),
        readability=(result or {}).get("readability"),
        search_score=(result or {}).get("search_score"),
        title_characters=title_analysis.get("characters"),
        is_baseline=existing == 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_analysis(row)


# ── comparison, which is the whole point ──────────────────────────────────────────────

_TRACKED = ("word_count", "readability", "search_score", "title_characters")


def compute_deltas(analyses: list[SeoDraftAnalysis]) -> dict[str, Any]:
    """What moved since the previous reading, and since the first.

    ★ Both, deliberately. "Since last time" is what you act on during a session; "since the
    baseline" is what tells you whether the session went anywhere. A tool that reports only the
    first can show four consecutive improvements that net to nothing.
    """
    if len(analyses) < 2:
        return {"available": False, "reason": "one analysis so far — nothing to compare yet"}

    newest = analyses[0]
    previous = analyses[1]
    baseline = next((a for a in reversed(analyses) if a.is_baseline), analyses[-1])

    def _diff(a: SeoDraftAnalysis, b: SeoDraftAnalysis) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for field in _TRACKED:
            new_value = getattr(a, field)
            old_value = getattr(b, field)
            if new_value is None or old_value is None:
                # Reported as None rather than 0: a metric that did not exist in the older
                # analysis has not "stayed the same".
                out[field] = None
                continue
            out[field] = round(new_value - old_value, 2)
        return out

    return {
        "available": True,
        "since_previous": _diff(newest, previous),
        "since_baseline": _diff(newest, baseline),
        "analyses_counted": len(analyses),
    }


# ── retention: the system proposes, the person decides ────────────────────────────────

def prune_proposal(analyses: list[SeoDraftAnalysis]) -> dict[str, Any]:
    """Whether to raise the subject, and exactly what would go if the answer is yes.

    Returns the ids rather than a count. A prompt that says "delete 14 old analyses" asks for
    consent to something the person cannot see; the caller can render what is actually on the
    table.
    """
    total = len(analyses)
    if total <= PRUNE_PROMPT_AFTER:
        return {
            "prune_suggested": False,
            "total": total,
            "threshold": PRUNE_PROMPT_AFTER,
        }

    keep_ids = {a.id for a in analyses[:PRUNE_KEEP_RECENT]}
    keep_ids |= {a.id for a in analyses if a.is_baseline}
    prunable = [a for a in analyses if a.id not in keep_ids]

    return {
        "prune_suggested": bool(prunable),
        "total": total,
        "threshold": PRUNE_PROMPT_AFTER,
        "keeps_recent": PRUNE_KEEP_RECENT,
        # Stated so the offer is legible: the baseline is never on the table, because pruning it
        # would destroy the comparison the pruning was making room for.
        "keeps_baseline": True,
        "prunable_ids": [a.id for a in prunable],
        "prunable_count": len(prunable),
        "oldest_prunable": prunable[-1].created_at.isoformat()
        if prunable and prunable[-1].created_at
        else None,
    }


def prune_analyses(
    db: Session, *, user_id: Any, draft_id: str, analysis_ids: list[str]
) -> dict[str, Any]:
    """Delete the analyses a person confirmed, and nothing else.

    ★ Takes explicit ids rather than re-deriving the set. Between the proposal and the answer a
    new analysis may have been recorded, and a function that recomputed "what is prunable" would
    delete something the person was never shown. It also refuses to remove a baseline, whatever
    it is asked: the earliest reading is what every comparison is measured against.
    """
    uid = parse_user_id(user_id)
    if uid is None:
        return {"deleted": 0, "refused": 0, "reason": "a valid user_id is required"}
    draft = _owned_draft(db, draft_id, uid)
    if draft is None:
        return {"deleted": 0, "refused": 0, "reason": "draft not found"}

    requested = [str(i) for i in (analysis_ids or []) if i]
    if not requested:
        return {"deleted": 0, "refused": 0, "reason": "nothing was selected"}

    rows = (
        db.query(SeoDraftAnalysis)
        .filter(
            SeoDraftAnalysis.draft_id == draft.id,
            SeoDraftAnalysis.id.in_(requested),
        )
        .all()
    )
    deletable = [r for r in rows if not r.is_baseline]
    refused = len(rows) - len(deletable)

    for row in deletable:
        db.delete(row)
    db.commit()

    if refused:
        logger.info(
            "[SEO] prune kept %d baseline analysis(es) for draft %s", refused, draft.id
        )
    return {
        "deleted": len(deletable),
        "refused": refused,
        "requested": len(requested),
        # Requested-but-missing is not an error: the person may be answering a proposal made
        # before something else removed a row.
        "not_found": len(requested) - len(rows),
    }
