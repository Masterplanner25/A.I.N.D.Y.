"""The Work model's HTTP surface — `WORK_MODEL_SPEC.md` §3–§4. Served at `/apps/works`.

Every handler returns data and every call hands the pipeline the request session
(`CLAUDE.md`: *a pipeline handler returns data, not ORM rows, and every call passes
`metadata={"db": db}`*). Route names stay within `system_events.source`'s width.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from AINDY.core.execution_helper import execute_with_pipeline
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.services.auth_service import get_current_user

from apps.masterplan.routes.masterplan_router import _with_execution_envelope

router = APIRouter(prefix="/works", tags=["Works"])


class WorkBody(BaseModel):
    name: Optional[str] = None
    summary: Optional[str] = None
    kind: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    started_on: Optional[str] = None
    ended_on: Optional[str] = None
    url: Optional[str] = None
    declared_target: Optional[str] = None


class LinkBody(BaseModel):
    to_work_id: str
    relation: str
    note: Optional[str] = None


class ObjectivesBody(BaseModel):
    objective_ids: list[str] = []


class ProposalBody(BaseModel):
    key: str
    name: Optional[str] = None
    summary: Optional[str] = None
    kind: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None


async def _run(request: Request, route_name: str, handler, *, db: Session, user_id: str, payload: dict):
    result = await execute_with_pipeline(
        request=request,
        route_name=route_name,
        handler=handler,
        user_id=user_id,
        input_payload=payload,
        metadata={"db": db},
    )
    return _with_execution_envelope(result)


def _set_fields(body: BaseModel) -> dict:
    return body.model_dump(exclude_unset=True)


@router.get("")
@limiter.limit("60/minute")
async def list_works_route(request: Request, db: Session = Depends(get_db),
                           current_user: dict = Depends(get_current_user)):
    """Your works, how they relate, and what they serve."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.work_service import works_overview
        return works_overview(db, user_id)

    return await _run(request, "masterplan.works.list", handler, db=db, user_id=user_id, payload={})


@router.post("")
@limiter.limit("30/minute")
async def create_work_route(request: Request, body: WorkBody, db: Session = Depends(get_db),
                            current_user: dict = Depends(get_current_user)):
    """Declare a work, in your words."""
    user_id = str(current_user["sub"])
    fields = _set_fields(body)

    def handler(ctx):
        from apps.masterplan.services.work_service import create_work
        return create_work(db, user_id, fields)

    return await _run(request, "masterplan.works.create", handler, db=db, user_id=user_id, payload=fields)


@router.get("/proposals")
@limiter.limit("60/minute")
async def list_work_proposals_route(request: Request, db: Session = Depends(get_db),
                                    current_user: dict = Depends(get_current_user)):
    """What the system can already see and asks you about. Reads only."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.work_service import list_proposals
        return list_proposals(db, user_id)

    return await _run(request, "masterplan.works.proposals", handler, db=db, user_id=user_id, payload={})


@router.post("/proposals/confirm")
@limiter.limit("30/minute")
async def confirm_work_proposal_route(request: Request, body: ProposalBody, db: Session = Depends(get_db),
                                      current_user: dict = Depends(get_current_user)):
    """Accept a proposal. Your edits replace the suggestion."""
    user_id = str(current_user["sub"])
    edits = {k: v for k, v in _set_fields(body).items() if k != "key"}

    def handler(ctx):
        from apps.masterplan.services.work_service import confirm_proposal
        return confirm_proposal(db, user_id, body.key, edits)

    return await _run(request, "masterplan.works.confirm", handler, db=db, user_id=user_id,
                      payload={"key": body.key, **edits})


@router.post("/proposals/dismiss")
@limiter.limit("30/minute")
async def dismiss_work_proposal_route(request: Request, body: ProposalBody, db: Session = Depends(get_db),
                                      current_user: dict = Depends(get_current_user)):
    """Not a work of yours: it is not asked again."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.work_service import dismiss_proposal
        return dismiss_proposal(db, user_id, body.key)

    return await _run(request, "masterplan.works.dismiss", handler, db=db, user_id=user_id,
                      payload={"key": body.key})


@router.patch("/{work_id}")
@limiter.limit("30/minute")
async def update_work_route(request: Request, work_id: str, body: WorkBody, db: Session = Depends(get_db),
                            current_user: dict = Depends(get_current_user)):
    """Edit a work. What it said before is kept."""
    user_id = str(current_user["sub"])
    fields = _set_fields(body)

    def handler(ctx):
        from apps.masterplan.services.work_service import update_work
        return update_work(db, user_id, work_id, fields)

    return await _run(request, "masterplan.works.update", handler, db=db, user_id=user_id,
                      payload={"work_id": work_id, **fields})


@router.delete("/{work_id}")
@limiter.limit("30/minute")
async def delete_work_route(request: Request, work_id: str, db: Session = Depends(get_db),
                            current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.work_service import delete_work
        return delete_work(db, user_id, work_id)

    return await _run(request, "masterplan.works.delete", handler, db=db, user_id=user_id,
                      payload={"work_id": work_id})


@router.post("/{work_id}/links")
@limiter.limit("30/minute")
async def add_work_link_route(request: Request, work_id: str, body: LinkBody, db: Session = Depends(get_db),
                              current_user: dict = Depends(get_current_user)):
    """Relate two works: built_on, executes, demonstrates, part_of, informs, precedes."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.work_service import add_link
        return add_link(db, user_id, work_id, to_work_id=body.to_work_id, relation=body.relation,
                        note=body.note)

    return await _run(request, "masterplan.works.link.add", handler, db=db, user_id=user_id,
                      payload={"work_id": work_id, **body.model_dump()})


@router.delete("/links/{link_id}")
@limiter.limit("30/minute")
async def remove_work_link_route(request: Request, link_id: str, db: Session = Depends(get_db),
                                 current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.work_service import remove_link
        return remove_link(db, user_id, link_id)

    return await _run(request, "masterplan.works.link.remove", handler, db=db, user_id=user_id,
                      payload={"link_id": link_id})


@router.put("/{work_id}/objectives")
@limiter.limit("30/minute")
async def set_work_objectives_route(request: Request, work_id: str, body: ObjectivesBody,
                                    db: Session = Depends(get_db),
                                    current_user: dict = Depends(get_current_user)):
    """Which objectives of your plan this work serves."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.work_service import set_objectives
        return set_objectives(db, user_id, work_id, body.objective_ids)

    return await _run(request, "masterplan.works.objectives", handler, db=db, user_id=user_id,
                      payload={"work_id": work_id, "objective_ids": body.objective_ids})
