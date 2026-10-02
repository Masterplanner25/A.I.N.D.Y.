"""Task agent tool implementations."""

from __future__ import annotations

from AINDY.agents.tool_registry import register_tool

from apps._shared.tool_results import TOOL_RESULTS
from AINDY.agents.tool_syscalls import invoke_tool_syscall


def _dispatch_tool_syscall(syscall_name: str, args: dict, user_id: str, *, capability: str) -> dict:
    return invoke_tool_syscall(
        syscall_name,
        args,
        user_id=user_id,
        capability=capability,
    )


def register() -> None:
    register_tool(
        "task.create",
        result_schema=TOOL_RESULTS["task.create"],  # FR-48 (2.25.0): apps/_shared/tool_results.py
        risk="low",
        description="Create a new task in the user's task list. Returns {task_id, name, status}.",
        # FR-33 (runtime 2.20.0): the argument contract — see apps/arm/agents/tools.py.
        # `estimated_hours` carries no type on purpose: the dispatcher's "number" means
        # `float` only, and a planner writes `2` as readily as `2.0`.
        args_schema={
            "required": ["task_name"],
            "properties": {
                "task_name": {"type": "string"},
                "priority": {"type": "string"},
                "due_date": {"type": "string", "description": "ISO date"},
                "estimated_hours": {"description": "hours"},
                "category": {"type": "string"},
                "masterplan_id": {"type": "string"},
                "phase_id": {"type": "string"},
                "strategy_id": {"type": "string"},
            },
        },
        capability="tool:task.create",
        required_capability="manage_tasks",
        category="task",
        egress_scope="internal",
    )(task_create)
    register_tool(
        "task.complete",
        risk="medium",
        description=(
            "Mark a task as complete by its exact name. Its result is a status report: "
            "do not reference its fields from a later step."
        ),
        args_schema={
            "required": ["task_name"],
            "properties": {"task_name": {"type": "string", "description": "the exact task name"}},
        },
        capability="tool:task.complete",
        required_capability="manage_tasks",
        category="task",
        egress_scope="internal",
    )(task_complete)


def task_create(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall("sys.v1.task.create", args, user_id, capability="task.create")
    return {"task_id": data.get("task_id"), "name": data.get("task_name"), "status": data.get("status")}


def task_complete(args: dict, user_id: str, db) -> dict:
    return _dispatch_tool_syscall("sys.v1.task.complete_full", args, user_id, capability="task.complete_full")
