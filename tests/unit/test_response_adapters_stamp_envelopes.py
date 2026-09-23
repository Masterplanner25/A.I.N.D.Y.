"""Every response adapter we register marks an envelope body, and only an envelope body.

`@aindy/ui-kit` 2.1.0 (FR-37) resolves a response carrying `X-AINDY-Envelope` to `body.data` inside
`request()`, and once it has seen one stamped response it treats every UNSTAMPED body as final.
So an envelope served without the header is unwrapped or not depending on which page loaded
first, and a bare body served WITH it is replaced by its `data` key (or `null`). The runtime only
stamps its default exit; a route answered by a registered adapter is stamped only if we stamp it
(`apps/_shared/envelope.py`). Found 2026-09-23: 54 envelope-bodied route names, none marked.

The invariant, checked for every adapter every app registers: a success body that carries
`data` is stamped; a body without it is not.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.app_profile

ROOT = Path(__file__).resolve().parents[2]

CANONICAL = {
    "status": "success",
    "data": {"value": 1},
    "trace_id": "trace-1",
    "eu_id": "eu-1",
    "duration_ms": 1.0,
    "memory_context_count": 0,
    "metadata": {"events": [], "next_action": None},
}


def _registered_adapters(monkeypatch) -> dict[str, object]:
    from AINDY.platform_layer import registry

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        registry, "register_response_adapter", lambda prefix, handler: captured.__setitem__(prefix, handler)
    )
    for bootstrap in sorted((ROOT / "apps").glob("*/bootstrap.py")):
        module = importlib.import_module(f"apps.{bootstrap.parent.name}.bootstrap")
        register = getattr(module, "_register_response_adapters", None)
        if register is not None:
            register()
    return captured


def test_the_scan_sees_our_adapters(monkeypatch):
    adapters = _registered_adapters(monkeypatch)
    # analytics / main / arm / autonomy x3 / social x2 / memory x4 at least
    assert len(adapters) >= 13, sorted(adapters)
    assert {"analytics", "arm", "social", "social.feed.get", "memory.execute"} <= set(adapters)


def test_an_envelope_body_is_stamped_and_a_bare_body_is_not(monkeypatch):
    wrong = []
    for prefix, adapter in sorted(_registered_adapters(monkeypatch).items()):
        response = adapter(
            route_name=prefix, canonical=dict(CANONICAL), status_code=200, trace_headers={}
        )
        body = json.loads(response.body)
        enveloped = isinstance(body, dict) and "data" in body
        stamped = response.headers.get("X-AINDY-Envelope") == "v1"
        if enveloped != stamped:
            wrong.append(f"{prefix}: body has data={enveloped}, stamped={stamped}")
    assert not wrong, (
        "Adapters whose header disagrees with their body (wrap envelope adapters in "
        "apps._shared.envelope.stamped; never wrap a bare-JSON adapter):\n" + "\n".join(wrong)
    )


def test_an_error_response_is_not_stamped():
    from AINDY.platform_layer.response_adapters import raw_canonical_adapter

    from apps._shared.envelope import stamped

    response = stamped(raw_canonical_adapter)(
        route_name="x", canonical=dict(CANONICAL), status_code=422, trace_headers={}
    )
    assert "X-AINDY-Envelope" not in response.headers
