---
title: "Runtime 2.22.0 upgrade — adoption"
last_verified: "2026-09-23"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.22.0 upgrade — adoption

Floor moved `>=2.21.0,<3.0` → `>=2.22.0,<3.0`; build pin `==2.21.0` → `==2.22.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.22.0.md`;
companion: `aindy-runtime/docs/upgrades/SOAK_REGISTER.md` (§8 below).

**The schema step did not happen the way the handoff said it would — and did not happen at all
until we ran it by hand.** The handoff promised exit 3; the entrypoint got exit 0 and a stamp of
`0020` over an unwidened column. Filed as **FR-43** (§2). Everything else in the release landed as
described, and four of our five open FRs shipped in it.

---

## 1. Installed runtime, printing the path

```
2.22.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']      # dev venv, pip install -c constraints.txt
2.22.0 ['/usr/local/lib/python3.11/site-packages/AINDY']                       # container, image ea952767e33b
```

App-profile boot in the container: `boot_profile=default-apps`, `app_plugins_loaded=True`,
`app_plugin_count=16`; `/health` 200.

---

## 2. ★ The schema step — Alembic `0020` was stamped, not applied (FR-43)

The handoff §1 says that with `AINDY_BOOTSTRAP_RECONCILE` off, `bootstrap-schema` exits **3** and
the entrypoint stops. First boot of the 2.22.0 image, flag off:

```
[entrypoint] runtime schema: aindy-runtime bootstrap-schema
ok: runtime-owned tables already present (no table changes).
ok: stamped alembic_version_runtime to revision 0020.
```

The api booted healthy, and:

```
system_events.source character_maximum_length   32
alembic_version_runtime                         0020
```

**Cause, read in the installed package:** `schema_contract._normalize_type_name` compiles each
column type and keeps only the part before `(` — `VARCHAR(32)` and `VARCHAR(128)` are both
`varchar`, so the drift check reports `compatible` and `_bootstrap_schema` stamps head. Even had it
been detected, a `column_type_mismatch` is classed offline-migration (exit 4) and `--reconcile`
only handles missing tables and columns, so the exit-3 path the handoff describes does not exist
for a widening. The handoff's own verification step 2 (`exit 0 and "stamped 0020"`) passes on the
broken stack; only the `information_schema` query beside it shows the problem.

**Remedied out-of-band with 0020's own DDL**, metadata-only in PostgreSQL, no row touched:

```sql
ALTER TABLE system_events ALTER COLUMN source TYPE VARCHAR(128);   -- → 128
```

`bootstrap-schema` re-run afterwards: exit 0, stamped 0020, column 128. `AINDY_BOOTSTRAP_RECONCILE`
stays off. Filed upstream as **FR-43** (compare length, class a pure widening as reconcilable,
never stamp past DDL that did not run).

**For any other stack adopting 2.22.0 from a create_all-built database: check the column, not the
exit code.** A stack whose runtime schema came from `alembic upgrade` gets 0020's DDL normally.

---

## 3. FR-39 — the planner sees the Infinity context, verified live

`build_planner_context` had been rewritten to open its own session in #388
(`AGENT-PLANNER-CONTEXT-BOUNDARY-1`) and was waiting only on a string tenant. Driven through the
runtime's own path (`agent_runtime.shared._get_planner_context`, which crosses the extension
boundary) in the container, for the designated test account, read-only:

```
prompt_len 1548
has_kpi_block True
has_reasoning_block True
context_block_len 680
## User Performance Context (Infinity Score)
Overall score: 48.1/100 (confidence: low)
…
- ARM usage is low - consider arm.analyze to improve code quality
## Reasoning Recommendation (Autonomous Reasoning)
Recommended next action: review_plan (because: ai_productivity_below_threshold)
```

Before 2.22.0 this was 0 and 0: every plan since 2026-05-20 was made from the base prompt alone.
The memory block is absent here because the recall returned nothing for this account, not
because it failed. `AGENT-PLANNER-CONTEXT-BOUNDARY-1` closed. The provider's WARNING on a missing
tenant stays, re-worded: it would now mean a regression.

---

## 4. FR-38 — the resume route passes the decision body through

`apps/agent/routes/agent_router.py::resume_agent_run` now takes an optional JSON body and hands it
to `resume_agent_run_runtime(..., payload=)` unread, mirroring the runtime's reference route. A
run parked at the authority gate can be resumed on our surface with
`{"decision": "skip" | "abort", "note": "…"}`; without a body the runtime answers 409 and the run
stays parked. An ordinary plan-declared wait resumes as before. Test:
`test_agent.py::TestAgentResume::test_resume_passes_gate_decision_through` (integration,
Linux CI).

**No client surface resumes an agent run at all** — the only resume in `client/src` is the flow
engine's. A gate-parked run is decided through the API until one exists. Noted, not built.

### 4.1 Handoff §6 ask 1 — the manufactured denial, re-run on `nodus_vm` (2026-09-23)

The 2026-09-16 manufacture, unchanged (FR-38 in the register): a one-step plan
`leadgen.act {apply: false, channel: draft}` for the designated test account, executed in a
`docker exec` under a token minted with `capability_ceiling=['execute_flow']` — the plan requires
`['execute_flow', 'external_api_call']`, so `granted_tools: []`. Backend `nodus_vm` (our default,
no override), `AINDY_AUTHORITY_NEGOTIATION=true`. Run **`bea83301-c771-49f7-adcd-9434ecd4662c`**.

| | 2026-09-16, runtime 2.19.0 (run `3562ae93…`) | 2026-09-23, runtime 2.22.0 (run `bea83301…`) |
|---|---|---|
| after `execute_run` | **`failed`** — `step 0 (leadgen.act) failed: tool 'leadgen.act' not granted by capability token` | **`waiting`**, `steps 0 / 1`, no error |
| agent events | `capability.denied` ×3, `AGENT_STEP_FAILED` | `EXECUTION_STARTED` → `AUTHORITY_NEGOTIATED {outcome: waiting}` → `WAITING` |
| `wait_state` | — | `{event_type: agent.authority.decision, continuation: true, resume_segment_index: 0, authority_gate: {tool: leadgen.act, step_index: 0, negotiation_outcome: no_variant, decisions: [skip, abort], denied_error: …, tool_args: {apply: false, channel: draft}}}` |

**The operator's half, over HTTP through OUR route** (`POST /apps/agent/runs/{id}/resume`, the
#399 pass-through), as the test account:

| body | answer | run after |
|---|---|---|
| none | **409** `Run is parked at the authority gate; resume needs a decision: skip \| abort` | `waiting` |
| `{"decision": "maybe"}` | **422** `unknown authority-gate decision 'maybe'; the run stays parked` | `waiting` |
| `{"decision": "skip", "note": …}` | **200**, `authority_gate.run_status: "resuming"`, **`waiters_notified: 0`** | step 0 → `skipped` with the note; **run stayed `waiting`** (3 min observed) |
| api restarted, then `skip` again | **200**, **`waiters_notified: 1`** | `executing` → **`completed`** within 11 s |

Final state: run `completed`, `steps_completed 0 / steps_total 1` (FR-34's fix, visible — a skip is
not a success), step 0 `skipped` with `result {authority_gate: skip, note: …}`,
`result.steps[0].replayed: true`, `COMPLETED` agent event, `agent.completed` system event.
**`wait_state` cleared** (to JSON `null` — `IS NULL` reads false on it; read the value).
The 09-16 "not cleared" observation does not reproduce, on the rehydrated path either.

**Verdict for phase 3: the gate works on `nodus_vm`** — park, typed refusal, skip, re-drive,
completion. With 09-16's `agent_flow` evidence the flip now has both backends.

**One defect, filed as FR-44:** the first `skip` wrote its irreversible half (the step row
`skipped`) and answered `resuming` while no process held the run's waiter — agent-run waits are
re-registered **only at startup** (`startup.py` → `rehydrate_waiting_agent_runs`), and this park
was made in a process that then exited. Nothing on the response distinguishes that from a real
resume except `waiters_notified: 0`. It is partly the manufacture's shape (a park made outside
the api), but the same holds for any park made by a process other than the one serving the
resume — and the flow resume route has handled exactly this since FR-31.

**FR-40 — no evidence from this run** (the only tool step was denied before argument validation,
then skipped). Read on an ordinary run instead — §5.

---

## 5. FR-40 — `warn` is now observable on `nodus_vm`

Nothing to change: `AINDY_TOOL_ARGS_VALIDATION` stays `warn`.

**Verified live 2026-09-23** with an ordinary run: the test account asked for a read-only
`memory.recall` + `reasoning.evaluate` over the API; the planner (with the Infinity context, §3 — no
`[planner_context]` WARNING) produced two low-risk steps, `memory.recall {limit: 5, query:
"sprint-12"}` and `reasoning.evaluate {}`; approved through `/apps/agent/runs/{id}/approve`. Run
**`1b99dc93-eed6-492e-82e5-91db11da3806`**: `completed`, `steps_completed 2 / 2`, both steps
`success`, executed as a Nodus task graph (`nodus_events: task_graph_start {tasks: 2}` on its
`execution.completed`). Baseline before the run: no samples. After, on the **api's** `/metrics`:

```
aindy_tool_args_validation_total{mode="warn",outcome="valid",tool="memory.recall"} 1.0
aindy_tool_args_validation_total{mode="warn",outcome="valid",tool="reasoning.evaluate"} 1.0
```

On 2.20.0 / 2.21.0 these samples existed only in the worker. So `warn` is now observable here,
and the recipe holds: when `outcome="invalid"` stays absent across ordinary runs, the flip to
`enforce` is the owner's call on evidence. Two valid samples are not that evidence yet; the
counter resets on an api restart, so read it over a stretch of real use.

---

## 6. FR-41 — width 128; our renames stay

Our eight renamed routes (`ROUTE-NAME-EVENT-SOURCE-1`) stay renamed: the shorter names are
already in the ledger and nothing is gained by splitting a route's history across two names.
`test_route_names_fit_event_source.py` reads the width off the model and keeps working (it now
reads 128). Verification step 3 had no traffic to read at the time of writing.

---

## 7. FR-37, PACK-DEBT-6, `[mcp]`

- **FR-37:** adopted 2026-09-23 — §7.1.
- **`nltk` / `textstat`** leave the runtime's dependencies no earlier than 2026-10-01. We declared
  both in #391; nothing to do.
- **`[mcp]` extra** no longer caps `mcp<2`. We do not install it.

### 7.1 FR-37 — ui-kit 2.1.0, and why the bump was not a drop-in (FR-45)

**What 2.1.0 does, read in the installed bundle:** `request()` reads `X-AINDY-Envelope`; a stamped
body is resolved to `body.data` (or `null`) and marked. Once ONE stamped response has been seen, a
module-level latch marks every later UNSTAMPED body as final too, and `unwrapEnvelope` passes a
marked value through. So after the latch, `unwrapEnvelope` no longer unwraps anything.

**Why that would have broken us:** the runtime stamps only `adapt_response`'s default exit. A
route answered by a registered adapter is unstamped, including the runtime's own
`raw_canonical_adapter`, whose body IS the canonical envelope, and `legacy_envelope_adapter`.
Measured live, every parameterless `/apps` GET as the test account (78 × 200):

| | before | after this change |
|---|---|---|
| stamped envelope | 8 (tasks, identity, dashboard) | **31** |
| unstamped body with a `data` key | 26 (analytics, ARM, compute, social, autonomy/coordination, + 3 agent) | **3** (agent's hand-built list wrapper, read explicitly) |
| bare, unstamped | 44 | 44 |

Resolving every pipeline `route_name` against the registered adapters gave the full set: 45 names
through `raw_canonical_adapter`, 8 through the legacy one, 1 exact (`social.feed.get`), 3 memory
execute adapters. All their client consumers used `unwrapEnvelope`. After the latch, which any
stamped response trips (the dashboard's own `/apps/dashboard/overview` is one), analytics, ARM,
social and the agent console would have received the whole envelope, or not, depending on which
page loaded first.

**What changed, ours:**

- `apps/_shared/envelope.py::stamped` wraps a response adapter to set `X-AINDY-Envelope: v1` on
  success. Applied to every adapter whose body carries `data`: analytics / main, arm, autonomy /
  system / coordination, social + `social.feed.get`, and the three memory execute adapters.
  `test_response_adapters_stamp_envelopes.py` checks every adapter every app registers: a body
  with `data` is stamped, a body without it is not (mutation-checked: 12 adapters fail with the
  wrapper disabled).
- `client/src/api/agent.js`: the agent router's `{data: [...]}` is hand-built, not an envelope.
  The four list reads use `listOf` instead of `unwrapEnvelope`, so they work either side of the
  latch. A test pins that case.
- All 51 other `.then(unwrapEnvelope)` calls deleted (analytics 20, operator 9, arm 7, social 6,
  tasks 5, identity 4). Every body they received is now either stamped (resolved in `request()`)
  or bare (nothing to unwrap). Test stubs for stamped routes now send the header, as the server does.
- `@aindy/ui-kit` `^2.0.0` → `^2.1.0`. The lockfile change is only the kit's 4 lines. npm on
  Windows also dropped two nested optional `wasm32` packages, which was reverted.

Client: 321/321 tests, lint clean, production build OK. Backend: unit suite, ruff, import check.

**Filed as FR-45** (runtime + kit): the runtime's own envelope-bodied adapters should stamp,
since every app that registers them has this latent bug; and the kit's latch assumes every
envelope is stamped. `_resetEnvelopeDetection` is declared in the `.d.ts` but not exported
from the bundle.

---

## 8. Soak register

Row 1, `AINDY_MEMORY_RECALL_OWN_SESSION`: **wired, value empty → off.** `docker-compose.prod.yml:148`
passes `${AINDY_MEMORY_RECALL_OWN_SESSION:-}` and `.env` does not set it; the runtime reads
anything outside its truthy set as off (`memory/orchestrator.py:120`).

**Soak started 2026-09-23T20:30Z (owner):** `AINDY_MEMORY_RECALL_OWN_SESSION=true` in `.env`,
confirmed in the container's environment. Baseline read just before the flip: `idle in
transaction` 0, `aindy_db_pool_exhaustion_events_total` 0, `aindy_db_pool_checkedout` 1,
`[MemoryOrchestrator] recall failed` 0 in the log. The last `memory.recall` agent step before the
flip succeeded (run `1b99dc93…`, §5). Ends no earlier than 2026-09-30 (7 days), or 200 runs if
that comes later. Read the same four signals, plus a `memory.recall` step succeeding, at the end.
Rows 2–6 wait behind row 1 (one flag at a time).
