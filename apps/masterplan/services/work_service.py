"""The Work model's service: declare, relate, propose-then-confirm. `WORK_MODEL_SPEC.md` §3–§4, §6.

Handlers call these and return data (never ORM rows): `CLAUDE.md`, *a pipeline handler returns
data*. Refusals are `HTTPException`s raised inside the handler, which the pipeline serves as the
4xx they name.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.masterplan.work_model import (
    WORK_KINDS,
    WORK_RELATIONS,
    WORK_ROLES,
    WORK_STATUSES,
    Work,
    WorkLink,
    WorkObjective,
    WorkProposalDismissal,
    WorkRevision,
)

#: What the planner block may carry at most (§6): the block must never crowd out the plan.
PLANNER_WORK_LIMIT = 12

_TRACKED_FIELDS = ("name", "kind", "summary", "role", "status", "url", "declared_target")


def _uid(user_id: Any):
    uid = parse_user_id(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="user_id is required")
    return uid


def _refuse(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": "work_refused", "message": message})


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _date(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise _refuse(422, f"{field} must be a date (YYYY-MM-DD)")


def _clean_fields(data: dict, *, partial: bool) -> dict:
    """Validate the owner's fields against the closed vocabularies."""
    out: dict[str, Any] = {}
    if "name" in data or not partial:
        name = str(data.get("name") or "").strip()
        if not name:
            raise _refuse(422, "a work needs a name")
        out["name"] = name[:300]
    if "summary" in data or not partial:
        summary = str(data.get("summary") or "").strip()
        if not summary:
            # §3.1: a work without one, in the owner's words, is a string with an id.
            raise _refuse(422, "a work needs a summary, in your words: what it is")
        out["summary"] = summary
    for field, allowed, default in (
        ("kind", WORK_KINDS, "project"),
        ("role", WORK_ROLES, "creator"),
        ("status", WORK_STATUSES, "active"),
    ):
        if field in data or not partial:
            value = str(data.get(field) or default).strip().lower()
            if value not in allowed:
                raise _refuse(422, f"{field} must be one of: {', '.join(allowed)}")
            out[field] = value
    for field in ("started_on", "ended_on"):
        if field in data:
            out[field] = _date(data.get(field), field)
    if "url" in data:
        out["url"] = (str(data.get("url") or "").strip() or None)
        if out["url"] and len(out["url"]) > 500:
            raise _refuse(422, "url is too long")
    if "declared_target" in data:
        out["declared_target"] = (str(data.get("declared_target") or "").strip() or None)
    return out


def serialize_work(work: Work) -> dict:
    return {
        "id": work.id,
        "name": work.name,
        "kind": work.kind,
        "summary": work.summary,
        "role": work.role,
        "status": work.status,
        "started_on": work.started_on.isoformat() if work.started_on else None,
        "ended_on": work.ended_on.isoformat() if work.ended_on else None,
        "url": work.url,
        "declared_target": work.declared_target,
        "container_id": work.container_id,
        "provenance": work.provenance,
        "created_at": work.created_at.isoformat() if work.created_at else None,
    }


def _owned_work(db: Session, uid, work_id: str) -> Work:
    work = db.query(Work).filter(Work.id == work_id, Work.user_id == uid).first()
    if work is None:
        raise _refuse(404, "work not found")
    return work


def _name_taken(db: Session, uid, name: str, *, except_id: str | None = None) -> bool:
    target = _normalize(name)
    for other in db.query(Work).filter(Work.user_id == uid).all():
        if other.id != except_id and _normalize(other.name) == target:
            return True
    return False


# ── Works ───────────────────────────────────────────────────────────────────────────────────


def list_works(db: Session, user_id: Any) -> dict:
    """Every work, its links and its objectives, plus the vocabularies the UI offers."""
    from apps.masterplan.strategy_layer import PlanObjective

    uid = _uid(user_id)
    works = db.query(Work).filter(Work.user_id == uid).order_by(Work.created_at.asc()).all()
    ids = [w.id for w in works]
    links = db.query(WorkLink).filter(WorkLink.user_id == uid).all()
    objective_rows = (
        db.query(WorkObjective, PlanObjective)
        .join(PlanObjective, PlanObjective.id == WorkObjective.objective_id)
        .filter(WorkObjective.work_id.in_(ids))
        .all()
        if ids
        else []
    )
    objectives_by_work: dict[str, list[dict]] = {}
    for link, objective in objective_rows:
        objectives_by_work.setdefault(link.work_id, []).append({"id": objective.id, "name": objective.name})
    from apps.masterplan.models import MasterPlan

    plan = db.query(MasterPlan).filter(MasterPlan.user_id == uid, MasterPlan.is_active.is_(True)).first()
    available = (
        db.query(PlanObjective)
        .filter(PlanObjective.masterplan_id == plan.id)
        .order_by(PlanObjective.ordinal.asc())
        .all()
        if plan is not None
        else []
    )
    return {
        "works": [{**serialize_work(w), "objectives": objectives_by_work.get(w.id, [])} for w in works],
        "objectives_available": [{"id": o.id, "name": o.name} for o in available],
        "links": [
            {"id": link.id, "from_work_id": link.from_work_id, "to_work_id": link.to_work_id,
             "relation": link.relation, "note": link.note}
            for link in links
        ],
        "vocabulary": {
            "kinds": list(WORK_KINDS),
            "roles": list(WORK_ROLES),
            "statuses": list(WORK_STATUSES),
            "relations": WORK_RELATIONS,
        },
    }


def create_work(db: Session, user_id: Any, data: dict, *, provenance: str = "declared",
                container_id: str | None = None) -> dict:
    uid = _uid(user_id)
    fields = _clean_fields(data, partial=False)
    if _name_taken(db, uid, fields["name"]):
        raise _refuse(409, f"you already have a work named {fields['name']!r}")
    work = Work(user_id=uid, provenance=provenance, container_id=container_id, **fields)
    db.add(work)
    db.commit()
    db.refresh(work)
    return serialize_work(work)


def update_work(db: Session, user_id: Any, work_id: str, data: dict) -> dict:
    """Edit a work, keeping what it said before (§3.4)."""
    uid = _uid(user_id)
    work = _owned_work(db, uid, work_id)
    fields = _clean_fields(data, partial=True)
    if "name" in fields and _name_taken(db, uid, fields["name"], except_id=work.id):
        raise _refuse(409, f"you already have a work named {fields['name']!r}")
    for field, new in fields.items():
        old = getattr(work, field)
        if old == new:
            continue
        if field in _TRACKED_FIELDS:
            db.add(WorkRevision(work_id=work.id, field=field,
                                old_value=None if old is None else str(old),
                                new_value=None if new is None else str(new)))
        setattr(work, field, new)
    db.commit()
    db.refresh(work)
    return serialize_work(work)


def delete_work(db: Session, user_id: Any, work_id: str) -> dict:
    uid = _uid(user_id)
    work = _owned_work(db, uid, work_id)
    for model, column in ((WorkLink, WorkLink.from_work_id), (WorkLink, WorkLink.to_work_id),
                          (WorkObjective, WorkObjective.work_id), (WorkRevision, WorkRevision.work_id)):
        db.query(model).filter(column == work.id).delete(synchronize_session=False)
    db.delete(work)
    db.commit()
    return {"deleted": True, "id": work_id}


# ── Relations and objectives ───────────────────────────────────────────────────────────────


def add_link(db: Session, user_id: Any, work_id: str, *, to_work_id: str, relation: str,
             note: str | None = None) -> dict:
    uid = _uid(user_id)
    relation = str(relation or "").strip().lower()
    if relation not in WORK_RELATIONS:
        raise _refuse(422, f"relation must be one of: {', '.join(WORK_RELATIONS)}")
    source = _owned_work(db, uid, work_id)
    target = _owned_work(db, uid, to_work_id)
    if source.id == target.id:
        raise _refuse(422, "a work cannot relate to itself")
    exists = (
        db.query(WorkLink)
        .filter(WorkLink.from_work_id == source.id, WorkLink.to_work_id == target.id,
                WorkLink.relation == relation)
        .first()
    )
    if exists:
        raise _refuse(409, "that link already exists")
    link = WorkLink(user_id=uid, from_work_id=source.id, to_work_id=target.id, relation=relation,
                    note=(note or "").strip() or None)
    db.add(link)
    db.commit()
    return {"id": link.id, "from_work_id": source.id, "to_work_id": target.id,
            "relation": relation, "note": link.note}


def remove_link(db: Session, user_id: Any, link_id: str) -> dict:
    uid = _uid(user_id)
    link = db.query(WorkLink).filter(WorkLink.id == link_id, WorkLink.user_id == uid).first()
    if link is None:
        raise _refuse(404, "link not found")
    db.delete(link)
    db.commit()
    return {"deleted": True, "id": link_id}


def set_objectives(db: Session, user_id: Any, work_id: str, objective_ids: list[str]) -> dict:
    """Replace the objectives a work serves. Only objectives of the owner's own plans."""
    from apps.masterplan.models import MasterPlan
    from apps.masterplan.strategy_layer import PlanObjective

    uid = _uid(user_id)
    work = _owned_work(db, uid, work_id)
    wanted = {str(i) for i in (objective_ids or []) if i}
    if wanted:
        owned = {
            row.id
            for row in db.query(PlanObjective)
            .join(MasterPlan, MasterPlan.id == PlanObjective.masterplan_id)
            .filter(MasterPlan.user_id == uid, PlanObjective.id.in_(wanted))
            .all()
        }
        missing = wanted - owned
        if missing:
            raise _refuse(404, "objective not found in your plan")
    db.query(WorkObjective).filter(WorkObjective.work_id == work.id).delete(synchronize_session=False)
    for objective_id in sorted(wanted):
        db.add(WorkObjective(work_id=work.id, objective_id=objective_id))
    db.commit()
    return {"work_id": work.id, "objective_ids": sorted(wanted)}


# ── Proposals: derived on demand, never stored (the container rule) ─────────────────────────


_KEY_ASSET = re.compile(r"^\s*(?P<name>[^()]+?)\s*\((?P<desc>[^)]*)\)\s*$")


def _key_asset_proposals(db: Session, uid) -> list[dict]:
    """The MasterPlan's `key_assets` strings: *"Nodus (orchestration DSL)"* → name + a starting
    summary the owner is asked to confirm or rewrite."""
    from apps.masterplan.models import MasterPlan

    plan = (
        db.query(MasterPlan)
        .filter(MasterPlan.user_id == uid, MasterPlan.is_active.is_(True))
        .first()
    )
    structure = plan.structure_json if plan is not None and isinstance(plan.structure_json, dict) else {}
    out = []
    for raw in structure.get("key_assets") or []:
        text = str(raw or "").strip()
        if not text:
            continue
        match = _KEY_ASSET.match(text)
        name, desc = (match.group("name"), match.group("desc")) if match else (text, "")
        out.append({
            "key": f"key_asset:{_normalize(text)}",
            "source": "key_asset",
            "question": f"Is {name.strip()!r} something you made? Describe it in your words.",
            "evidence": f"Your MasterPlan lists it as a key asset: {text!r}",
            "name": name.strip(),
            "summary": desc.strip(),
            "kind": "project",
            "role": "creator",
            "status": "active",
            "container_id": None,
        })
    return out


def _container_proposals(db: Session, uid) -> list[dict]:
    """The series the owner already confirmed in RippleTrace (`TITLE_AS_CONTAINER_SPEC` §4b)."""
    from AINDY.platform_layer.registry import get_job

    confirmed = get_job("rippletrace.confirmed_containers")
    if confirmed is None:
        return []
    out = []
    for container in confirmed(user_id=str(uid), db=db) or []:
        count = container.get("drop_count_at_decision")
        out.append({
            "key": f"container:{container['id']}",
            "source": "container",
            "question": f"You confirmed {container['name']!r} as a series of yours. What was it for?",
            "evidence": f"Confirmed in RippleTrace" + (f", {count} pieces at the time" if count else ""),
            "name": container["name"],
            "summary": "",
            "kind": "series",
            "role": "author",
            "status": "active",
            "container_id": container["id"],
        })
    return out


def list_proposals(db: Session, user_id: Any) -> dict:
    """What the system can already see and asks about (§4.1). Answered or declined ones drop out."""
    uid = _uid(user_id)
    works = db.query(Work).filter(Work.user_id == uid).all()
    taken_names = {_normalize(w.name) for w in works}
    taken_containers = {w.container_id for w in works if w.container_id}
    dismissed = {d.proposal_key for d in db.query(WorkProposalDismissal).filter(WorkProposalDismissal.user_id == uid)}
    proposals = []
    for proposal in _key_asset_proposals(db, uid) + _container_proposals(db, uid):
        if proposal["key"] in dismissed:
            continue
        if _normalize(proposal["name"]) in taken_names:
            continue
        if proposal["container_id"] and proposal["container_id"] in taken_containers:
            continue
        proposals.append(proposal)
    return {"proposals": proposals}


def _find_proposal(db: Session, uid, key: str) -> dict:
    for proposal in list_proposals(db, uid)["proposals"]:
        if proposal["key"] == key:
            return proposal
    raise _refuse(404, "that proposal is no longer open")


def confirm_proposal(db: Session, user_id: Any, key: str, edits: dict) -> dict:
    """The owner accepts a proposal, in their own words: their edits override the suggestion."""
    uid = _uid(user_id)
    proposal = _find_proposal(db, uid, key)
    data = {field: proposal[field] for field in ("name", "summary", "kind", "role", "status")}
    data.update({k: v for k, v in (edits or {}).items() if v is not None})
    return create_work(db, uid, data, provenance="confirmed", container_id=proposal["container_id"])


def dismiss_proposal(db: Session, user_id: Any, key: str) -> dict:
    uid = _uid(user_id)
    _find_proposal(db, uid, key)
    db.add(WorkProposalDismissal(user_id=uid, proposal_key=key))
    db.commit()
    return {"dismissed": True, "key": key}


# ── What the planner sees (§6) ────────────────────────────────────────────────────────────


BLOCK_HEADING = "## The user's work (stated or confirmed by them; use it, do not invent more)"


def render_work_block(ctx: dict | None) -> str:
    """The planner's "your work" block, as text. One renderer: the planner sends it and
    Collaborator shows it, so the owner sees exactly what the agent is told (§6)."""
    if not ctx or not ctx.get("works"):
        return ""
    lines = ["", BLOCK_HEADING]
    for work in ctx["works"]:
        line = f"- {work['name']} ({work['kind']}, {work['role']}, {work['status']}): {work['summary']}"
        if work.get("relations"):
            line += f"; {'; '.join(work['relations'])}"
        if work.get("serves"):
            line += f"; serves {', '.join(work['serves'])}"
        lines.append(line)
    hidden = int(ctx.get("total") or 0) - len(ctx["works"])
    if hidden > 0:
        lines.append(f"({hidden} more not shown)")
    return "\n".join(lines) + "\n"


def work_context(*, user_id: Any, db: Session) -> dict | None:
    """The owner's works, compact, for the planner block. Only what the owner stated or confirmed
    exists in this table, so all of it may be used. Active first, capped at PLANNER_WORK_LIMIT."""
    uid = parse_user_id(user_id)
    if uid is None:
        return None
    listing = list_works(db, uid)
    works = listing["works"]
    if not works:
        return None
    order = {"active": 0, "planned": 1, "paused": 2, "finished": 3}
    works = sorted(works, key=lambda w: (order.get(w["status"], 9), w["name"].lower()))[:PLANNER_WORK_LIMIT]
    names = {w["id"]: w["name"] for w in listing["works"]}
    relations: dict[str, list[str]] = {}
    for link in listing["links"]:
        if link["from_work_id"] in names and link["to_work_id"] in names:
            relations.setdefault(link["from_work_id"], []).append(
                f"{link['relation'].replace('_', ' ')} {names[link['to_work_id']]}"
            )
    ctx = {
        "works": [
            {
                "name": w["name"], "kind": w["kind"], "role": w["role"], "status": w["status"],
                "summary": w["summary"], "relations": relations.get(w["id"], []),
                "serves": [o["name"] for o in w["objectives"]],
            }
            for w in works
        ],
        "total": len(listing["works"]),
    }
    ctx["block"] = render_work_block(ctx)
    return ctx


def works_overview(db: Session, user_id: Any) -> dict:
    """What `GET /apps/works` serves: the works, plus the exact block the agent is sent (§6)."""
    listing = list_works(db, user_id)
    listing["agent_block"] = render_work_block(work_context(user_id=user_id, db=db))
    return listing
