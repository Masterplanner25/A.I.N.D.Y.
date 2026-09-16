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
            "integrity scores plus a summary). Args: {file_path: str (required — a path to a "
            ".py/.js/.ts/.md/.json/.yaml file under the project root; NOT a topic or free text), "
            "additional_context?: str}. It cannot analyze a topic, a memory, or prior step output."
        ),
        capability="tool:arm.analyze",
        required_capability="external_api_call",
        category="analysis",
        egress_scope="external_llm",
    )(arm_analyze)
    register_tool(
        "arm.generate",
        risk="medium",
        description=(
            "Generate or refactor code with the ARM code-generation engine. "
            "Args: {prompt: str (required), language?: str, generation_type?: str, "
            "original_code?: str, analysis_id?: str}."
        ),
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
            "Args: {apply?: bool (default false — dry run), window?: int days (default 30)}."
        ),
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
