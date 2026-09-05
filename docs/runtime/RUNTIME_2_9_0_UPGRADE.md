---
title: "Runtime 2.9.0 upgrade — adoption"
last_verified: "2026-09-05"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.9.0 upgrade — adoption

Floor moved `>=2.8.0,<3.0` → `>=2.9.0,<3.0`.

No schema step **in this release**. One required code change on our side (§1), which is
the substance of this adoption.

> **★★ We still owe 2.8.0's schema step.** 2.8.0 was adopted on 2026-09-03 but the local
> stack was down for host-memory reasons and `bootstrap-schema` never ran against the
> deployed database. `flow_runs.graph_signature` is still missing there. The 2.9.0 handoff
> calls this case out explicitly: *"2.9.0 needs no schema step" is true of the release and
> false for a deployment that skipped one.* See §5.

---

## 1. ★★ The syscall envelope has two new `status` values

`status` may now be `partial` or `unknown`, not only `success` or `error`:

```jsonc
{ "status": "success" | "partial" | "unknown" | "error", "outcome": null, "data": {} }
```

The ask is one line: **treat anything that is not `success` as not-success.** A `partial`
that falls through an `== "error"` test reads as success, and you believe a half-applied
effect fully applied.

**Nothing emits these values in 2.9.0.** The value set widened while the set of emitters is
still empty, deliberately — so this is a change made ahead of the first emitter rather than
during an incident. This upgrade changes no response we receive today.

### What we found — 4 sites, not 24

A grep for `status == "error"` across `apps/` returns **24** hits. Only **4** are syscall
envelopes. The other 20 are different envelopes that must **not** be changed, and getting
that wrong would have been worse than doing nothing.

**Fixed (syscall envelope — `get_dispatcher().dispatch(...)`):**

| file | what it is |
|---|---|
| `apps/automation/flows/flow_definitions.py` | `_syscall_node` |
| `apps/automation/flows/system_flows.py` | `_syscall_node` |
| `apps/tasks/flows/tasks_flows.py` | `_syscall_node` |
| `apps/analytics/services/scoring/infinity_service.py` | direct `dispatch` of `sys.v1.task.get_user_tasks` |

**Deliberately not changed:**

- **~19 router sites** (`task_router`, `score_router`, `goals_router`, `arm_router`, …)
  test the result of `run_flow(...)`. That is the **flow** envelope, whose statuses are
  `SUCCESS | FAILED | SKIPPED | WAITING` — verified from
  `flow_engine/runner_completion.py`, where `_format_execution_response` is only ever
  called with those four. Rewriting these to `!= "success"` would treat every successful
  flow as a failure, because flow success is uppercase `SUCCESS`.
- `apps/social/routes/social_router.py` — the canonical **HTTP** envelope in a response
  adapter. The runtime's own `AINDY/core/response_adapter.py:60` uses the identical
  `== "error"` on that envelope and was **not** among the four sites the runtime fixed in
  this release, which is the evidence that it is not syscall-shaped.
- `apps/rippletrace/services/content_ingest.py` — `poll_source()` is ours; its `status` is
  our own dict, unrelated to any runtime envelope.

**29 syscall sites in `apps/` already used `!= "success"`** before this change. The four
above were the exceptions, not the rule.

### A second defect fixed in the same lines

All four sites read `result["error"]` on the failure branch. Only an `error` envelope is
guaranteed to carry that key — a `partial` or `unknown` would have raised `KeyError`
*inside the error handler*, converting a recoverable partial into an unhandled exception.
Changed to `.get("error")` with a fallback naming the status.

---

## 2. `EffectRecord.status` — no impact

The column can now hold `partial` and `unknown`, written from the same resolution as the
envelope. **We never read `effect_records`** — no reference anywhere in `apps/`. Nothing
to do.

---

## 3. Cancellation granularity — informational

`sys.v1.agent.cancel` now refuses the *next* tool call rather than taking effect between
segments. It is cooperative (a tool already executing is not interrupted) and fails open
(unreadable cancellation state means "not cancelled"). A tool in the isolated
out-of-process worker is not reached by it at all.

No app change. New metric `aindy_run_cancel_observed_total{surface}` if we want to watch it.

---

## 4. Smaller things

- **LLM token metering will read zero for us, and that is expected.** The handoff predicts
  this and it is correct: we construct provider SDK clients directly —
  `apps/agent/agents/planner_anthropic.py:64` (`anthropic.Anthropic()`) and
  `apps/arm/services/deepseek/deepseek_code_analyzer.py:576-578` (`OpenAI(...)`) — so
  nothing routes through the runtime's metered seam. Routing `planner_anthropic.py`
  through it is a scoped option, not a request, and carries a stated regression in error
  diagnosability. Not taken here.
- **`env_spec` on `register_tool`** — an undeclared tool is completely unaffected. We
  declare none.
- **`state_policies` on flow definitions** — inert today with one writer per node.
- **`aindy_syscall_outcome_total{syscall,status}`** — a non-zero
  `aindy_syscall_outcome_refused_total` would indicate a handler making a malformed
  outcome claim, i.e. a bug on the emitting side.

---

## 5. Deployment: the 2.8.0 step is still outstanding

Whoever brings the stack up next must do this **before** expecting it to serve, because
our database is still at runtime revision `0017`:

```bash
# read the exit code first if unsure: 0 = done, 3 = reconcile, 4 = stop and ask a human
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml \
  run --rm --no-deps --entrypoint aindy-runtime api bootstrap-schema
```

Exit `3` is expected here (2.8.0's `flow_runs.graph_signature` is missing), and the fix is
the same command with `--reconcile`. `docker/entrypoint.sh` already branches on this, so
the failure mode is a clean stop with instructions rather than a crash loop — see
`RUNTIME_2_8_0_UPGRADE.md` §1.

Running `bootstrap-schema` after that reconcile exits `0`: 2.9.0 adds no drift of its own.

---

## 6. Verification

Local `AINDY/` is exactly v2.9.0 — the sibling checkout is ahead of the tag only in
`tests/` and `docs/`, with no diff under `AINDY/`.

| check | result |
|---|---|
| `test_runtime_dependency_contract.py` | pass — specifier in lockstep |
| app-profile subset (7 files, `-m app_profile`) | 55 passed |
| flow / syscall / infinity / task / automation unit suites | 141 passed |
| boot smoke | `default-apps`, `app_plugins_loaded=True`, count **16** |
| `scripts/check_app_imports.py` | 37 declared, 0 undeclared |
| `ruff check apps/ tests/` | clean |

### What this does not establish

**The behaviour change is unexercised, and cannot be exercised yet.** Nothing emits
`partial` or `unknown` in 2.9.0, so no test can drive a real one through these four sites.
What the suites prove is that the rewritten condition is equivalent for the `success` and
`error` cases that do occur — not that the new branch behaves well when it first fires.

The schema step in §5 has still not run.

---

## 7. Found during this audit, NOT part of this release

The classification work above surfaced something separate and pre-existing.

`run_flow()` never returns `status == "error"`. Both of its paths return the flow
envelope — the direct path returns `runner.start(...)`, and the syscall path raises on a
failed syscall and otherwise returns `result["data"]["flow_result"]`. Its statuses are
`SUCCESS | FAILED | SKIPPED | WAITING`. The runtime's own `memory_router._mem_run_flow`
tests `result.get("status") == "FAILED"`, which is the independent confirmation.

So the ~19 app router sites testing `run_flow(...).get("status") == "error"` are **dead
branches**: a `FAILED` flow does not match, falls through to the success path, and the
route returns a 200 built from whatever `data` holds.

`CLAUDE.md`'s "Integration test patterns" section documents `run_flow()` as returning
`{"status": "SUCCESS"|"error", ...}`, which is where the `"error"` half is wrong.

**Not fixed here.** It is unrelated to 2.9.0, it touches ~19 routes, and the right
behaviour on `FAILED` is a per-route decision rather than a mechanical rewrite. Tracked
separately.
