"""What a plain `docker compose up` on a new host depends on (OFF_LAPTOP_DEPLOYMENT_SPEC phase B).

- Redis runs without a profile. The api's environment sets REDIS_URL unconditionally, and with redis behind
  `--profile full` the documented `up` answered 500 on every rate-limited route, `/health` included
  (COMPOSE-REDIS-URL-UNCONDITIONAL-1, closed 2026-11-25).
- The api's host binding is `AINDY_BIND_ADDR`, loopback by default: signup is open, so a port on every interface lets
  anyone on the network make an account (owner, 2026-11-07). A server sets it to its tailnet address.
- Everything else with a host port stays on loopback, literally: the mcp port (its public path is the tunnel) and
  mailpit's inbox (no login).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.app_profile

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"


def _services() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def test_redis_runs_whenever_the_api_names_it():
    services = _services()
    assert "redis://redis:" in services["api"]["environment"]["REDIS_URL"]
    assert "profiles" not in services["redis"], "REDIS_URL is unconditional, so redis must be too"
    for name in ("api", "mcp"):
        assert services[name]["depends_on"]["redis"] == {"condition": "service_healthy"}, name


def test_the_api_binds_to_a_setting_that_defaults_to_loopback():
    assert _services()["api"]["ports"] == ["${AINDY_BIND_ADDR:-127.0.0.1}:8000:8000"]


@pytest.mark.parametrize("service", ["mcp", "mailpit"])
def test_every_other_host_port_is_loopback(service):
    for port in _services()[service]["ports"]:
        assert port.startswith("127.0.0.1:"), (service, port)
