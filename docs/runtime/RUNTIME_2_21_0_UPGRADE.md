---
title: "Runtime 2.21.0 upgrade — adoption"
last_verified: "2026-09-18"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.21.0 upgrade — adoption

Floor moved `>=2.20.0,<3.0` → `>=2.21.0,<3.0`; build pin `==2.20.0` → `==2.21.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.21.0.md`.
The 2.19.0 and 2.20.0 handoffs were re-read alongside it; both are adopted and container-verified
(`RUNTIME_2_19_0_UPGRADE.md`, `RUNTIME_2_20_0_UPGRADE.md`) and nothing in them is left open on our
side except what §4 below carries forward.

**No schema step, no required code change.** Verified rather than taken from the handoff: runtime
Alembic head unchanged at `0019`; `SCHEMA_CONTRACT_VERSION` unchanged at `2026-09-16`; `git diff
v2.20.0..v2.21.0 -- AINDY/db/models alembic/` is empty. The diff under `AINDY/` is 20 files
(+989 / −234). We import from 7 of them and every symbol we take is unchanged; the seam-level
additions are private (`_run_authority_ended`, `_tool_network_mode`, `_persist_on_session`,
`run_post_persist_effects`) plus one metric series (`authority_lifetime_refusals_total`).

**One thing the handoff asks for *before* the rebuild** — a write followed by a raise with no
commit between (§1) — was done first, and answered: none (§2). One thing the handoff asks for
that is already done, and one that was already on file before it asked (§4).

---

## 1. The dev venv, re-checked printing the path

```
2.20.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # before
2.21.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # after pip install -e .[test] -c constraints.txt --no-cache-dir
```

---

## 2. `EVENT-OUTBOX-1` (#721) — a handler that raises is now rolled back; our side, grepped

A route handler inside `ExecutionPipeline` that raises now has its request session rolled back
before `execution.failed` is recorded. Before, the failure event's own commit landed the
handler's pending writes as a side effect — `db.add(row)` then `raise HTTPException(409)` *kept*
the row. Side effect `handler.rollback` in the envelope.

**Our routes, scanned rather than assumed** (`scan_write_then_raise.py`, session scratchpad: per
function, in source order, a `db.add / add_all / delete / merge / execute / flush` followed by a
`raise` with no `.commit()` between; over-reports by design): **2 candidates across all of
`apps/`, both false positives**. Both are in
`apps/analytics/services/scoring/infinity_service.py::calculate_infinity_score`, inside
`transaction_scope(db)`, and the raise is `_ConcurrentScoreWrite` — the optimistic-lock race,
followed by an explicit `db.rollback()` and a retry. Discarding the write is the intent there.
Every other write-then-raise in our routes has a `commit` between, or the write is the thing being
refused. **Ask 3 answered: the pattern is not on our side.**

**Our test suite** — the handoff's second warning: a test sharing one session between app and test
(`mock_db` / `db_session`) that drives a route to a 4xx and then reads fixture rows breaks under
the new rollback. The full `tests/unit` on 2.21.0 is the check (§6.1).

`queue_system_event` (14 of our files) keeps its signature; its events now ride the handler's
transaction, which is what makes the rollback real — an event queued by a handler that raises is
gone with the handler's writes, which is the honest record.

---

## 3. Consumer-visible edges, checked against our source — none fire

| Change | Where we would feel it | Our source |
|---|---|---|
| `user.id` removed from `syscall.*` spans (#723; dated in 2.20.0 §3) | a trace query | no OTel exporter configured anywhere; every `user.id` in `apps/` is Python attribute access (re-checked; same as 2.20.0 §4) |
| `call_tool(name, args, step_index)` — per-step `agent_steps` rows as steps complete; crash continuation replays recorded successes; `replayed: true` on `result.steps[]` only when true (#722) | a reader of `result.steps[]` keyed on exact shape | `Assistant.jsx` / `AgentConsole.jsx` read `steps_completed` / `steps_total`, not the array's keys; our `replayed` hits are the DLQ panel's unrelated `replayed: true` reply. Nothing to change; a continued run's shape is additive |
| `EGRESS-INPROC-1` (#718) — the egress guard now reaches `isolation=` tools; `authority.network="none"` deny-all | only with `AINDY_EGRESS_ENFORCEMENT=1` | not set anywhere; **0** of our tools declare `isolation=` or `env_spec` |
| `AUTHORITY-LIFETIME-1` (#720) — a capability token for a run in a terminal status is refused at the tool seam and the dispatcher, `failure_class="permission"` | a caller presenting a run's token after the run ended | the check lives in `check_tool_capability`, **not** `validate_token`; our one direct caller — `apps/automation/routes/automation_router.py:119` replaying an automation log's stored `execution_token` — uses `validate_token`, which stays the pure HMAC check. Unaffected. Nothing of ours re-presents a run token after completion (the completion hook runs on jobs, not tokens) |
| `AUDIT-CORRELATION-1` (#719) — `syscall.executed` gains `capability`, `guarantee`, `action_id`; `capability.allowed` gains `action_id` | a test pinning either payload exactly | **0** tests reference `syscall.executed` |
| `HTTP-SCOPE-GAP-1` (DEC-046), `CLI-EXEC-SURFACE-1` (DEC-047) — closed by decision | — | nothing to do |

**Not touched:** the pipeline envelope's shape (one side effect added), `require_execution_unit`,
`to_envelope`, `run_flow`, every route path and status code we consume. App-profile syscall count
**97** = 23 runtime + 74 ours, unchanged.

---

## 4. The four asks

| # | Ask | State |
|---|---|---|
| 1 | Observe the first `leadgen.act` denial | **Already on file since 2026-09-16 — FR-38**, on both backends, with the operator's `skip` resume from a different process (`RUNTIME_FEATURE_REQUESTS.md` FR-38, *The first denial, observed*; also 2.20.0 §5.2). The flip waits on the runtime's `nodus_vm` seam, not on more evidence from here. The handoff has now asked for this twice after it was recorded — the record is in the register it names |
| 2 | Declare `args_schema` on tools you own | **Done, #389** (2.20.0 §5.1) — all 15. And FR-40: on `nodus_vm` the `warn` counter never leaves the worker, so `warn` is unobservable here |
| 3 | Grep pipeline routes for write-then-raise-without-commit | **Done, §2 — none** |
| 4 | Declare `nltk` and `textstat` in our own `pyproject.toml` (`PACK-DEBT-6`) | **Done, this PR** — `nltk>=3.10.3,<4.0`, `textstat>=0.7.13,<1.0`, the runtime's pins as floors, ranged for the same reason `aindy-sdk` and `anthropic` are (`constraints.txt` is not a lockfile). `apps/search/services/seo_services.py:7-8` is the import. The runtime may announce its pin removal |

---

## 5. Decisions recorded, at defaults

`AINDY_EGRESS_ENFORCEMENT` stays off (nothing of ours is isolated; no guest egress to enforce
yet). No new flags this release otherwise.

---

## 6. Verification

### 6.1 Dev venv, 2026-09-18

```
venv imports 2.21.0 from site-packages (path printed)               — §1
test_runtime_dependency_contract.py                                 — 6 passed (nltk/textstat accepted)
full tests/unit                                                     — 1316 passed, 1 skipped, exit 0 — no shared-session test broke under §2's rollback
ruff check apps/ tests/ — clean;  check_app_imports.py — 37 declared, 0 undeclared
```

### 6.2 Container

(filled after the rebuild)
