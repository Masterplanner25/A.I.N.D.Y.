"""The market's service: segments, what surrounds them, evidence, and proposals. `MARKET_MODEL_SPEC.md`.

Built the way `work_service.py` is: handlers call these and return data (never ORM rows), refusals
are `HTTPException`s the pipeline serves as the 4xx they name, and nothing reaches the planner block
unless the owner declared it or confirmed a proposal.

Saved leads are read and retired through search's registered jobs (`search.unactioned_leads`,
`search.retire_lead`), so masterplan imports nothing of search's.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.masterplan.market_model import (
    ENTITY_KINDS,
    EVIDENCE_SOURCES,
    EVIDENCE_STANCES,
    SEGMENT_STATUSES,
    MarketEntity,
    MarketEvidence,
    MarketProposal,
    MarketRevision,
    MarketSegment,
    SegmentWork,
)
from apps.masterplan.work_model import Work

#: The planner block's budget (§6): segments shown, and entities per kind per segment.
PLANNER_SEGMENT_LIMIT = 6
PLANNER_ENTITIES_PER_KIND = 5

_TRACKED_FIELDS = ("name", "buyer", "problem", "trigger", "category_terms", "status")
_STATUS_ORDER = {"validated": 0, "testing": 1, "hypothesis": 2, "abandoned": 3}
_TERM_LIMIT = 12


def _uid(user_id: Any):
    uid = parse_user_id(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="user_id is required")
    return uid


def _refuse(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": "market_refused", "message": message})


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _text(value: Any, limit: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit] if limit else text


def _terms(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    out: list[str] = []
    for item in items:
        term = str(item or "").strip()
        if term and _normalize(term) not in {_normalize(t) for t in out}:
            out.append(term[:80])
    return out[:_TERM_LIMIT]


def _evidence_items(value: Any) -> list[dict]:
    """Evidence as the agent or a proposal hands it: dicts with a claim, or bare sentences."""
    out = []
    for item in value if isinstance(value, (list, tuple)) else []:
        if isinstance(item, dict):
            claim = _text(item.get("claim"), 1000)
            url = _text(item.get("source_url") or item.get("url"), 1000)
        else:
            claim, url = _text(item, 1000), None
        if claim:
            out.append({"claim": claim, "source_url": url})
    return out[:10]


# ── Serialisation ──────────────────────────────────────────────────────────────────────────


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def serialize_segment(segment: MarketSegment) -> dict:
    return {
        "id": segment.id,
        "name": segment.name,
        "buyer": segment.buyer,
        "problem": segment.problem,
        "trigger": segment.trigger,
        "category_terms": list(segment.category_terms or []),
        "status": segment.status,
        "provenance": segment.provenance,
        "created_at": _iso(segment.created_at),
    }


def serialize_entity(entity: MarketEntity) -> dict:
    return {
        "id": entity.id,
        "segment_id": entity.segment_id,
        "kind": entity.kind,
        "name": entity.name,
        "url": entity.url,
        "note": entity.note,
        "provenance": entity.provenance,
        "created_at": _iso(entity.created_at),
    }


def serialize_evidence(row: MarketEvidence) -> dict:
    return {
        "id": row.id,
        "segment_id": row.segment_id,
        "entity_id": row.entity_id,
        "claim": row.claim,
        "source_url": row.source_url,
        "source_kind": row.source_kind,
        "stance": row.stance,
        "captured_at": _iso(row.captured_at),
    }


def _owned_segment(db: Session, uid, segment_id: str) -> MarketSegment:
    segment = db.query(MarketSegment).filter(MarketSegment.id == segment_id, MarketSegment.user_id == uid).first()
    if segment is None:
        raise _refuse(404, "segment not found")
    return segment


def _owned_entity(db: Session, uid, entity_id: str) -> MarketEntity:
    entity = db.query(MarketEntity).filter(MarketEntity.id == entity_id, MarketEntity.user_id == uid).first()
    if entity is None:
        raise _refuse(404, "market entry not found")
    return entity


def _owned_work_ids(db: Session, uid, work_ids) -> list[str]:
    wanted = {str(i) for i in (work_ids or []) if i}
    if not wanted:
        return []
    owned = {w.id for w in db.query(Work).filter(Work.user_id == uid, Work.id.in_(wanted)).all()}
    if wanted - owned:
        raise _refuse(404, "work not found")
    return sorted(owned)


def _works_by_name(db: Session, uid, names) -> list[str]:
    """Resolve work names (as the agent writes them) to the owner's works; unknown names drop."""
    wanted = {_normalize(n) for n in (names or []) if n}
    if not wanted:
        return []
    return sorted(w.id for w in db.query(Work).filter(Work.user_id == uid).all() if _normalize(w.name) in wanted)


def _segment_by_name(db: Session, uid, name) -> MarketSegment | None:
    target = _normalize(name or "")
    if not target:
        return None
    for segment in db.query(MarketSegment).filter(MarketSegment.user_id == uid).all():
        if _normalize(segment.name) == target:
            return segment
    return None


# ── The market, as a whole ─────────────────────────────────────────────────────────────────


def list_market(db: Session, user_id: Any) -> dict:
    """Every segment with its works and evidence, every entity, and the vocabularies."""
    uid = _uid(user_id)
    segments = db.query(MarketSegment).filter(MarketSegment.user_id == uid).all()
    segments.sort(key=lambda s: (_STATUS_ORDER.get(s.status, 9), s.name.lower()))
    entities = (
        db.query(MarketEntity).filter(MarketEntity.user_id == uid).order_by(MarketEntity.created_at.asc()).all()
    )
    works = db.query(Work).filter(Work.user_id == uid).order_by(Work.created_at.asc()).all()
    work_names = {w.id: w.name for w in works}
    segment_ids = [s.id for s in segments]
    joins = db.query(SegmentWork).filter(SegmentWork.segment_id.in_(segment_ids)).all() if segment_ids else []
    works_by_segment: dict[str, list[dict]] = {}
    for join in joins:
        if join.work_id in work_names:
            works_by_segment.setdefault(join.segment_id, []).append({"id": join.work_id, "name": work_names[join.work_id]})
    evidence = db.query(MarketEvidence).filter(MarketEvidence.user_id == uid).all()
    by_segment: dict[str, list[dict]] = {}
    by_entity: dict[str, list[dict]] = {}
    for row in evidence:
        if row.segment_id:
            by_segment.setdefault(row.segment_id, []).append(serialize_evidence(row))
        if row.entity_id:
            by_entity.setdefault(row.entity_id, []).append(serialize_evidence(row))
    return {
        "segments": [
            {**serialize_segment(s), "works": works_by_segment.get(s.id, []), "evidence": by_segment.get(s.id, [])}
            for s in segments
        ],
        "entities": [{**serialize_entity(e), "evidence": by_entity.get(e.id, [])} for e in entities],
        "works_available": [{"id": w.id, "name": w.name} for w in works],
        "vocabulary": {"statuses": list(SEGMENT_STATUSES), "kinds": ENTITY_KINDS},
    }


# ── Segments ──────────────────────────────────────────────────────────────────────────────


def _segment_fields(data: dict, *, partial: bool) -> dict:
    out: dict[str, Any] = {}
    if "name" in data or not partial:
        name = _text(data.get("name"), 300)
        if not name:
            raise _refuse(422, "a segment needs a name")
        out["name"] = name
    if "buyer" in data or not partial:
        buyer = _text(data.get("buyer"))
        if not buyer:
            # §3.1: a segment without a buyer is a topic, and a topic is what lead search got wrong.
            raise _refuse(422, "a segment needs a buyer: who decides, and in what kind of organisation")
        out["buyer"] = buyer
    for field in ("problem", "trigger"):
        if field in data:
            out[field] = _text(data.get(field))
    if "category_terms" in data:
        out["category_terms"] = _terms(data.get("category_terms"))
    if "status" in data or not partial:
        status = str(data.get("status") or "hypothesis").strip().lower()
        if status not in SEGMENT_STATUSES:
            raise _refuse(422, f"status must be one of: {', '.join(SEGMENT_STATUSES)}")
        out["status"] = status
    return out


def create_segment(db: Session, user_id: Any, data: dict, *, provenance: str = "declared",
                   work_ids=None, commit: bool = True) -> dict:
    uid = _uid(user_id)
    fields = _segment_fields(data, partial=False)
    if _segment_by_name(db, uid, fields["name"]) is not None:
        raise _refuse(409, f"you already have a segment named {fields['name']!r}")
    segment = MarketSegment(user_id=uid, provenance=provenance, **fields)
    db.add(segment)
    db.flush()
    for work_id in _owned_work_ids(db, uid, work_ids):
        db.add(SegmentWork(segment_id=segment.id, work_id=work_id))
    if commit:
        db.commit()
        db.refresh(segment)
    return serialize_segment(segment)


def update_segment(db: Session, user_id: Any, segment_id: str, data: dict) -> dict:
    """Edit a segment, keeping what it said before. A status change is the bet moving."""
    uid = _uid(user_id)
    segment = _owned_segment(db, uid, segment_id)
    fields = _segment_fields(data, partial=True)
    if "name" in fields:
        other = _segment_by_name(db, uid, fields["name"])
        if other is not None and other.id != segment.id:
            raise _refuse(409, f"you already have a segment named {fields['name']!r}")
    for field, new in fields.items():
        old = getattr(segment, field)
        if old == new:
            continue
        if field in _TRACKED_FIELDS:
            db.add(MarketRevision(
                segment_id=segment.id, field=field,
                old_value=None if old is None else (", ".join(old) if isinstance(old, list) else str(old)),
                new_value=None if new is None else (", ".join(new) if isinstance(new, list) else str(new)),
            ))
        setattr(segment, field, new)
    db.commit()
    db.refresh(segment)
    return serialize_segment(segment)


def delete_segment(db: Session, user_id: Any, segment_id: str) -> dict:
    uid = _uid(user_id)
    segment = _owned_segment(db, uid, segment_id)
    for model, column in ((SegmentWork, SegmentWork.segment_id), (MarketEvidence, MarketEvidence.segment_id),
                          (MarketRevision, MarketRevision.segment_id)):
        db.query(model).filter(column == segment.id).delete(synchronize_session=False)
    db.query(MarketEntity).filter(MarketEntity.segment_id == segment.id).update(
        {MarketEntity.segment_id: None}, synchronize_session=False
    )
    db.delete(segment)
    db.commit()
    return {"deleted": True, "id": segment_id}


def set_segment_works(db: Session, user_id: Any, segment_id: str, work_ids) -> dict:
    """Replace which of the owner's works serve this segment."""
    uid = _uid(user_id)
    segment = _owned_segment(db, uid, segment_id)
    ids = _owned_work_ids(db, uid, work_ids)
    db.query(SegmentWork).filter(SegmentWork.segment_id == segment.id).delete(synchronize_session=False)
    for work_id in ids:
        db.add(SegmentWork(segment_id=segment.id, work_id=work_id))
    db.commit()
    return {"segment_id": segment.id, "work_ids": ids}


# ── Entities and evidence ─────────────────────────────────────────────────────────────────


def _entity_fields(db: Session, uid, data: dict) -> dict:
    name = _text(data.get("name"), 300)
    if not name:
        raise _refuse(422, "a market entry needs a name")
    kind = str(data.get("kind") or "").strip().lower()
    if kind not in ENTITY_KINDS:
        raise _refuse(422, f"kind must be one of: {', '.join(ENTITY_KINDS)}")
    segment_id = _text(data.get("segment_id"))
    if segment_id:
        _owned_segment(db, uid, segment_id)
    return {"name": name, "kind": kind, "segment_id": segment_id,
            "url": _text(data.get("url"), 1000), "note": _text(data.get("note"))}


def create_entity(db: Session, user_id: Any, data: dict, *, provenance: str = "declared",
                  commit: bool = True) -> dict:
    uid = _uid(user_id)
    fields = _entity_fields(db, uid, data)
    entity = MarketEntity(user_id=uid, provenance=provenance, **fields)
    db.add(entity)
    db.flush()
    if commit:
        db.commit()
        db.refresh(entity)
    return serialize_entity(entity)


def delete_entity(db: Session, user_id: Any, entity_id: str) -> dict:
    uid = _uid(user_id)
    entity = _owned_entity(db, uid, entity_id)
    db.query(MarketEvidence).filter(MarketEvidence.entity_id == entity.id).delete(synchronize_session=False)
    db.delete(entity)
    db.commit()
    return {"deleted": True, "id": entity_id}


def add_evidence(db: Session, user_id: Any, *, claim: str, segment_id: str | None = None,
                 entity_id: str | None = None, source_url: str | None = None, source_kind: str = "owner",
                 stance: str = "supports", commit: bool = True) -> dict:
    uid = _uid(user_id)
    if bool(segment_id) == bool(entity_id):
        raise _refuse(422, "evidence belongs to one segment or one market entry")
    if segment_id:
        _owned_segment(db, uid, segment_id)
    if entity_id:
        _owned_entity(db, uid, entity_id)
    claim = _text(claim)
    if not claim:
        raise _refuse(422, "evidence needs a claim, in one sentence")
    if source_kind not in EVIDENCE_SOURCES:
        raise _refuse(422, f"source_kind must be one of: {', '.join(EVIDENCE_SOURCES)}")
    if stance not in EVIDENCE_STANCES:
        raise _refuse(422, f"stance must be one of: {', '.join(EVIDENCE_STANCES)}")
    row = MarketEvidence(user_id=uid, segment_id=segment_id, entity_id=entity_id, claim=claim,
                         source_url=_text(source_url, 1000), source_kind=source_kind, stance=stance)
    db.add(row)
    db.flush()
    if commit:
        db.commit()
    return serialize_evidence(row)


# ── Proposals (§4) ────────────────────────────────────────────────────────────────────────


def propose(db: Session, user_id: Any, args: dict, *, source: str = "agent") -> dict:
    """Record a proposal. The agent's only way in (`market.propose`): it never confirms.

    A proposal naming something the owner already has, or already has open, is not stored twice.
    """
    uid = _uid(user_id)
    kind = str(args.get("kind") or "").strip().lower()
    if kind != "segment" and kind not in ENTITY_KINDS:
        raise ValueError(f"kind must be 'segment' or one of: {', '.join(ENTITY_KINDS)}")
    name = _text(args.get("name"), 300)
    if not name:
        raise ValueError("a proposal needs a name")
    target = _normalize(name)
    if kind == "segment":
        known = _segment_by_name(db, uid, name) is not None
    else:
        known = any(
            _normalize(e.name) == target and e.kind == kind
            for e in db.query(MarketEntity).filter(MarketEntity.user_id == uid).all()
        )
    if not known:
        for row in db.query(MarketProposal).filter(MarketProposal.user_id == uid, MarketProposal.status == "open"):
            payload = row.payload or {}
            if payload.get("kind") == kind and _normalize(payload.get("name")) == target:
                known = True
                break
    if known:
        return {"proposed": False, "key": None, "reason": f"{name!r} is already known or awaiting the owner"}
    payload = {
        "kind": kind,
        "name": name,
        "note": _text(args.get("note")),
        "url": _text(args.get("url"), 1000),
        "segment": _text(args.get("segment"), 300),
        "buyer": _text(args.get("buyer")),
        "problem": _text(args.get("problem")),
        "trigger": _text(args.get("trigger")),
        "category_terms": _terms(args.get("category_terms")),
        "works": [str(w) for w in (args.get("works") or []) if w][:10],
        "evidence": _evidence_items(args.get("evidence")),
    }
    row = MarketProposal(user_id=uid, proposal_key=f"{source}:{uuid.uuid4()}", source=source,
                         payload=payload, status="open")
    db.add(row)
    db.commit()
    return {"proposed": True, "key": row.proposal_key, "reason": "awaiting the owner's answer"}


def _lead_proposals(db: Session, uid) -> list[dict]:
    """Saved leads nobody acted on: were they buyers, or market research filed as leads? (§4.1)"""
    from AINDY.platform_layer.registry import get_job

    unactioned = get_job("search.unactioned_leads")
    if unactioned is None:
        return []
    out = []
    for lead in unactioned(user_id=str(uid), db=db) or []:
        context = _text(lead.get("context"), 400)
        out.append({
            "key": f"lead:{lead['id']}",
            "source": "lead",
            "question": (f"Lead search saved {lead.get('company')!r} as a lead. Is it market research: "
                         "an alternative, a channel, an intermediary, a voice or an exemplar?"),
            "kind": None,
            "name": lead.get("company") or "",
            "url": lead.get("url"),
            "note": f"Saved as a lead by the search {lead.get('query')!r}" if lead.get("query") else None,
            "segment": None,
            "buyer": None, "problem": None, "trigger": None, "category_terms": [], "works": [],
            "evidence": [{"claim": context, "source_url": lead.get("url")}] if context else [],
            "lead_id": lead["id"],
        })
    return out


def _stored_proposal(row: MarketProposal) -> dict:
    payload = dict(row.payload or {})
    kind = payload.get("kind")
    question = (f"Is {payload.get('name')!r} a segment of your market?" if kind == "segment"
                else f"Is {payload.get('name')!r} a {kind} in your market?")
    return {
        "key": row.proposal_key,
        "source": row.source,
        "question": question,
        "kind": kind,
        "name": payload.get("name") or "",
        "url": payload.get("url"),
        "note": payload.get("note"),
        "segment": payload.get("segment"),
        "buyer": payload.get("buyer"),
        "problem": payload.get("problem"),
        "trigger": payload.get("trigger"),
        "category_terms": payload.get("category_terms") or [],
        "works": payload.get("works") or [],
        "evidence": payload.get("evidence") or [],
        "lead_id": None,
        "created_at": _iso(row.created_at),
    }


def list_proposals(db: Session, user_id: Any) -> dict:
    uid = _uid(user_id)
    decided = {
        row.proposal_key
        for row in db.query(MarketProposal).filter(MarketProposal.user_id == uid, MarketProposal.status != "open")
    }
    derived = [p for p in _lead_proposals(db, uid) if p["key"] not in decided]
    stored = [
        _stored_proposal(row)
        for row in db.query(MarketProposal)
        .filter(MarketProposal.user_id == uid, MarketProposal.status == "open")
        .order_by(MarketProposal.created_at.asc())
        .all()
    ]
    return {"proposals": derived + stored}


def _find_proposal(db: Session, uid, key: str) -> dict:
    for proposal in list_proposals(db, uid)["proposals"]:
        if proposal["key"] == key:
            return proposal
    raise _refuse(404, "that proposal is no longer open")


def _record_decision(db: Session, uid, proposal: dict, status: str) -> None:
    now = datetime.now(timezone.utc)
    row = (
        db.query(MarketProposal)
        .filter(MarketProposal.user_id == uid, MarketProposal.proposal_key == proposal["key"])
        .first()
    )
    if row is None:
        row = MarketProposal(user_id=uid, proposal_key=proposal["key"], source=proposal["source"],
                             payload={"kind": proposal.get("kind"), "name": proposal.get("name")}, status=status)
        db.add(row)
    row.status = status
    row.decided_at = now


def confirm_proposal(db: Session, user_id: Any, key: str, edits: dict) -> dict:
    """The owner accepts a proposal, in their own words: their edits override the suggestion.

    A confirmed lead proposal is re-filed: the market entry is created with the lead's context as
    its evidence, and the saved lead is retired (never one that had outreach).
    """
    uid = _uid(user_id)
    proposal = _find_proposal(db, uid, key)
    edits = {k: v for k, v in (edits or {}).items() if v is not None}
    kind = str(edits.get("kind") or proposal.get("kind") or "").strip().lower()
    if not kind:
        raise _refuse(422, "choose what this is: segment, or one of " + ", ".join(ENTITY_KINDS))
    if kind == "segment":
        data = {f: proposal.get(f) for f in ("name", "buyer", "problem", "trigger", "category_terms")}
        data.update({k: v for k, v in edits.items() if k in data or k == "status"})
        work_ids = edits.get("work_ids")
        if work_ids is None:
            work_ids = _works_by_name(db, uid, proposal.get("works"))
        record = create_segment(db, uid, data, provenance="confirmed", work_ids=work_ids, commit=False)
        target = {"segment_id": record["id"]}
    else:
        segment_id = edits.get("segment_id")
        if segment_id is None and proposal.get("segment"):
            match = _segment_by_name(db, uid, proposal["segment"])
            segment_id = match.id if match else None
        data = {"kind": kind, "name": edits.get("name", proposal.get("name")),
                "url": edits.get("url", proposal.get("url")), "note": edits.get("note", proposal.get("note")),
                "segment_id": segment_id}
        record = create_entity(db, uid, data, provenance="confirmed", commit=False)
        target = {"entity_id": record["id"]}
    for item in proposal.get("evidence") or []:
        add_evidence(db, uid, claim=item["claim"], source_url=item.get("source_url"),
                     source_kind="research", stance="supports", commit=False, **target)
    _record_decision(db, uid, proposal, "confirmed")
    retired = False
    if proposal.get("lead_id") is not None:
        from AINDY.platform_layer.registry import get_job

        retire = get_job("search.retire_lead")
        retired = bool(retire and retire(user_id=str(uid), lead_id=proposal["lead_id"], db=db))
    db.commit()
    return {"kind": kind, "record": record, "lead_retired": retired}


def dismiss_proposal(db: Session, user_id: Any, key: str) -> dict:
    """Not part of your market: not asked again. A lead proposal dismissed stays a lead."""
    uid = _uid(user_id)
    proposal = _find_proposal(db, uid, key)
    _record_decision(db, uid, proposal, "dismissed")
    db.commit()
    return {"dismissed": True, "key": key}


# ── What the planner sees (§6) ────────────────────────────────────────────────────────────


BLOCK_HEADING = (
    "## The user's market (confirmed by them). A HYPOTHESIS is a bet, not a fact: gather evidence "
    "before acting on it. Record new market findings with market.propose, not as leads"
)


def render_market_block(ctx: dict | None) -> str:
    """The planner's market block. One renderer, so Collaborator shows exactly what the agent is told."""
    if not ctx or not (ctx.get("segments") or ctx.get("unattached") or ctx.get("open_proposals")):
        return ""
    lines = ["", BLOCK_HEADING]
    for segment in ctx.get("segments") or []:
        line = f"- {segment['name']} — {segment['status'].upper()}. Buyer: {segment['buyer']}."
        if segment.get("problem"):
            line += f" Problem: \"{segment['problem']}\"."
        if segment.get("category_terms"):
            line += f" Calls it: {', '.join(segment['category_terms'])}."
        if segment.get("works"):
            line += f" Served by: {', '.join(segment['works'])}."
        for kind, names in (segment.get("entities") or {}).items():
            line += f" {kind.capitalize()}s: {', '.join(names)}."
        lines.append(line)
    hidden = int(ctx.get("total_segments") or 0) - len(ctx.get("segments") or [])
    if hidden > 0:
        lines.append(f"({hidden} more segments not shown)")
    for kind, names in (ctx.get("unattached") or {}).items():
        lines.append(f"- {kind.capitalize()}s, not tied to a segment: {', '.join(names)}.")
    if ctx.get("open_proposals"):
        lines.append(f"({ctx['open_proposals']} market proposals await the user's answer; do not re-propose them)")
    return "\n".join(lines) + "\n"


def _grouped(entities: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for entity in entities:
        names = grouped.setdefault(entity["kind"], [])
        if len(names) < PLANNER_ENTITIES_PER_KIND:
            names.append(entity["name"])
    return grouped


def market_context(*, user_id: Any, db: Session) -> dict | None:
    """The confirmed market, compact, for the planner block. Capped (§6)."""
    uid = parse_user_id(user_id)
    if uid is None:
        return None
    listing = list_market(db, uid)
    open_count = len(list_proposals(db, uid)["proposals"])
    if not listing["segments"] and not listing["entities"] and not open_count:
        return None
    segments = listing["segments"][:PLANNER_SEGMENT_LIMIT]
    ctx = {
        "segments": [
            {
                "name": s["name"], "status": s["status"], "buyer": s["buyer"], "problem": s["problem"],
                "category_terms": s["category_terms"], "works": [w["name"] for w in s["works"]],
                "entities": _grouped([e for e in listing["entities"] if e["segment_id"] == s["id"]]),
            }
            for s in segments
        ],
        "total_segments": len(listing["segments"]),
        "unattached": _grouped([e for e in listing["entities"] if not e["segment_id"]]),
        "open_proposals": open_count,
    }
    ctx["block"] = render_market_block(ctx)
    return ctx


def market_overview(db: Session, user_id: Any) -> dict:
    """What `GET /apps/market` serves: the market, plus the exact block the agent is sent."""
    listing = list_market(db, user_id)
    listing["agent_block"] = render_market_block(market_context(user_id=user_id, db=db))
    return listing
