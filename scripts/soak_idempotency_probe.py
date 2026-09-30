"""Soak register row 2 probe: FR-27 strict idempotency under real contention, on this stack's Postgres.

Mirrors aindy-runtime's tests/integration/test_soak_idempotency_contention.py. A throwaway
EXACTLY_ONCE syscall counts its own handler runs; WORKERS threads, released together by a barrier,
dispatch it with the SAME payload and execution-unit id. Three phases:

  A  gate off                 -> WORKERS runs   (liveness: the burst is really concurrent)
  B  gate on, strict off      -> >1 runs likely (today's behaviour: the loser degrades)
  C  gate on, strict on       -> 1 run, the rest replayed (row 2's claim)

Nothing real is touched: the probe's only writes are its own effect_records rows, deleted at the end.

Run inside the api container, against the live database (PYTHONPATH so the repo's code is used):
    docker cp scripts/soak_idempotency_probe.py <api>:/tmp/ &&
    docker exec -e PYTHONPATH=/app <api> python /tmp/soak_idempotency_probe.py
First run 2026-09-30 (RUNTIME_2_24_0_UPGRADE.md §9): A 8/8, B 8/8 with 35 degraded, C 1/1 with 35 replayed.
"""
import os
import threading
import uuid
from unittest.mock import patch

import AINDY.main  # noqa: F401  (full model graph, as the api has it)
from AINDY.kernel import syscall_dispatcher as D
from AINDY.kernel import syscall_registry as R
from AINDY.platform_layer.metrics import effect_gate_outcomes_total

WORKERS = 8
ROUNDS = 5


class _OkRm:
    def check_quota(self, _x):
        return True, None

    def record_usage(self, _x, _u):
        return None


def gate_counts() -> dict:
    out = {}
    for metric in effect_gate_outcomes_total.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total"):
                out[sample.labels["outcome"]] = sample.value
    return out


def burst(name: str, runs: list) -> tuple[int, list]:
    eu_id = str(uuid.uuid4())
    payload = {"probe": eu_id}
    barrier = threading.Barrier(WORKERS)
    errors: list = []
    before = len(runs)

    def one():
        dispatcher = D.SyscallDispatcher()
        dispatcher._emit_syscall_event = lambda *a, **kw: None
        ctx = R.SyscallContext(execution_unit_id=eu_id, user_id=str(uuid.uuid4()),
                               capabilities=["test.soak"], trace_id="soak-row2")
        barrier.wait()
        with patch.object(D, "_get_rm", lambda: _OkRm()):
            result = dispatcher.dispatch(name, payload, ctx)
        if result.get("status") != "success":
            errors.append(result.get("error"))

    threads = [threading.Thread(target=one) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return len(runs) - before, errors


def phase(label: str, gate: str, strict: str) -> None:
    os.environ["AINDY_SYSCALL_IDEMPOTENCY"] = gate
    os.environ["AINDY_SYSCALL_IDEMPOTENCY_STRICT"] = strict
    runs: list = []

    def handler(payload, ctx):
        runs.append(1)
        import time
        time.sleep(0.2)  # a handler slow enough that the burst overlaps it
        return {"ran": len(runs)}

    name = f"sys.v1.test.soak_{uuid.uuid4().hex[:8]}"
    R.SYSCALL_REGISTRY[name] = R.SyscallEntry(handler=handler, capability="test.soak",
                                              execution_guarantee="EXACTLY_ONCE")
    before = gate_counts()
    per_round = []
    all_errors = []
    for _ in range(ROUNDS):
        n, errors = burst(name, runs)
        per_round.append(n)
        all_errors.extend(errors)
    after = gate_counts()
    delta = {k: int(after.get(k, 0) - before.get(k, 0)) for k in sorted(set(after) | set(before))
             if after.get(k, 0) != before.get(k, 0)}
    print(f"{label}: handler runs per {WORKERS}-way burst = {per_round}; gate outcomes {delta}; "
          f"errors {len(all_errors)}{' ' + str(all_errors[:2]) if all_errors else ''}")


phase("A gate off           ", "false", "")
phase("B gate on, strict off", "true", "")
phase("C gate on, strict on ", "true", "1")

from sqlalchemy import text  # noqa: E402

from AINDY.db.database import SessionLocal  # noqa: E402

db = SessionLocal()
deleted = db.execute(text("delete from effect_records where action_type like 'sys.v1.test.soak_%'")).rowcount
db.commit()
db.close()
print(f"cleanup: {deleted} probe effect_records rows deleted")
