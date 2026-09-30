---
title: "Runtime 2.24.0 + ui-kit 2.1.1 upgrade — adoption"
last_verified: "2026-09-26"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.24.0 + ui-kit 2.1.1 upgrade — adoption

Floor `>=2.23.0,<3.0` → `>=2.24.0,<3.0`; build pin `==2.23.0` → `==2.24.0`; `@aindy/ui-kit`
`^2.1.0` → `^2.1.1`. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.24.0.md`.

**This release answered all five open FRs: FR-43 … FR-47.** FR-44 is verified live (§3). FR-46
ships default-off, and its evidence run is owed (§5). No migration.

---

## 1. Installed, printing the path

```
2.24.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # dev venv, pip install -c constraints.txt
2.24.0 ['/usr/local/lib/python3.11/site-packages/AINDY']                     # container
@aindy/ui-kit 2.1.1                                                          # client/node_modules (npm ci from the lock)
```

Boot: `default-apps`, 16 plugins, `/health` 200.

## 2. Schema: FR-43 on a stack we had already fixed

`bootstrap-schema` now compares string length and numeric precision. We widened
`system_events.source` to 128 out of band on 2.22.0 (`RUNTIME_2_22_0_UPGRADE.md` §2), so as the
handoff predicted our entrypoint saw exit 0. Read from the database: `alembic_version_runtime`
**`0020`**, `system_events.source` **128**.

## 3. FR-44: verified live (handoff §8 ask 2)

This is the 09-23 setup that stranded the run until a restart. The api had booted **before** the
park; the park was made in a separate `docker exec` (`leadgen.act` under a token that excludes
`external_api_call`, test account); the resume went over HTTP through our route. Run
`3880d88e-c95c-4a7c-8a0b-9743ef7e64e6`:

```
POST /apps/agent/runs/{id}/resume {"decision":"skip", …}
→ 200 | waiters_notified: 1 | authority_gate.run_status: "resuming"
→ run completed at the first poll, no restart; step 0 skipped; wait_state cleared
```

We have no client surface that reads `run_status`, so the new `"waiting"` value (§2 of the
handoff) needs no branch here.

## 4. FR-45 and FR-47: the client

- **FR-47 (ui-kit 2.1.1):** `createAgentRun` passes `timeoutMs: 90_000` and the #410
  poll-on-408 workaround is removed. A 408 now means the kit's own 90 s timer fired. Run creation
  still has no idempotency key (handoff §6 note 1), so that error tells the user the run may still
  arrive rather than inviting a resubmit. We use no caller `signal`, so the `AbortError` change does
  not reach us.
- **FR-45:** the runtime's envelope adapters stamp `X-AINDY-Envelope` themselves, including on
  error statuses whose body carries `data`. This is harmless, because the kit throws on any non-2xx
  first. Our `apps/_shared/envelope.py::stamped` stays: it is a no-op over the runtime's adapters
  and the only stamp for our own `social_feed_response_adapter`. The guard test
  (`test_response_adapters_stamp_envelopes.py`) holds either way. The one test that had pinned
  error-status behaviour *through* the runtime's adapter now pins our wrapper alone.
- The ui-kit lock entry was edited by hand (only its version, URL and integrity change; 2.1.1's
  dependencies are identical), as for 2.1.0, so npm on Windows does not drop the `wasm32`
  optional packages from the lock.

## 5. FR-46: step references, default off

- **The planner rule follows the flag.** #412's rule told the planner *"a step cannot read an
  earlier step's result"*. With `AINDY_PLAN_STEP_REFERENCES=1` the runtime's catalog teaches the
  `$from_step` form, and that rule would contradict it. `planner_system_prompt()` now uses the
  runtime's own `step_references_enabled()` to pick the matching rule, so the two cannot
  disagree. With the flag off, nothing changes.
- **The 2 KB cut is ours, and it is fixed** (handoff ask 4). `sys.v1.research.query` returned
  `raw[:2000]`, which dated from the initial extraction and cut mid-word with no marker. It now
  returns up to **6000** characters (the findings-digest cap), cut at a word boundary and marked
  ` … [truncated]` (`apps/search/syscalls.py::_research_excerpt`, `test_research_excerpt.py`).
  `search_service.raw_excerpt` is the Search page's preview, not an agent input; it is unchanged.
### 5.1 The FR-46 evidence run (handoff §8 ask 1): **passed on the second attempt**

`AINDY_PLAN_STEP_REFERENCES=1`, wired into compose (#414; `.env` alone never reaches the process).
The owner's original goal, *"Research SEO, AI Search and Marketing Strategies. Then use the research
to create a strategy to market aindy-runtime and the A.I.N.D.Y. app"*, submitted in Collaborator
and approved by the owner.

**First attempt, run `615b67ea` — failed safely, and found FR-48.** The planner used a reference,
`memory.write {"content": {"$from_step": 0, "path": "results"}}`, but `research.query` returns
`{raw_result}`. `results` is `search.query`'s key. The step failed with
`step reference could not be resolved: args.content: step 0's result has no 'results'`. No
placeholder was written and the tool was never called with the literal (DEC-075, as designed). The
planner is shown tool arguments, never results, so the path was a guess. Ours (#415): every
tool description states its return shape, and a test checks the keys against each tool's real
result. The runtime's half is FR-48 (`result_schema`, and path checks at plan time).

**Second attempt, run `19dcf508-c452-4a36-9e0f-3794f4d55ebc` — passed.** `completed 5/5`:

```
2 memory.write  plan:     {"content": {"$from_step": 0, "path": "raw_result"}, …}
                recorded: {"content": "GEO vs AEO vs SEO: The 2026 Field Guide for B2B SaaS Marketers\nhttps://www…", …}
```

- `agent_steps[2].tool_args.content` **equals** `agent_steps[0].result.raw_result`, byte for byte
  (SQL equality: `t`), 5000 characters. The stored memory node holds the same 5000 characters.
- Under the old `raw[:2000]` cut (§5), 60% of it would have been lost mid-word.
- The completion hook also saved the run's findings (#412, node `f20ab0ea…`).

**Pass condition met:** the `memory.write` step stored step 0's findings, not a sentence written
before step 0 ran. The flag stays on here.

Two observations, neither a failure:

1. **The research is now in memory twice**: the referenced `memory.write` and the completion
   hook's findings node. Harmless; when a run already saved its research through a reference, the
   hook's copy is redundant. A small follow-up of ours.
2. **The two `task.create` names are still the planner's own wording** (*"Draft go-to-market
   marketing strategy … using SEO/AI-search research"*). A reference substitutes a value; it
   cannot make the planner write new text from findings it has not seen. "Turn the research into
   specific tasks" still needs a second planning pass: Collaborator's *Continue from this* (#411).

## 6. IDEM-14, nodus-lang 5.15.0

- **IDEM-14** (tool idempotency key per plan step): we have no `EXACTLY_ONCE` tool, and none of
  our tests stubs `execute_tool` with a fixed signature. The unit suite passes on 2.24.0.
- **nodus-lang 5.15.0:** we do not pin it, so nothing to move.

## 7. Operational note

`npm ci` on Windows fails with `EPERM` on `lightningcss-win32-x64-msvc` while Vite is running,
because the dev server holds the native module open. It also deletes `node_modules` first, so Vite
breaks until the install finishes. Stop Vite, install, then restart it detached.

## 8. Soak register row 1 — the 7-day readout (2026-09-30)

`AINDY_MEMORY_RECALL_OWN_SESSION=true`, on since 2026-09-23T20:30Z, confirmed in the container's
environment at the reading. Read against the baseline in `RUNTIME_2_22_0_UPGRADE.md` §8 and the
register's row 1 (`aindy-runtime/docs/upgrades/SOAK_REGISTER.md`).

| Signal | Baseline (09-23) | 09-30 |
|---|---|---|
| `idle in transaction` | 0 | **0**, sampled six times over a minute; `pg_stat_activity` held 1 active, 6 idle |
| `aindy_db_pool_exhaustion_events_total` | 0 | **0** (pool size 20, pressure ratio 0) |
| `aindy_db_pool_checkedout` | 1 | **0–5, returning to 0** across the minute: scheduler ticks, not held connections |
| `[MemoryOrchestrator] recall failed` | 0 | **0** in the current container's log (see the gap below); 0 at the 09-25 mid-window read |
| `memory.recall` steps succeeding (presence) | — | **7 of 7 succeeded**, 09-26 → 09-28; none failed |

**Failed runs in the window: 3 of 15, none recall-related.** `abf834d4` (task.create without a
masterplan_id), `615b67ea` (an unresolvable step reference, FR-46's evidence run) and `195777b0`
(`leadgen.search`'s memory note without `node_type`, fixed in #425).

**What the readout does not show, stated rather than implied:**

- **Volume: short of 200 runs.** 15 agent runs and 120 flow runs in the window. Our §8 terms were
  *7 days, or 200 runs if that comes later*, so on its own terms the window is not finished. The
  time half is met and every signal is clean; the volume half is not.
- **The presence signal was never sampled during a recall.** The register asks for `idle in
  transaction` *during a recall-heavy run*. Every reading was at rest. The seven recall steps
  succeeded, which is half of the presence signal; whether the caller's transaction stayed short
  during them was not observed.
- **The log has gaps.** The api container was recreated at least six times in the window (each
  merge that went live). `docker logs` covers only the current container (since 2026-09-30T15:03Z);
  the stretches between the 09-25 read and today were never read. The step table and the pool
  counters are the durable evidence; the log is not.
- **The one behaviour change was not exercised on purpose.** The register's failure mode is recall
  missing rows the caller wrote and has not committed. Nothing in the window was built to test
  that, and nothing reported it.

**Verdict, as first written:** clean for 7 days at low volume; the window continues to 200 runs.

### 8.1 Corrected the same day: the volume was never low

The 200 was read as *agent runs*, which at one owner's pace is months. But the flag changes **every
memory recall**, and agent `memory.recall` steps are the rarest kind. The runtime's request pipeline
recalls after every successful authenticated request (`_safe_recall_memory_count`), and since #393
every route of ours hands it a session, so every one goes through the own-session path. Agent planning
and Nodus execution recall too.

- **1,332** authenticated requests completed in the window (`system_events`, `execution.completed`
  with a user), each one a recall through the flagged path, plus the 7 agent steps. Past 200 six
  times over, with the pool and transaction signals clean throughout.
- **Their failures have no witness.** The pipeline's recall failure is recorded as a request side
  effect and logged at DEBUG; neither is persisted (0 of 1,614 completed events carry
  `side_effects`). Filed as **FR-49**, which asks for a counter.
- **The behaviour change, audited.** Nine places in our apps recall. Eight recall before they write
  or never write. Task completion writes a note and then recalls, and is safe twice: under a request
  the note is queued until the handler returns, and it is an `outcome` note while the recall asks for
  `decision`. Agent plans that write in one step and recall in a later one are safe because each tool
  step dispatches with no caller session, so the runtime's handler commits its own write.
  `tests/unit/test_recall_own_session_safe.py` holds both facts.

**Verdict: row 1 is complete.** Seven days, 1,339 recalls through the flagged path, clean signals,
and no dependency on the one behaviour it changes. Reported to the runtime in FR-49, with the
caveats: `idle in transaction` was never sampled during a recall, and the pipeline's recalls cannot
show a failure until FR-49 lands. The flag stays on here. Rows 2–6 can start, one at a time.
