"""Soak register row 4: agent runs are declared continuation-safe, but never while outreach really sends.

`AINDY_DURABLE_CONTINUATION` continues only agent types the app declares safe. A continued run
re-runs the step in flight at the crash; with `AINDY_SEARCH_OUTREACH_SEND` on, that step could
be an email (owner, 2026-10-14).
"""
from __future__ import annotations

import pathlib

import pytest

from apps.agent import bootstrap

pytestmark = pytest.mark.app_profile


@pytest.fixture
def declared(monkeypatch):
    from AINDY.core import agent_continuation

    monkeypatch.setattr(agent_continuation, "CONTINUATION_SAFE_AGENT_TYPES", set())
    return agent_continuation


def test_our_agent_type_is_declared_safe_while_outreach_does_not_send(declared, monkeypatch):
    monkeypatch.delenv("AINDY_SEARCH_OUTREACH_SEND", raising=False)
    bootstrap._declare_continuation_safety()
    assert declared.is_agent_type_continuation_safe("default")


@pytest.mark.parametrize("value", ["1", "true", "ON"])
def test_it_is_not_declared_when_outreach_really_sends(declared, monkeypatch, value):
    monkeypatch.setenv("AINDY_SEARCH_OUTREACH_SEND", value)
    bootstrap._declare_continuation_safety()
    assert not declared.is_agent_type_continuation_safe("default")


def test_the_flag_is_wired_with_a_boolean_default():
    """A typed pydantic bool: an empty string crash-loops the container at bootstrap-schema."""
    compose = (pathlib.Path(__file__).resolve().parents[2] / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert 'AINDY_DURABLE_CONTINUATION: "${AINDY_DURABLE_CONTINUATION:-false}"' in compose
