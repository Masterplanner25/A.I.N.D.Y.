"""Freelance agent tool implementations.

Makes the freelance domain agent-invocable (register_tool) — Phase 2 of the
freelancing evolution. Both tools dispatch to existing freelance syscalls; neither
has external egress. The act tool (pricing optimization) is safe by construction:
gated + bounded + revertible, dry-run unless ``apply=true``, and it only ever writes
the studio's internal default price (never an existing order or a customer charge).
"""

from __future__ import annotations

from AINDY.agents.tool_registry import register_tool
from AINDY.agents.tool_syscalls import invoke_tool_syscall


def _dispatch_tool_syscall(syscall_name: str, args: dict, user_id: str, *, capability: str) -> dict:
    return invoke_tool_syscall(syscall_name, args, user_id=user_id, capability=capability)


def register() -> None:
    register_tool(
        "freelance.optimize_pricing",
        risk="medium",
        description=(
            "Recommend (or apply) gated, revertible service-price adjustments from realized "
            "outcomes (paid revenue, acceptance, refunds, ratings). Dry run unless apply=true; "
            "applying writes an internal default price for future quotes only — it never "
            "changes an existing order or charges a customer."
        ),
        # FR-33 (runtime 2.20.0): the argument contract — see apps/arm/agents/tools.py.
        args_schema={
            "required": [],
            "properties": {"apply": {"type": "boolean", "description": "default false (dry run)"}},
        },
        capability="tool:freelance.optimize_pricing",
        required_capability="revenue_optimize",
        category="optimization",
        egress_scope="none",
    )(freelance_optimize_pricing)
    register_tool(
        "freelance.performance",
        risk="low",
        description="Read recent realized-revenue performance signals for the current user. Read-only.",
        args_schema={
            "required": [],
            "properties": {"limit": {"type": "integer", "description": "default 3"}},
        },
        capability="tool:freelance.performance",
        required_capability="revenue_read",
        category="revenue",
        egress_scope="none",
    )(freelance_performance)


def freelance_optimize_pricing(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall(
        "sys.v1.freelance.optimize_pricing", args, user_id, capability="freelance.optimize"
    )
    return {
        "status": data.get("status"),
        "applied": data.get("applied", []),
        "recommendations": data.get("recommendations", []),
        "skipped": data.get("skipped", []),
        "dry_run": data.get("dry_run", False),
        "would_change": data.get("would_change"),
    }


def freelance_performance(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall(
        "sys.v1.freelance.get_performance_signals", args, user_id, capability="freelance.read"
    )
    return {"signals": data.get("signals", []), "count": data.get("count", 0)}
