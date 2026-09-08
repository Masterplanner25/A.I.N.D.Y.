"""Unit tests for the app-owned Claude planner backend.

These mock the Anthropic client — no network, no API key. A live Claude call is
verified on Linux CI (this stack's authoritative oracle), not locally.
"""
from __future__ import annotations

import types

import httpx
import pytest

from apps.agent.agents import planner_anthropic as pa

pytestmark = [pytest.mark.app_profile]


def _fake_message(plan: dict):
    """Build a fake Anthropic Message whose content carries a submit_plan tool_use."""
    tool_block = types.SimpleNamespace(type="tool_use", name="submit_plan", input=plan)
    return types.SimpleNamespace(content=[tool_block])


class _FakeClient:
    """Mirrors the runtime's `LLMClient`, not the raw Anthropic SDK.

    ★ The planner goes through `get_llm_client("anthropic").call_method("messages_create", …)`
    since 2026-09-07, so a fake shaped like `client.messages.create` would pass while testing
    an interface the code no longer uses. `call_method` is also what carries `tools` and
    `tool_choice` through untouched — the seam's `chat()` returns a string and would discard
    the `tool_use` block the forced tool call exists to produce.
    """

    def __init__(self, message, capture: dict):
        self._message = message
        self._capture = capture

    def call_method(self, method_name: str, **kwargs):
        assert method_name == "messages_create", method_name
        self._capture.update(kwargs)
        return self._message


def _request(objective="Recall my priorities", tools=None, system_prompt="SYS"):
    from AINDY.agents.agent_runtime.planner_backends import PlannerRequest

    return PlannerRequest(
        objective=objective,
        run_type="default",
        user_id=None,
        system_prompt=system_prompt,
        tools=tuple(tools if tools is not None else [{"name": "memory.recall"}, {"name": "task.create"}]),
    )


def test_backend_parses_forced_tool_plan(monkeypatch):
    plan = {
        "executive_summary": "Recall priorities.",
        "steps": [{"tool": "memory.recall", "args": {"query": "priorities"},
                   "risk_level": "low", "description": "Recall."}],
        "overall_risk": "low",
    }
    capture: dict = {}
    monkeypatch.setattr(pa, "_make_client", lambda: _FakeClient(_fake_message(plan), capture))

    result = pa.claude_planner_backend(_request())

    assert result == plan
    # tool_choice is pinned to submit_plan; step tools are constrained to the catalog.
    assert capture["tool_choice"] == {"type": "tool", "name": "submit_plan"}
    enum = capture["tools"][0]["input_schema"]["properties"]["steps"]["items"]["properties"]["tool"]["enum"]
    assert set(enum) == {"memory.recall", "task.create"}
    assert capture["system"] == "SYS"


def test_backend_uses_default_model(monkeypatch):
    capture: dict = {}
    monkeypatch.delenv("AINDY_CLAUDE_PLANNER_MODEL", raising=False)
    monkeypatch.setattr(pa, "_make_client", lambda: _FakeClient(_fake_message({"steps": []}), capture))
    pa.claude_planner_backend(_request())
    assert capture["model"] == "claude-opus-4-8"


def test_backend_honors_model_override(monkeypatch):
    capture: dict = {}
    monkeypatch.setenv("AINDY_CLAUDE_PLANNER_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(pa, "_make_client", lambda: _FakeClient(_fake_message({"steps": []}), capture))
    pa.claude_planner_backend(_request())
    assert capture["model"] == "claude-sonnet-4-6"


def test_backend_requires_tools(monkeypatch):
    monkeypatch.setattr(pa, "_make_client", lambda: pytest.fail("client should not be built"))
    with pytest.raises(pa.AnthropicPlannerError):
        pa.claude_planner_backend(_request(tools=[]))


def test_backend_raises_when_no_tool_use_block(monkeypatch):
    empty = types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="nope")])
    monkeypatch.setattr(pa, "_make_client", lambda: _FakeClient(empty, {}))
    with pytest.raises(pa.AnthropicPlannerError):
        pa.claude_planner_backend(_request())


def test_backend_registers_as_anthropic_chat(client):
    """After app bootstrap, the backend is selectable by name."""
    from AINDY.platform_layer.registry import get_agent_planner_backend

    assert get_agent_planner_backend("anthropic_chat") is pa.claude_planner_backend


# ── the LLM seam ──────────────────────────────────────────────────────────────────────
#
# `docs/runtime/LLM_SEAM_ADOPTION_SCOPE.md` phase 1. The planner is the most expensive LLM
# call this app makes and it was the only one the runtime could not see: a raw
# `anthropic.Anthropic()` bypasses both the token meter and the circuit breaker.


def test_the_client_comes_from_the_runtime_seam(monkeypatch):
    """★ Not `anthropic.Anthropic()`.

    Routing through `get_llm_client` is what puts this call in `aindy_llm_tokens_total` —
    `anthropic_client.messages_create` calls `observe_llm_usage`, and the raw SDK path does
    not. It also wraps the call in the provider circuit breaker.
    """
    from AINDY.platform_layer import llm_client as seam

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    asked: list[str] = []
    monkeypatch.setattr(
        seam, "get_llm_client", lambda provider="openai": asked.append(provider) or object()
    )
    monkeypatch.setattr(pa, "_make_client", pa._make_client)  # keep the real one

    pa._make_client()

    assert asked == ["anthropic"]


def test_a_missing_key_still_fails_with_a_sentence(monkeypatch):
    """The key check stays in the app so the message names the variable to set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(pa.AnthropicPlannerError, match="ANTHROPIC_API_KEY"):
        pa._make_client()


def test_a_provider_error_survives_the_seams_wrapper(monkeypatch):
    """★ The failure this unwrap exists to prevent.

    `CircuitBreakerLLMClient` raises `LLMCallError(...) from exc`, so by the time the planner
    sees it the SDK error is one level down. Without reading `__cause__` every provider
    failure collapses into the generic message and the status code, error type and request id
    are lost — at exactly the moment an incident needs them.
    """
    import anthropic
    from AINDY.platform_layer.llm_client import LLMCallError

    sdk_error = anthropic.APIStatusError(
        "rate limited",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com")),
        body=None,
    )
    wrapped = LLMCallError("anthropic call failed")
    wrapped.__cause__ = sdk_error

    class _Failing:
        def call_method(self, *a, **k):
            raise wrapped

    monkeypatch.setattr(pa, "_make_client", lambda: _Failing())

    with pytest.raises(pa.AnthropicPlannerError) as caught:
        pa.claude_planner_backend(_request())

    detail = str(caught.value)
    assert "429" in detail, detail
    assert "planner call failed" not in detail, "collapsed into the generic message"


def test_a_bare_error_is_still_reported(monkeypatch):
    """The unwrap must not swallow errors that were never wrapped."""

    class _Failing:
        def call_method(self, *a, **k):
            raise RuntimeError("socket exploded")

    monkeypatch.setattr(pa, "_make_client", lambda: _Failing())

    with pytest.raises(pa.AnthropicPlannerError, match="socket exploded"):
        pa.claude_planner_backend(_request())
