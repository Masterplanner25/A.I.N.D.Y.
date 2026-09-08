"""App-owned Claude/Anthropic planner backend.

Registered on the runtime's planner-backend registry as ``anthropic_chat`` (see
``apps/agent/agents/runtime_extensions.py``). This is pure app composition — the
runtime stays a pinned dependency; nothing here edits the runtime package.

It puts a real LLM in the agent's decision seat: given an objective and the
registered tool catalog, Claude produces the same structured plan the
deterministic ``runtime_local`` backend produces, so it drops straight into the
existing goal -> plan -> approve -> execute loop.

Design notes:
- The plan's ``args`` field is free-form per tool, which strict structured
  outputs (which require ``additionalProperties: false`` everywhere) cannot
  express. So we use **forced tool use** — a single ``submit_plan`` tool with a
  non-strict input schema and ``tool_choice`` pinned to it — and read the plan
  straight off the ``tool_use`` block. This guarantees the fixed top-level shape
  while leaving ``args`` open.
- ``anthropic`` is imported lazily so the app boots (and the backend registers)
  even when the SDK isn't installed; only *invoking* this backend needs it.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from AINDY.platform_layer.llm_client import LLMCallError

logger = logging.getLogger(__name__)

# Default to the latest, most capable Claude model. Override with
# AINDY_CLAUDE_PLANNER_MODEL (e.g. "claude-sonnet-4-6" for lower cost).
DEFAULT_PLANNER_MODEL = "claude-opus-4-8"
_RISK_LEVELS = ["low", "medium", "high"]


class AnthropicPlannerError(RuntimeError):
    """Raised when the Claude planner backend cannot produce a plan.

    The runtime's ``generate_plan`` catches all backend exceptions and records a
    plan-generation failure, so raising here fails the run cleanly rather than
    crashing the request.
    """


def _planner_model() -> str:
    return (os.environ.get("AINDY_CLAUDE_PLANNER_MODEL") or DEFAULT_PLANNER_MODEL).strip()


def _make_client():
    """Return the runtime's Anthropic client through the LLM seam.

    ★ Was `anthropic.Anthropic()` — a raw SDK client the runtime could not see. Routing
    through `get_llm_client` buys two things this planner had neither of:

    * **Token metering.** `anthropic_client.messages_create` calls `observe_llm_usage`, so a
      plan generated here now lands in `aindy_llm_tokens_total`. The planner is the most
      expensive LLM call this app makes and it was the only one costing nothing on paper.
    * **The circuit breaker.** `get_llm_client` returns a breaker-wrapped client, so a provider
      outage stops the planner instead of being retried per request.

    `call_method("messages_create", ...)` rather than the seam's `chat()`: `chat()` returns a
    string and would discard the `tool_use` block, and the forced tool call IS the mechanism
    that guarantees the plan's shape (see the module docstring). `call_method` passes
    `tools`/`tool_choice` through untouched.

    Still isolated for test monkeypatching, and still checks the key here so a missing
    `ANTHROPIC_API_KEY` fails with a sentence rather than a provider error.
    """
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        detail = "ANTHROPIC_API_KEY is not set; cannot use the anthropic_chat planner backend."
        logger.error("[AnthropicPlanner] %s", detail)
        raise AnthropicPlannerError(detail)

    from AINDY.platform_layer.llm_client import get_llm_client

    try:
        return get_llm_client("anthropic")
    except Exception as exc:  # pragma: no cover - exercised when the SDK is absent
        detail = (
            "Could not build the Anthropic client; the 'anthropic' SDK may not be installed. "
            f"({type(exc).__name__}: {exc})"
        )
        logger.error("[AnthropicPlanner] %s", detail)
        raise AnthropicPlannerError(detail) from exc


def _plan_tool(tool_names: list[str]) -> dict[str, Any]:
    """Build the forced-tool schema, constraining step tools to the catalog."""
    return {
        "name": "submit_plan",
        "description": (
            "Return the structured execution plan for the user's objective. "
            "Use only the tools listed in the system prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "executive_summary": {
                    "type": "string",
                    "description": "2-3 sentence summary of what the agent will do.",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string", "enum": tool_names},
                            # Free-form, tool-specific arguments.
                            "args": {"type": "object"},
                            "risk_level": {"type": "string", "enum": _RISK_LEVELS},
                            "description": {
                                "type": "string",
                                "description": "One sentence explaining this step.",
                            },
                        },
                        "required": ["tool", "args", "risk_level", "description"],
                    },
                },
                "overall_risk": {"type": "string", "enum": _RISK_LEVELS},
            },
            "required": ["executive_summary", "steps", "overall_risk"],
        },
    }


def claude_planner_backend(request) -> dict[str, Any]:
    """Planner backend that drives Claude to emit a structured plan.

    ``request`` is the runtime's ``PlannerRequest`` (duck-typed here): it carries
    ``.objective``, ``.system_prompt`` (already includes the tool catalog and
    KPI/memory context), and ``.tools`` (the registered tool dicts).
    """
    logger.warning(
        "[AnthropicPlanner] backend invoked (objective=%r, tools=%d)",
        getattr(request, "objective", None),
        len(request.tools or ()),
    )
    tool_names = sorted(
        {
            t["name"]
            for t in (request.tools or ())
            if isinstance(t, dict) and t.get("name")
        }
    )
    if not tool_names:
        raise AnthropicPlannerError(
            "Anthropic planner backend requires at least one registered tool."
        )

    client = _make_client()
    model = _planner_model()
    try:
        message = client.call_method(
            "messages_create",
            model=model,
            max_tokens=4096,
            system=request.system_prompt or "",
            tools=[_plan_tool(tool_names)],
            tool_choice={"type": "tool", "name": "submit_plan"},
            messages=[{"role": "user", "content": f"Objective: {request.objective}"}],
        )
    except Exception as exc:  # surface the real cause — the runtime wraps this in a generic 500
        import anthropic

        # ★ Read through the seam's wrapper. `CircuitBreakerLLMClient` raises
        # `LLMCallError(...) from exc`, so `exc` is no longer the SDK error — without this the
        # isinstance branches below would all miss and every provider failure would collapse
        # into the generic message, losing the status code, error type and request id at
        # exactly the moment an incident needs them.
        exc = exc.__cause__ if isinstance(exc, LLMCallError) and exc.__cause__ else exc

        if isinstance(exc, anthropic.APIStatusError):
            detail = (
                f"Anthropic API {exc.status_code} ({getattr(exc, 'type', None)}) "
                f"for model {model!r}: {exc.message} "
                f"[request_id={getattr(exc, 'request_id', None) or getattr(exc, '_request_id', None)}]"
            )
        elif isinstance(exc, anthropic.APIConnectionError):
            detail = f"Anthropic API connection error for model {model!r}: {exc}"
        else:
            detail = f"Anthropic planner call failed for model {model!r}: {type(exc).__name__}: {exc}"
        logger.error("[AnthropicPlanner] %s", detail)
        raise AnthropicPlannerError(detail) from exc

    # Forced tool_choice should always emit the tool; a non-tool stop means the
    # model refused or the output was truncated — both surface as a missing plan.
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        detail = (
            f"Anthropic planner refused the request for model {model!r} "
            f"(stop_reason=refusal, stop_details={getattr(message, 'stop_details', None)})."
        )
        logger.error("[AnthropicPlanner] %s", detail)
        raise AnthropicPlannerError(detail)
    if stop_reason == "max_tokens":
        logger.warning(
            "[AnthropicPlanner] hit max_tokens for model %s — the plan tool_use may be truncated",
            model,
        )

    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_plan":
            plan = block.input
            if not isinstance(plan, dict):
                raise AnthropicPlannerError(
                    f"Anthropic planner returned {type(plan).__name__}, expected a dict."
                )
            logger.info(
                "[AnthropicPlanner] plan generated via %s (%d steps)",
                _planner_model(),
                len(plan.get("steps", []) or []),
            )
            return plan

    block_types = [getattr(b, "type", None) for b in message.content]
    detail = (
        f"Anthropic planner did not emit the submit_plan tool for model {model!r} "
        f"(stop_reason={stop_reason}, blocks={block_types})."
    )
    logger.error("[AnthropicPlanner] %s", detail)
    raise AnthropicPlannerError(detail)
