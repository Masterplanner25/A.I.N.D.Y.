"""The market's HTTP surface — `MARKET_MODEL_SPEC.md` §3–§4. Served at `/apps/market`.

Built as `works_router.py`: every handler returns data, every call hands the pipeline the request
session, and route names stay within `system_events.source`'s width.
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

router = APIRouter(prefix="/market", tags=["Market"])


class SegmentBody(BaseModel):
    name: Optional[str] = None
    buyer: Optional[str] = None
    problem: Optional[str] = None
    trigger: Optional[str] = None
    category_terms: Optional[list[str]] = None
    status: Optional[str] = None
    work_ids: Optional[list[str]] = None


class EntityBody(BaseModel):
    kind: str
    name: str
    url: Optional[str] = None
    note: Optional[str] = None
    segment_id: Optional[str] = None


class EvidenceBody(BaseModel):
    claim: str
    segment_id: Optional[str] = None
    entity_id: Optional[str] = None
    source_url: Optional[str] = None
    stance: str = "supports"


class WorksBody(BaseModel):
    work_ids: list[str] = []


class ProposalBody(BaseModel):
    key: str
    kind: Optional[str] = None
    name: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None
    segment_id: Optional[str] = None
    buyer: Optional[str] = None
    problem: Optional[str] = None
    trigger: Optional[str] = None
    category_terms: Optional[list[str]] = None
    status: Optional[str] = None
    work_ids: Optional[list[str]] = None


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


@router.get("")
@limiter.limit("60/minute")
async def list_market_route(request: Request, db: Session = Depends(get_db),
                            current_user: dict = Depends(get_current_user)):
    """Your market: segments, what surrounds them, the evidence, and what the agent is told."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.market_service import market_overview
        return market_overview(db, user_id)

    return await _run(request, "masterplan.market.list", handler, db=db, user_id=user_id, payload={})


@router.get("/proposals")
@limiter.limit("60/minute")
async def list_market_proposals_route(request: Request, db: Session = Depends(get_db),
                                      current_user: dict = Depends(get_current_user)):
    """What the system and the agent propose about your market. Reads only."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.market_service import list_proposals
        return list_proposals(db, user_id)

    return await _run(request, "masterplan.market.proposals", handler, db=db, user_id=user_id, payload={})


@router.post("/proposals/confirm")
@limiter.limit("30/minute")
async def confirm_market_proposal_route(request: Request, body: ProposalBody, db: Session = Depends(get_db),
                                        current_user: dict = Depends(get_current_user)):
    """Accept a proposal. Your edits replace the suggestion."""
    user_id = str(current_user["sub"])
    edits = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "key"}

    def handler(ctx):
        from apps.masterplan.services.market_service import confirm_proposal
        return confirm_proposal(db, user_id, body.key, edits)

    return await _run(request, "masterplan.market.confirm", handler, db=db, user_id=user_id,
                      payload={"key": body.key, **edits})


@router.post("/proposals/dismiss")
@limiter.limit("30/minute")
async def dismiss_market_proposal_route(request: Request, body: ProposalBody, db: Session = Depends(get_db),
                                        current_user: dict = Depends(get_current_user)):
    """Not part of your market: it is not asked again."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.market_service import dismiss_proposal
        return dismiss_proposal(db, user_id, body.key)

    return await _run(request, "masterplan.market.dismiss", handler, db=db, user_id=user_id,
                      payload={"key": body.key})


@router.post("/segments")
@limiter.limit("30/minute")
async def create_segment_route(request: Request, body: SegmentBody, db: Session = Depends(get_db),
                               current_user: dict = Depends(get_current_user)):
    """Declare a segment: who the buyer is, and what they call the problem."""
    user_id = str(current_user["sub"])
    fields = body.model_dump(exclude_unset=True)
    work_ids = fields.pop("work_ids", None)

    def handler(ctx):
        from apps.masterplan.services.market_service import create_segment
        return create_segment(db, user_id, fields, work_ids=work_ids)

    return await _run(request, "masterplan.market.seg.create", handler, db=db, user_id=user_id,
                      payload={**fields, "work_ids": work_ids})


@router.patch("/segments/{segment_id}")
@limiter.limit("30/minute")
async def update_segment_route(request: Request, segment_id: str, body: SegmentBody,
                               db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Edit a segment, or move its status. What it said before is kept."""
    user_id = str(current_user["sub"])
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "work_ids"}

    def handler(ctx):
        from apps.masterplan.services.market_service import update_segment
        return update_segment(db, user_id, segment_id, fields)

    return await _run(request, "masterplan.market.seg.update", handler, db=db, user_id=user_id,
                      payload={"segment_id": segment_id, **fields})


@router.delete("/segments/{segment_id}")
@limiter.limit("30/minute")
async def delete_segment_route(request: Request, segment_id: str, db: Session = Depends(get_db),
                               current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.market_service import delete_segment
        return delete_segment(db, user_id, segment_id)

    return await _run(request, "masterplan.market.seg.delete", handler, db=db, user_id=user_id,
                      payload={"segment_id": segment_id})


@router.put("/segments/{segment_id}/works")
@limiter.limit("30/minute")
async def set_segment_works_route(request: Request, segment_id: str, body: WorksBody,
                                  db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Which of your works serve this segment."""
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.market_service import set_segment_works
        return set_segment_works(db, user_id, segment_id, body.work_ids)

    return await _run(request, "masterplan.market.seg.works", handler, db=db, user_id=user_id,
                      payload={"segment_id": segment_id, "work_ids": body.work_ids})


@router.post("/entities")
@limiter.limit("30/minute")
async def create_entity_route(request: Request, body: EntityBody, db: Session = Depends(get_db),
                              current_user: dict = Depends(get_current_user)):
    """Add an alternative, channel, intermediary, voice or exemplar."""
    user_id = str(current_user["sub"])
    fields = body.model_dump()

    def handler(ctx):
        from apps.masterplan.services.market_service import create_entity
        return create_entity(db, user_id, fields)

    return await _run(request, "masterplan.market.ent.create", handler, db=db, user_id=user_id, payload=fields)


@router.delete("/entities/{entity_id}")
@limiter.limit("30/minute")
async def delete_entity_route(request: Request, entity_id: str, db: Session = Depends(get_db),
                              current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["sub"])

    def handler(ctx):
        from apps.masterplan.services.market_service import delete_entity
        return delete_entity(db, user_id, entity_id)

    return await _run(request, "masterplan.market.ent.delete", handler, db=db, user_id=user_id,
                      payload={"entity_id": entity_id})


@router.post("/evidence")
@limiter.limit("30/minute")
async def add_evidence_route(request: Request, body: EvidenceBody, db: Session = Depends(get_db),
                             current_user: dict = Depends(get_current_user)):
    """Record why you believe, or doubt, a segment or a market entry."""
    user_id = str(current_user["sub"])
    fields = body.model_dump()

    def handler(ctx):
        from apps.masterplan.services.market_service import add_evidence
        return add_evidence(db, user_id, source_kind="owner", **fields)

    return await _run(request, "masterplan.market.evidence", handler, db=db, user_id=user_id, payload=fields)
