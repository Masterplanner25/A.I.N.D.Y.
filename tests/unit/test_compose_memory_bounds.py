"""The api container's memory bounds are load-bearing and travel together.

Decided 2026-09-16 (runtime 2.19.0 handoff §3, `RUNTIME_2_19_0_UPGRADE.md` §4.1): the api gets a
hard `mem_limit` so a runaway (a guest script, a full warm pool) OOM-kills *this* container and
restarts it instead of pushing the Docker VM into a global OOM that takes postgres down — the
isolation mongo already has for the same reason (PR #234). `memswap_limit == mem_limit` is on
purpose: an API that swaps produces the "running, zero restarts, dead /health, no log output"
fingerprint. `AINDY_NODUS_MAX_MEMORY_MB` bounds one guest execution's growth and is polled, so the
runtime says to set it *with* a container cap, never alone.

Sizes are measured (cgroup peak 530 MiB over a life with boot + an agent run + a worker spawn;
~320 MiB api + ~225 MiB per warm worker, pool of 4). The floor below is the re-measure line from
the compose comment: dropping under it would risk the boot spike itself. Read with a small YAML
parse rather than regex so a reformat does not fool it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.app_profile

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.prod.yml"

MIB = 1024 * 1024


def _size_bytes(value: str | int) -> int:
    text = str(value).strip().lower()
    for suffix, mult in (("g", 1024 * MIB), ("m", MIB), ("k", 1024), ("b", 1)):
        if text.endswith(suffix):
            return int(float(text[:-1]) * mult)
    return int(text)


def _api() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["api"]


def test_api_has_a_hard_memory_limit_above_the_measured_floor():
    api = _api()
    assert "mem_limit" in api, "the api container must carry a mem_limit (see the compose comment)"
    limit = _size_bytes(api["mem_limit"])
    assert limit >= 1024 * MIB, (
        f"api mem_limit is {api['mem_limit']}; below ~1024m the boot spike (16-app graph imported "
        "twice) plus one warm worker is at risk — re-measure cgroup memory.peak before lowering"
    )


def test_api_swap_is_disabled_by_matching_memswap_limit():
    api = _api()
    assert "memswap_limit" in api, "without memswap_limit the container may swap up to 2x mem_limit"
    assert _size_bytes(api["memswap_limit"]) == _size_bytes(api["mem_limit"]), (
        "memswap_limit must equal mem_limit: a swapping API is the frozen-with-zero-restarts "
        "fingerprint, and a clean OOM kill is the better failure"
    )


def test_guest_memory_ceiling_is_set_and_below_the_container_cap():
    api = _api()
    env = api["environment"]
    raw = env.get("AINDY_NODUS_MAX_MEMORY_MB")
    assert raw, "AINDY_NODUS_MAX_MEMORY_MB must be declared on the api service (the guest ceiling)"
    # "${AINDY_NODUS_MAX_MEMORY_MB:-256}" — read the default out of the interpolation.
    default = raw.split(":-", 1)[1].rstrip("}").strip('"') if ":-" in raw else raw.strip('"')
    ceiling_mb = int(default)
    assert 0 < ceiling_mb * MIB < _size_bytes(api["mem_limit"]), (
        "the per-execution guest ceiling must sit under the container cap, or the cap fires first "
        "and the run's failure reads as an OOM kill instead of a sandbox error"
    )
