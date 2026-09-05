from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from AINDY.core.execution_helper import execute_with_pipeline_sync
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from AINDY.services.auth_service import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Health Dashboard"], dependencies=[Depends(get_current_user)])


def _run_flow_health_dashboard(flow_name: str, payload: dict, db: Session, user_id: str):
    from apps._shared.flow import run_flow_data

    return run_flow_data(flow_name, payload, db=db, user_id=user_id)


def _execute_health_dashboard(request: Request, route_name: str, handler, *, db: Session, user_id: str):
    return execute_with_pipeline_sync(
        request=request,
        route_name=route_name,
        handler=handler,
        user_id=user_id,
        metadata={"db": db, "source": "health_dashboard_router"},
    )


@router.get("/health")
@limiter.limit("60/minute")
def get_health_logs(
    request: Request,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns the latest system health logs for dashboard visualization.
    """
    user_id = str(current_user["sub"])
    def handler(_ctx):
        return _run_flow_health_dashboard("health_dashboard_list", {"limit": limit}, db, user_id)
    return _execute_health_dashboard(request, "dashboard.health", handler, db=db, user_id=user_id)

