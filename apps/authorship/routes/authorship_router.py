# /routers/authorship_router.py
"""
A.I.N.D.Y. Authorship Router
----------------------------
API interface for the Epistemic Reclaimer (Authorship Integrity Layer).
Allows users and collaborators to upload text and receive a
reclaimed, watermarked version with a visible + invisible authorship signature.
"""

# /routes/authorship_router.py
from fastapi import APIRouter, Depends, Request
from AINDY.core.execution_helper import execute_with_pipeline_sync
from AINDY.db.database import get_db
from sqlalchemy.orm import Session
from apps.authorship.services.authorship_services import reclaim_authorship
from AINDY.services.auth_service import get_current_user
from AINDY.platform_layer.rate_limiter import limiter


router = APIRouter(prefix="/authorship", tags=["Authorship"], dependencies=[Depends(get_current_user)])


def _execute_authorship(request: Request, route_name: str, handler, *, db: Session, user_id: str):
    # The session goes in `metadata["db"]`: without it the pipeline records no
    # execution.started/completed and attaches no execution unit (ROUTE-PIPELINE-NO-SESSION-1).
    return execute_with_pipeline_sync(
        request=request, route_name=route_name, handler=handler, user_id=user_id, metadata={"db": db}
    )


@router.post("/reclaim")
@limiter.limit("30/minute")
def reclaim_authorship_endpoint(
    request: Request,
    content: str,
    author: str = "Last name, First name",
    motto: str = "Yourmottohere",
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Reclaim authorship for provided text.
    Returns semantically watermarked text and fingerprint metadata.
    """
    def handler(_ctx):
        return reclaim_authorship(content, author, motto)
    return _execute_authorship(request, "authorship.reclaim", handler, db=db, user_id=str(current_user["sub"]))


