# /routers/task_router.py
import logging

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Request
from sqlalchemy.orm import Session
from AINDY.core.execution_gate import to_envelope
from AINDY.core.execution_helper import execute_with_pipeline_sync
from AINDY.core.system_event_service import emit_system_event
from AINDY.db.database import get_db
from AINDY.platform_layer.rate_limiter import limiter
from apps.tasks.schemas.task_schemas import TaskCreate, TaskAction
from AINDY.services.auth_service import get_current_user
from apps.tasks.events import TaskEventTypes as SystemEventTypes

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _execute_tasks(request: Request, route_name: str, handler, *, db: Session, user_id: str, input_payload=None):
    return execute_with_pipeline_sync(
        request=request,
        route_name=route_name,
        handler=handler,
        user_id=user_id,
        input_payload=input_payload or {},
        metadata={"db": db, "source": "task_router"},
    )


def _flow_envelope(result: dict) -> dict:
    """Embed execution_envelope into flow result data. Returns the data dict."""
    data = result.get("data")
    if not isinstance(data, dict):
        data = {} if data is None else {"result": data}
    data.setdefault("execution_envelope", to_envelope(
        eu_id=result.get("run_id"),
        trace_id=result.get("trace_id"),
        status=str(result.get("status") or "UNKNOWN").upper(),
        output=None,
        error=result.get("error"),
        duration_ms=None,
        attempt_count=None,
    ))
    return data


def _serialize_task(task) -> dict:
    return {
        "task_id": task.id,
        "task_name": task.name,
        "category": task.category,
        "priority": task.priority,
        "status": getattr(task, "status", "unknown"),
        "time_spent": task.time_spent,
        "masterplan_id": getattr(task, "masterplan_id", None),
        "parent_task_id": getattr(task, "parent_task_id", None),
        "depends_on": getattr(task, "depends_on", []) or [],
        "dependency_type": getattr(task, "dependency_type", "hard"),
        "automation_type": getattr(task, "automation_type", None),
        "automation_config": getattr(task, "automation_config", None),
    }

@router.post("/create")
@limiter.limit("30/minute")
def create_task(
    request: Request,
    task: TaskCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    _task_result: dict = {}

    def handler(_ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise(
            "task_create",
            {
                "task_name": task.name,
                "category": task.category,
                "priority": task.priority,
                "estimated_hours": task.estimated_hours,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "masterplan_id": task.masterplan_id,
                "parent_task_id": task.parent_task_id,
                "dependency_type": task.dependency_type,
                "dependencies": task.dependencies,
                "automation_type": task.automation_type,
                "automation_config": task.automation_config,
                "scheduled_time": task.scheduled_time.isoformat() if task.scheduled_time else None,
                "reminder_time": task.reminder_time.isoformat() if task.reminder_time else None,
                "recurrence": task.recurrence,
            },
            db=db,
            user_id=user_id,
        )
        data = result.get("data")
        if isinstance(data, dict):
            _task_result.update(data)
        return _flow_envelope(result)

    response = _execute_tasks(request, "tasks.create", handler, db=db, user_id=user_id, input_payload={"task_name": task.name})

    # TERMINAL — emitted after the pipeline so any internal rollback is already settled.
    # user_id intentionally omitted: the pipeline's FK errors can roll back the users
    # row in the test session, and the FK on system_events.user_id would fail.
    # The event is still fully observable via trace_id and payload.
    try:
        emit_system_event(
            db=db,
            event_type=SystemEventTypes.TASK_CREATED,
            user_id=user_id,
            payload={
                "operation": "create",
                "name": task.name,
                "user_id": user_id,
                "task_id": _task_result.get("task_id"),
            },
            source="task",
        )
    except Exception as _obs_exc:
        logger.warning("[task] system event emit failed (create): %s", _obs_exc)

    return response

@router.post("/start")
@limiter.limit("30/minute")
def start_task(
    request: Request,
    task: TaskAction,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    _not_found: list[bool] = []

    def handler(_ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise(
            "task_start",
            {"task_name": task.name},
            db=db,
            user_id=user_id,
        )
        # run_flow returns {"status": "SUCCESS", "data": {"message": "..."}, ...}
        data = result.get("data") if isinstance(result, dict) else None
        msg = data.get("message", "") if isinstance(data, dict) else ""
        if msg and "not found" in msg.lower():
            _not_found.append(True)
        return _flow_envelope(result)

    response = _execute_tasks(request, "tasks.start", handler, db=db, user_id=user_id, input_payload={"task_name": task.name})
    if _not_found:
        raise HTTPException(status_code=404, detail=f"Task '{task.name}' not found")
    return response

@router.post("/pause")
@limiter.limit("30/minute")
def pause_task(
    request: Request,
    task: TaskAction,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    def handler(_ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise(
            "task_pause",
            {"task_name": task.name},
            db=db,
            user_id=user_id,
        )
        return _flow_envelope(result)

    return _execute_tasks(request, "tasks.pause", handler, db=db, user_id=user_id, input_payload={"task_name": task.name})

@router.post("/complete")
@limiter.limit("30/minute")
def complete_task(
    request: Request,
    task: TaskAction,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])

    _not_found: list[bool] = []

    def handler(_ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise(
            "task_completion",
            {"task_name": task.name},
            db=db,
            user_id=user_id,
        )
        # run_flow returns {"status": "SUCCESS", "data": {"task_result": "...", ...}, ...}
        data = result.get("data") if isinstance(result, dict) else None
        task_result = data.get("task_result", "") if isinstance(data, dict) else ""
        if isinstance(task_result, str) and "not found" in task_result.lower():
            _not_found.append(True)
        return _flow_envelope(result)

    response = _execute_tasks(request, "tasks.complete", handler, db=db, user_id=user_id, input_payload={"task_name": task.name})
    if _not_found:
        raise HTTPException(status_code=404, detail=f"Task '{task.name}' not found")
    return response

@router.get("/list")
@limiter.limit("60/minute")
def list_tasks(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["sub"])
    def handler(_ctx):
        from apps.tasks.services.task_service import list_tasks
        tasks = list_tasks(db, user_id=current_user["sub"])
        return {
            "tasks": [_serialize_task(task) for task in tasks],
            "execution_envelope": to_envelope(
                eu_id=None, trace_id=None, status="SUCCESS",
                output=None, error=None, duration_ms=None, attempt_count=1,
            ),
        }
    return _execute_tasks(request, "tasks.list", handler, db=db, user_id=user_id)

@router.post("/delete")
@limiter.limit("30/minute")
def delete_task(
    request: Request,
    task: TaskAction,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete one of the caller's tasks by name.

    The capability already existed as `sys.v1.task.delete_by_ids` and
    `delete_tasks_by_ids`, reachable only from `masterplan_execution_service` — there was
    no HTTP route and no UI, so a task created by mistake could not be removed by the
    person who created it. (Two duplicates had to be deleted by hand on 2026-09-06.)

    Takes a NAME rather than an id because that is what every other verb on this router
    takes (`/start`, `/pause`, `/complete` all use `TaskAction`) and what the client
    already holds. The lookup is user-scoped, so a name resolves within the caller's own
    tasks only.

    404 rather than a silent success when nothing matched: `delete_tasks_by_ids` returns a
    count, and a 200 with `deleted_count: 0` would let the UI report a deletion that never
    happened. The 404 is raised *after* the pipeline returns — raising it inside the handler
    would be served as an opaque 500 (`PRE-PIPELINE-RAISE`).
    """
    user_id = str(current_user["sub"])
    # Closure flag rather than re-parsing the pipeline envelope on the way out — the same
    # pattern `/start` and `/complete` use for their 404s, and it does not depend on the
    # envelope's shape.
    _not_found: list[bool] = []

    def handler(_ctx):
        from AINDY.kernel.syscall_dispatcher import dispatch_syscall
        from apps.tasks.services.task_service import find_task

        target = find_task(db, task.name, user_id=user_id)
        if target is None:
            _not_found.append(True)
            return {"deleted_count": 0, "task_name": task.name}

        result = dispatch_syscall(
            "sys.v1.task.delete_by_ids",
            {"task_ids": [target.id], "user_id": user_id},
            db=db,
            user_id=user_id,
            capability="task.write",
        )
        # Lowercase syscall envelope, not the uppercase flow one — and since runtime
        # 2.9.0 a non-`success` may be `partial` or `unknown`, so test `!= "success"`
        # rather than `== "error"` (CLAUDE.md, run_flow vs syscall envelopes).
        if result.get("status") != "success":
            raise HTTPException(
                status_code=500,
                detail=result.get("error") or "task delete failed",
            )
        data = result.get("data") or {}
        return {
            "deleted_count": int(data.get("deleted_count") or 0),
            "task_name": task.name,
            "execution_envelope": to_envelope(
                eu_id=None, trace_id=None, status="SUCCESS",
                output=None, error=None, duration_ms=None, attempt_count=1,
            ),
        }

    response = _execute_tasks(
        request, "tasks.delete", handler, db=db, user_id=user_id,
        input_payload={"task_name": task.name},
    )
    # Raised outside the handler: a 404 raised *inside* would be served as an opaque
    # 500 internal_error — the pre-pipeline-raise shape now guarded against in CI.
    if _not_found:
        raise HTTPException(status_code=404, detail=f"Task '{task.name}' not found")
    return response


@router.post("/recurrence/check")
@limiter.limit("30/minute")
def trigger_recurrence(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Triggers the recurrence check job asynchronously."""
    user_id = str(current_user["sub"])
    def handler(_ctx):
        from apps._shared.flow import run_flow_or_raise
        result = run_flow_or_raise("tasks_recurrence_check", {}, db=db, user_id=user_id)
        return _flow_envelope(result)
    return _execute_tasks(request, "tasks.recurrence.check", handler, db=db, user_id=user_id)



