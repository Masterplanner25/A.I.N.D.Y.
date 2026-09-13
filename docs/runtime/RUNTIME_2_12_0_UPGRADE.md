---
title: "Runtime 2.12.0 upgrade — adoption"
last_verified: "2026-09-12"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.12.0 upgrade — adoption

Floor moved `>=2.11.0,<3.0` → `>=2.12.0,<3.0`; build pin `==2.11.0` → `==2.12.0`. Handoff:
`aindy-runtime/docs/runtime/APP_HANDOFF_v2.12.0.md`.

**No schema step, no required code change.** Verified rather than taken from the handoff:
runtime Alembic head unchanged at `0018`; `git diff v2.11.0 v2.12.0 -- AINDY/db/models
AINDY/memory/memory_persistence.py` is empty; the diff under `AINDY/` is 13 files, and of the
two on our registration surface, `platform_layer/registry.py` only *adds* (deprecation warnings
on two functions we do not call, plus `list_run_tool_provider_run_types`) and
`agents/tool_registry.py` only adds plugin-load failure reporting — `register_tool` is
byte-identical. Every `register_*` hook and syscall this repo depends on is intact.

This release is four fixes to things we filed (FR-23, FR-25, FR-26, FR-27) and nothing new to
wire. Three of them close on adoption; one ships behind a flag and stays off (§3).

---

## 1. ★ The handoff's opening box was right about this machine

The handoff opens by saying our 2.9.0 and 2.11.0 adoption checks ran their suites against a
stale **2.6.0** in the dev venv. Measured today before touching anything:

```
python -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
2.6.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']
```

A non-editable published `aindy_runtime-2.6.0.dist-info`, no `__editable__` link to the sibling
checkout. So `pytest` from this repo was importing 2.6.0, whatever the sibling checkout was
tagged. `RUNTIME_2_11_0_UPGRADE.md` §1 argued the opposite — that the venv was an editable
install with stale *metadata* and the *code* was current. Its `AINDY._version` number may have
come from an interpreter run in `C:\dev\aindy-runtime`, where the checkout shadows
site-packages; from this repo the answer is the one above. Either way the 2.11.0 doc's "1,222
passed" cannot be attributed to 2.11.0 with confidence, and this doc's numbers can.

**Fixed two ways:**

1. The venv now holds the published 2.12.0, installed the way CI does —
   `python -m pip install -e .[test] -c constraints.txt --no-build-isolation` — and the import
   check above answers `2.12.0` from `site-packages`.
2. `test_runtime_dependency_contract.py` gained
   `test_the_interpreter_runs_a_runtime_inside_the_declared_range` (handoff §5's suggestion):
   it asks `AINDY._version` — the interpreter, not two strings in two files — whether what
   actually imports satisfies the `pyproject` range. A venv below the floor now fails the suite
   on its first test instead of validating 1,200 tests against the wrong runtime. Range rather
   than exact pin, so a sibling checkout a few commits past the tag still passes; the failure
   being guarded is *below the floor*, which is the one that happened.

---

## 2. Closed on adoption — with the probe, not the handoff

| Item | Was | Now |
|---|---|---|
| **`TRACE-ID-DUAL-1` / FR-26** | body `trace_id` ≠ `X-Trace-ID` header on every enveloped `/apps/*` response; two event graphs | **equal.** New `tests/unit/test_trace_id_envelope_contract.py` asserts it; **fails on 2.11.0** (`header 0a938374…, body 5a5ddabb…`), passes on 2.12.0. The test stays so the next adoption re-measures instead of trusting the handoff |
| **FR-23** | `/observability/system` reported `syscall_count: 0, tool_count: 0` | counts `SYSCALL_REGISTRY` / `TOOL_REGISTRY`; adds `run_tool_provider_run_types`. **Verify in the container** (§5) — the route is platform-admin-gated and legacy-root-mounted, not reachable from the unit fixture. Expect the operator dashboard's numbers to jump from 0 to ~98 / 16: that is the fix |
| **FR-25 a+c** | 11 of 13 syscall error paths silent; Nodus worker plugin-load failure swallowed at DEBUG | dispatcher errors log once at WARNING with the message they already return; worker load failure is a WARNING naming the manifest. **New WARNING lines only where something was already failing** — `grep '\[syscall\]'` / `Permission denied` in the api log after a busy session is now `SYSCALL-SILENT-ERRORS-1`'s instrument |
| **FR-25 b** | malformed ids on runtime routes → 500 | 422 on `coordination`, `keys`, `admin/users/…/promote` via typed `path_params.py`. Same shape as our own `pre-pipeline-raise` guard, now on their side |

`SYSCALL_REGISTRY` at app-profile boot: **98** (unchanged from 2026-09-11's count in `CLAUDE.md`).
`TOOL_REGISTRY` still populated through `register_tool`; `get_tools_for_run('agent')` unaffected.

---

## 3. Not taken: `AINDY_SYSCALL_IDEMPOTENCY_STRICT` (FR-27) — shipped, off, and staying off for now

FR-27 asked for a Postgres advisory lock so a concurrent duplicate blocks and replays instead of
degrading and running the handler. 2.12.0 ships exactly that, **opt-in, default off, PostgreSQL
only.** With it off the gate behaves as measured on 2026-09-11: N−1 of N concurrent duplicates
run. So adoption does not by itself change the state `IDEMPOTENCY-CONTENTION-UNVERIFIED-1`
recorded; the app-side single-flight guards remain the protection that holds.

Why off, rather than on in `docker-compose.prod.yml`:

- **A blocked duplicate holds a pooled connection while it waits** (default 300 s). Our pool is
  `DB_POOL_SIZE=20` / `DB_MAX_OVERFLOW=40`. The 09-11 probe released 16 duplicates on a barrier;
  15 of them would hold a connection for the winner's whole handler. On a 7.7 GB host already
  inside the postgres-reinit band after builds (`POSTGRES-CRASH-RESIDUAL-1`), that is a new way
  to exhaust the pool under exactly the load that produces duplicates.
- **The paths that actually produce duplicates here are already single-flighted app-side**
  (`task_orchestrate`'s repeat check, the task screen's in-flight set). The flag buys
  correctness for the *unguarded* path we have not found yet, at a connection cost on every
  duplicate we already prevent.
- **It is not exactly-once across a winner crash** (stated in the handoff, not built). So it
  does not retire the app-side guards even when on.

**To flip it:** set `AINDY_SYSCALL_IDEMPOTENCY_STRICT=1` on the api service, size
`DB_POOL_SIZE` for the expected duplicate fan-in, re-run the 09-11 probe (N barrier-released
`sys.v1.event.emit` calls, expect `reserved 1, replayed N−1, rows written 1`), and watch
`aindy_effect_gate_outcomes_total{outcome="degraded_lock_timeout"}` — non-zero means a handler is
slower than the wait. Same soak-then-flip discipline as `SOAK-THEN-FLIP-1`. Note the metric's
`degraded` label now means "lock not attempted" (non-PG or flag off), not "lost the race".

---

## 4. Checked and irrelevant to us — handoff §3, verified against our source

- **Deprecated ABI functions** — `platform_layer.register_syscall` and `register_agent_tool` now
  warn. `grep` across `apps/` for either import: empty. We register through
  `AINDY.agents.tool_registry.register_tool` (`apps/agent/agents/tools.py`) and the kernel
  `syscall_registry.register_syscall` (15 modules). Boot under
  `warnings.simplefilter("always")` raised **0** deprecation warnings from either name.
- **`POST /coordination/messages/{id}/acknowledge` tightened** (404 unknown, 403 another agent's,
  422 bad id). No caller in `apps/` or `client/`.
- **Client-side `X-Trace-ID` workaround** — none existed to drop (`grep -i x-trace-id client/src`
  is empty). The ~40-site `metadata={"trace_id": …}` workaround FR-26 mentions was never taken.

---

## 5. Verification

Local runtime: the published `aindy-runtime==2.12.0` in `venv`, confirmed by import and path
(§1). Sibling checkout is at `v2.12.0-2`, ahead of the tag in `docs/` only.

| check | result |
|---|---|
| `test_runtime_dependency_contract.py` (now 6 tests incl. interpreter check) | pass — range, pin and *imported version* in lockstep at 2.12.0 |
| `test_trace_id_envelope_contract.py` | pass on 2.12.0; **fails on 2.11.0** (proved by downgrading and re-running) |
| app-profile subset (8 files, `-m app_profile`) | 55 passed |
| full `tests/unit` | **1,233 passed, 0 failed, 1 skipped** |
| boot smoke | `default-apps`, `app_plugins_loaded=True`, count **16**; `SYSCALL_REGISTRY` 98 |
| `scripts/check_app_imports.py` | 37 declared, 0 undeclared |
| `ruff check apps/ tests/` | clean |
| ABI deprecation warnings at boot | 0 |

**After the rebuild** (`--no-cache`, because the pin moved — the one case
`live-verification-practice` reserves it for), in the container:

```bash
python -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
#  expect: 2.12.0 ['/usr/local/lib/python3.11/site-packages/AINDY']
aindy-runtime bootstrap-schema                              # exit 0 — head still 0018
curl -s localhost:8000/health/deep | jq '.checks.syscall_registry.count'   # 98
curl -s -H "Authorization: Bearer $ADMIN" localhost:8000/observability/system \
  | jq '.data.registry // .registry | {syscall_count, tool_count, run_tool_provider_run_types}'
#  expect syscall_count ~98, tool_count 16 — the FR-23 fix; 0 means the plugin stack did not load
```

### In the container, after the rebuild (2026-09-12)

`--no-cache` build: `apt-get` 1,422 s and pip 966 s on a ~80 kB/s network — the build was slow,
not broken. `/health` answered 200 about three minutes after `up -d`; host at 1,019 MB
available during boot; 0 postgres reinits.

| check | result |
|---|---|
| `import AINDY` version + path | `2.12.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| `aindy-runtime bootstrap-schema` | exit 0 — "no table changes", stamped `0018` |
| `/health/deep` → `syscall_registry` | `{"count": 98, "minimum_expected": 24, "status": "ok"}` |
| `/api/version` | `default-apps`, `app_plugins_loaded=true`, `app_plugin_count=16` |
| `AINDY_SYSCALL_IDEMPOTENCY_STRICT` | unset (off) |
| **FR-23** `/platform/observability/system` → `registry` (admin session, from the signed-in client) | `{"syscall_count": 98, "tool_count": 16, "run_tool_provider_run_types": ["default"]}` — **was 0 / 0** |

The run type is `default`, not `agent`: `apps/agent/agents/runtime_extensions.py:320` registers
the provider as `register_run_tool_provider("default", get_tools_for_run)`. The route lives at
`/platform/observability/system` (not the bare `/observability/system` the handoff's curl uses)
and needs a platform-admin **user session** — the `X-API-Key` alone is 401 since
`HTTP-SCOPE-GAP-1`.

### What this does not establish

FR-27's lock is unexercised because it is off. FR-25's new WARNING lines are unexercised
because nothing in the suite fails a syscall on purpose. Both are the correct state for a
release whose required action is a pin bump.
