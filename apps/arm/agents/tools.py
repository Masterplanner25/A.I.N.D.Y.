"""ARM agent tool implementations."""

from __future__ import annotations

from AINDY.agents.tool_registry import register_tool
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
        "arm.analyze",
        risk="medium",
        description=(
            "Analyze ONE SOURCE FILE with the ARM code-reasoning engine (architecture and "
            "integrity scores plus a summary). It cannot analyze a topic, a memory, or prior "
            "step output — only a file path under the project root."
        ),
        # FR-33 (runtime 2.20.0): the argument contract, rendered into the planner catalog as
        # `args={…}` and checked before dispatch under AINDY_TOOL_ARGS_VALIDATION. Types are
        # the dispatcher's dialect (`syscall_versioning._SCHEMA_TYPE_MAP`); `description` on a
        # property is for the planner, the validator ignores it.
        args_schema={
            "required": ["file_path"],
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "path to a .py/.js/.ts/.md/.json/.yaml file under the project root; NOT a topic",
                },
                "additional_context": {"type": "string"},
            },
        },
        capability="tool:arm.analyze",
        required_capability="external_api_call",
        category="analysis",
        egress_scope="external_llm",
    )(arm_analyze)
    register_tool(
        "arm.generate",
        risk="medium",
        description="Generate or refactor code with the ARM code-generation engine.",
        args_schema={
            "required": ["prompt"],
            "properties": {
                "prompt": {"type": "string"},
                "language": {"type": "string", "description": "default python"},
                "generation_type": {"type": "string", "description": "default generate"},
                "original_code": {"type": "string"},
                "analysis_id": {"type": "string"},
            },
        },
        capability="tool:arm.generate",
        required_capability="external_api_call",
        category="analysis",
        egress_scope="external_llm",
    )(arm_generate)
    register_tool(
        "arm.autotune",
        risk="low",
        description=(
            "Apply gated, reversible self-tuning config changes from ARM's own metrics. "
            "Dry run unless apply=true."
        ),
        args_schema={
            "required": [],
            "properties": {
                "apply": {"type": "boolean", "description": "default false (dry run)"},
                "window": {"type": "integer", "description": "days, default 30"},
            },
        },
        capability="tool:arm.autotune",
        required_capability="self_tune",
        category="optimization",
        egress_scope="none",
    )(arm_autotune)


def arm_analyze(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall("sys.v1.arm.analyze", args, user_id, capability="arm.analyze")
    return {
        "summary": data.get("summary", ""),
        "architecture_score": data.get("architecture_score"),
        "integrity_score": data.get("integrity_score"),
        "analysis_id": data.get("analysis_id"),
    }


def arm_generate(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall("sys.v1.arm.generate", args, user_id, capability="arm.generate")
    return {
        "generated_code": data.get("generated_code", ""),
        "explanation": data.get("explanation", ""),
        "generation_id": data.get("generation_id"),
    }


def arm_autotune(args: dict, user_id: str, db) -> dict:
    data = _dispatch_tool_syscall("sys.v1.arm.autotune", args, user_id, capability="arm.self_tune")
    return {
        "status": data.get("status"),
        "applied": data.get("applied", []),
        "skipped": data.get("skipped", []),
        "log_id": data.get("log_id"),
        "dry_run": data.get("dry_run", False),
    }
