---
title: "Runtime 2.26.0 adoption"
last_verified: "2026-10-09"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.26.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.26.0.md`. No schema change (head stays `0020`), no
ui-kit change. Three defaults turn on; of them only the run-scoped syscall cap can change what we see.
It answers none of our open FRs: **FR-51** (pymongo 4.18.1) and **FR-52** (the compatibility check on
every request) are both still present.

## 1. The pin, and what is actually running (ask 1)

`pyproject.toml` `>=2.26.0,<3.0` and `constraints.txt` `==2.26.0`, moved together;
`test_runtime_dependency_contract.py` moves with them. The handoff's ask 3, the soak row 1 readout, was
taken **before** this rebuild (`RUNTIME_2_25_0_UPGRADE.md` §4.1).

Rebuilt 2026-10-09 (399 s, a pin move), image `4aee1092a575`; api healthy ~80 s after recreate.

| Check | Read |
|---|---|
| version and path, in the container | `2.26.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| boot | `boot_profile=default-apps`, `app_plugins_loaded=True`, `app_plugin_count=16`; `/health` 200 |
| compatibility (DEBT-COMPAT-1, now naming its source) | `aindy-apps-monolith` `<3.0,>=2.26.0`, **`satisfied`**, read from `site-packages/aindy_apps_monolith-1.0.0.dist-info`, `shadowed_metadata: []` |
| schema | none applied: runtime `0020`, app `rc2claims0001`; `[deploy_bootstrap] schema ready` |
| flags | `AINDY_PLAN_STEP_REFERENCES=1`, `AINDY_MEMORY_RECALL_OWN_SESSION=true`, `AINDY_SYSCALL_IDEMPOTENCY_STRICT=1`, `AINDY_RUNTIME_CALLBACK_TIMEOUT_SECS=90`; no quota or fan-out override, so 2.26.0's defaults apply |
| `pymongo` | 4.18.1 (FR-51 still open) |
| `GET /apps/scores/me`, 10 warm calls | p50 5,081 ms, max 6,570, 10/10 OK: **FR-52 unchanged** |
| local unit suite on 2.26.0 | three failures, all the step-reference default (§2), fixed here |

## 2. Plan step references, default ON (§1) — three of our tests assumed unset meant off

`AINDY_PLAN_STEP_REFERENCES` was already `1` here through compose, so runs do not change. Our planner
prompt chooses its step-result rule through the runtime's own `step_references_enabled()`, which is
why it followed the flip without a code change. The tests did not: three of them treated an unset
flag as off. `test_run_findings.py` now pins all three states (`0` → our flag-off rule, `1` → the
reference rule, unset → the reference rule), and the two `test_planner_context_boundary.py` tests
compare against `planner_system_prompt()` instead of the flag-off constant.

## 3. ★ A run's syscalls count against one cap (§2, SYSMAX-4)

`AINDY_RUN_SCOPED_QUOTA` now defaults ON: every dispatch during an agent run counts against that
run's `AINDY_QUOTA_MAX_SYSCALLS` (default 100), on both backends. We set neither.

**History cannot measure our exposure, for the reason this release fixes.** Every one of our 42 agent
runs shows a single `syscall.executed` under its trace: on `nodus_vm` (our default) the worker charged
its own unit. What history does give is the shape: **at most 7 steps, 2.9 on average.** At a generous
five syscalls per tool step that is ~35 per run, a third of the cap.

**Owed:** after the first real agent runs on 2.26.0, `docker logs <api> 2>&1 | grep
RESOURCE_LIMIT_EXCEEDED`, and report any hit with the run's step count (the handoff's ask 2). A refused
step is retried 3 times (`transient`), so one refusal logs three lines.

## 4. Concurrent fan-out, held effects, filesystem scope (§3–§5): nothing of ours

Checked against our source, not taken from the handoff: no `FanOutEdgeGroup`, no `outbound_request`,
no `AT_MOST_ONCE` or `EffectOutcomeUnknown`, no declared filesystem scope, no quota or fan-out
override in compose or `.env`. The new admin routes (`GET /platform/effects/unknown`,
`POST /platform/effects/{action_id}/resolve`) need nothing from us.

## 5. Still open after this release

- **FR-52 (P1).** `load_plugins()` still ends in `check_consumer_requirements` on every call
  (2.26.0 only made the check name where it read metadata). Every request still carries ~3 s.
- **FR-51.** `pymongo==4.18.1` unchanged; our audit ignores stay, with their removal condition.
