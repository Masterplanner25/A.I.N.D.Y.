---
title: "Runtime 2.29.2 adoption"
last_verified: "2026-11-04"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.29.2 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.29.2.md` (tag `v2.29.2`, `ec1e40d`, #883). No schema
change (head stays `0020`, contract `2026-09-20`), no ui-kit release (2.1.1 stays). We come from
2.29.1 (live since 2026-11-02, `RUNTIME_2_29_1_UPGRADE.md`).

**Released through A.I.N.D.Y.** The release handoff (`fb8c9490`) was requested at 04:36:56Z on
2026-11-04. The run reached the `production` gate and the gate email went out at 04:44:34Z. The owner
approved on the Collaborator card at 04:47:31Z, and the handoff was `done` at 04:49:13Z. PyPI has the
files from 04:47:45Z.

## 1. pydantic 2.14.2: two advisories (#881)

GHSA-qpmf-fgh3-ff25 and GHSA-3r8g-cqwr-jr29 need `extra='allow'` with a typed `__pydantic_extra__`,
or a `TypedDict`/dataclass with aliased fields and extra data allowed. **Our tree has none of them.**
Searched 2026-11-04, outside `client/`: no `extra='allow'`, `Extra.allow`, `__pydantic_extra__`,
`extra_items`, `pydantic.dataclasses`, `model_validate_json` or `alias_generator`. We pin none of the
runtime's moved dependencies (pydantic, openai, OpenTelemetry, pymongo) ourselves, so the runtime's
pins apply as they are.

## 2. The stale-log cleanup closes what it fails (#882, DEC-105)

This closes the drift half of our `JOB-LOG-MIRROR-STALE-1`. A stale row's execution unit now goes
`failed` with it, and `job_log.written` fires, which our `_handle_job_log_written` syncs into
`automation_logs`. The rows already failed get no event; we corrected those by hand on 11-02.

**Our settle question (2.29.1 §4) is answered: no.** `memory settle-embedding-logs` will not take the
2,387 `failed` embedding rows. "Never started" is true of them, and they hold no admission slot. We
leave them as they are.

## 3. The asks, read 2026-11-04 ~04:52Z, before the rebuild (2.29.1 container, up since 11-02 06:20:56Z)

1. **Pin, rebuild, check:** see §4.
2. **Stranded execution units: 2,387.** The handoff's query (unit `pending`, `job_logs` row
   `failed`) returns 2,387, all `memory.generate_embedding`, created 2026-07-22 23:52Z → 2026-11-01
   18:08Z. That is every row the stale cleanup failed before 2.29.1. Your call on whether it is large
   enough for a command.
3. **`aindy_memory_recall_failures_total`: no samples** over 2026-11-02 06:20:56Z → 11-04 04:52Z
   (about 46.5 h). The volume beside it is low: 57 authenticated requests (`execution.completed` with
   a user; the pipeline recalls after each), and no agent `memory.recall` steps. The api log had 0
   `recall failed` warnings in the same window. **We already run `AINDY_MEMORY_RECALL_OWN_SESSION=true`**
   (on since 2026-09-23; soak row 1 closed 09-30 with 1,332 pipeline recalls clean). So for us the
   default change changes nothing. With 57 requests, this window adds little to the 09-30 reading.
4. **`closing superseded embedding logs failed`: absent.** 0 occurrences in the api log since the
   2.29.1 recreate (2026-11-02 04:24:08Z, through the 06:20:56Z recreate to now). No `logs_closed`
   value appears in the log either. 128 memory nodes were created in the window and all were embedded,
   but none had an open `job_logs` row to close, so the Postgres JSON filter ran with nothing to match.
   It has not been tested here on a real row.

## 4. Rebuild

Owed after this PR merges. Note the build cache was pruned on 2026-11-04, so this build re-downloads
everything. Before the recreate, read `aindy_payload_identity_mismatch_total` (window 9). After it,
run the handoff's check:

```bash
docker exec <api> python -c "import AINDY, AINDY._version as v, pydantic; print(v.__version__, list(AINDY.__path__), pydantic.VERSION)"
# expect: 2.29.2 ['/usr/local/lib/python3.11/site-packages/AINDY'] 2.14.2
```
