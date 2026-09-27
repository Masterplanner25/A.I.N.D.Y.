"""Agent flags set in .env must be declared on the api service, or they never reach the process.

Compose reads .env for interpolation only. The shadow flags were lost that way (see the comment in
docker-compose.prod.yml), and on 2026-09-26 AINDY_PLAN_STEP_REFERENCES and
AINDY_TOOL_ARGS_VALIDATION would have been too, had they not been wired by hand.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.app_profile

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"


@pytest.mark.parametrize("flag", ["AINDY_PLAN_STEP_REFERENCES", "AINDY_TOOL_ARGS_VALIDATION", "AINDY_AUTHORITY_NEGOTIATION"])
def test_the_flag_is_passed_to_the_api(flag):
    assert f'{flag}: "${{{flag}:-}}"' in COMPOSE.read_text(encoding="utf-8")
