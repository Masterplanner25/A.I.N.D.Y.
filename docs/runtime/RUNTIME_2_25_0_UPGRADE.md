---
title: "Runtime 2.25.0 adoption"
last_verified: "2026-10-02"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.25.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.25.0.md`. No schema change (head stays `0020`), no
ui-kit change. It answers our whole open register: **FR-48, FR-49 and FR-50**. Each ask is answered
below, with what was read off the running container on 2026-10-02.

## 1. The pin, and what is actually running (ask 1)

`pyproject.toml` `>=2.25.0,<3.0` and `constraints.txt` `==2.25.0`, moved together;
`test_runtime_dependency_contract.py` moves with them. Rebuilt and deployed.

| Check | Read |
|---|---|
| version and path, in the container | `2.25.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| `nltk` / `textstat` (§2: the runtime no longer installs them) | `nltk 3.10.3`, Required-by `aindy-apps-monolith, textstat`; `textstat 0.7.13`, Required-by `aindy-apps-monolith`. Ours since #391 |
| schema | none applied; `bootstrap-schema` ran clean at boot |
| authority negotiation default-on (§1) | no change here: `AINDY_AUTHORITY_NEGOTIATION=true` was already set |
| flags | `AINDY_MEMORY_RECALL_OWN_SESSION=true`, `AINDY_SYSCALL_IDEMPOTENCY_STRICT=1`, `AINDY_PLAN_STEP_REFERENCES=1` |

## 2. Our declared range, as the runtime now reads it (ask 4, DEBT-COMPAT-1)

`GET /api/version` → `compatibility.consumers`: `aindy-apps-monolith`, requirement `<3.0,>=2.25.0`,
upper bound present, **status `satisfied`**.

**The handoff's finding was real, and had a cause they could not see.** Our dev venv's installed
metadata read `>=2.9.0` even after a fresh `pip install -e . -c constraints.txt`. The pip-installed
`dist-info` was correct; a stale, gitignored **`aindy_apps_monolith.egg-info`** in the repo root, from an
old setuptools install, **shadowed it whenever Python ran from the repo root**, which is where
`aindy-runtime serve` and pytest run. Deleted. If it reappears: `rm -rf aindy_apps_monolith.egg-info`.

## 3. FR-48: every referenceable tool declares what it returns (ask 2)

`result_schema` on all 15 tools a later step may reference (not `genesis.message` or `task.complete`,
whose results the planner is told not to reference), kept in one table, `apps/_shared/tool_results.py`.

- **Closed schemas declare the REAL keys.** A node that lists `properties` refuses a path to any key it
  does not list (DEC-077), so a declaration copied from a description could refuse a correct reference.
  `search.query` returns `learning_context` and `history_id` beyond the five its description names; both
  are declared. Item shapes that are open-ended (memory nodes, leads) stay open with `additionalProperties`.
- **The planner's catalog line now ends in `returns={…}`.** `test_agent_tool_args_schema.py`'s parse of
  that line moved with it.
- **`test_agent_tool_result_schema.py`** holds it: every referenceable tool has a schema; each carries
  every key its description states; each tool that shapes its own result declares exactly those keys;
  and **run `615b67ea`'s plan (`"path": "results"` on `research.query`) is refused by
  `validate_plan_references`**, while `raw_result`, and `memory.recall` → `content.draft` by `nodes`, pass.

A refused plan fails run creation (DEC-078); it is not re-planned.

## 4. FR-49: recall failures, counted (ask 3)

`aindy_memory_recall_failures_total{site, stage}` is registered on the api's `/metrics/`, with no samples
at boot. Six of our recall sites now pass `site=` (`app.arm.code_analysis`, `app.masterplan.genesis`,
`app.search.research_flow`, `app.search.leadgen`, `app.search.memory_search`, `app.tasks.completion`); the
other three go through runtime functions that do their own recall and count under the runtime's own sites.

**The handoff's correction, recorded:** a failure *inside* the pipeline's recall was always logged at
WARNING as `[MemoryOrchestrator] recall failed`, so soak row 1's absence signal did cover the 1,332
pipeline recalls (`RUNTIME_2_24_0_UPGRADE.md` §8.1 said otherwise). The real gap was that its only
witness was a log line, lost with each container recreate. Now it is a counter.

**Soak row 1, the window the runtime asked for: started 2026-10-02T05:05Z on 2.25.0,** flag on. Zero
across every `stage` is the condition for flipping `AINDY_MEMORY_RECALL_OWN_SESSION` by default. Readout
on or after 2026-10-09. The counter resets on api recreate, so read `/metrics/` before each rebuild.

## 5. FR-50: fixed (and wider than filed)

`POST /apps/memory/recall` with only `query` now answers **200**: on 2026-10-02 it returned the owner's
*AI Search Optimization* and *AI Search Experiment* passages. We never shipped the
`"tags": [], "node_type"` workaround in code (it was a probe-only workaround), so there is nothing to drop.

## 6. Dependencies (§7)

OpenTelemetry moved to 1.45.0 / 0.66b0 inside the runtime. We pin no `opentelemetry-*` package
ourselves, so nothing moves here.
