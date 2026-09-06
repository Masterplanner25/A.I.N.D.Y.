"""The task delete route must exist, be user-scoped, and 404 on a miss.

The delete capability shipped as a syscall (`sys.v1.task.delete_by_ids`) and a service
(`delete_tasks_by_ids`) with **no HTTP route and no UI** — reachable only from
`masterplan_execution_service`. A user could create a task but never remove one; two
duplicates had to be deleted directly from the database on 2026-09-06.

This guards the wiring end to end: the route is mounted where the client expects it, it
declares the `request: Request` slowapi needs, and a miss is a 404 rather than a 200 with
`deleted_count: 0` (which would let the UI report a deletion that never happened).
"""

from __future__ import annotations

import inspect
import os

import pytest
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

task_router_module = pytest.importorskip("apps.tasks.routes.task_router")


def _routes():
    return {
        (route.path, tuple(sorted(route.methods)))
        for route in task_router_module.router.routes
    }


def test_delete_route_is_mounted():
    """`/tasks/delete` must exist — the client resolves ROUTES.TASKS.DELETE to it."""
    paths = {path for path, _ in _routes()}
    assert "/tasks/delete" in paths, f"delete route missing; have: {sorted(paths)}"


def test_delete_route_is_post():
    """POST, matching /start /pause /complete — the client sends a JSON body."""
    assert ("/tasks/delete", ("POST",)) in _routes()


def test_delete_route_declares_request_for_the_rate_limiter():
    """slowapi looks up a parameter literally named `request` typed as starlette Request.

    Same class of bug as `test_rate_limited_route_request_param` guards elsewhere: get this
    wrong and every delete 500s.
    """
    sig = inspect.signature(task_router_module.delete_task)
    assert "request" in sig.parameters
    assert sig.parameters["request"].annotation is Request


def test_delete_route_takes_a_name_not_an_id():
    """Consistency with every other verb on this router, and what the client holds."""
    from apps.tasks.schemas.task_schemas import TaskAction

    sig = inspect.signature(task_router_module.delete_task)
    assert sig.parameters["task"].annotation is TaskAction


def test_delete_service_is_user_scoped():
    """The service must filter by user_id — a name lookup is not globally unique.

    Without this a caller could delete another user's task by guessing a name.
    """
    from apps.tasks.services import public_surface_service

    source = inspect.getsource(public_surface_service.delete_tasks_by_ids)
    assert "Task.user_id ==" in source
    assert "require_user_id(user_id)" in source


def test_delete_service_returns_zero_for_an_empty_id_list():
    """Guards the early return that keeps an empty request from deleting nothing loudly."""
    from apps.tasks.services.public_surface_service import delete_tasks_by_ids

    assert delete_tasks_by_ids(None, user_id="irrelevant", task_ids=[]) == 0
