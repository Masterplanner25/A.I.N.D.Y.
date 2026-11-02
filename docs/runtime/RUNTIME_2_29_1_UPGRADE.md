---
title: "Runtime 2.29.1 adoption"
last_verified: "2026-11-02"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.29.1 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.29.1.md` (tag `v2.29.1`, `c767c9f`, #872). No schema
change (head stays `0020`, contract `2026-09-20`), no ui-kit release (2.1.1 stays). We come from
2.29.0 (live since 2026-11-01 16:40Z, `RUNTIME_2_29_0_UPGRADE.md`), so the handoff's "if you are still
on 2.28.2" asks were already done there.

## 1. FR-56: the embedding sweep owns embedding (#871, DEC-104)

Our FR-56 (filed 2026-11-01): `enqueue_embedding` wrote a `memory.generate_embedding` row `pending` and
never submitted it whenever the scheduler was running, and those rows count against the admission caps.
On 2.29.1:

| Where `enqueue_embedding` runs | 2.29.0 | 2.29.1 |
|---|---|---|
| the scheduler instance (our api) | row written `pending`, never run | no row; the one-minute sweep embeds the node |
| no scheduler in the process (a booting process, a follower) | runs inline, row closed | unchanged |

The sweep also closes any open row for a node it embeds (`logs_closed` in its result).

**The rows already stranded are not changed by the upgrade.** The operator command settles them:

```bash
docker exec <api> aindy-runtime memory settle-embedding-logs        # dry run, reports only
docker exec <api> aindy-runtime memory settle-embedding-logs --yes  # settles
```

It settles only a row that is `memory.generate_embedding`, `pending`, `started_at` NULL, `attempt_count`
0, and whose node exists with `embedding_pending = false`. Each becomes `success` with
`result.superseded_by = "memory.embedding_sweep"`, and its execution unit goes `pending → executing →
completed`. A row whose node is still pending or was deleted is left and counted. Batches of 500.

**`--yes` writes the owner's database, so it is the owner's call.** Keep
`AINDY_ASYNC_MAX_CONCURRENT_PER_USER` and `_GLOBAL` unset until it has run.

## 2. The runtime's own `Dockerfile` upgrades setuptools (#870)

Nothing for us: our `Dockerfile` installs `aindy-runtime[mcp,security]`, which already carries
`setuptools>=84.1.0` (2.29.0's §2).

## 3. Done here

- **Pin and floor together:** `constraints.txt` `==2.29.1` and `pyproject.toml`
  `aindy-runtime[mcp,security]>=2.29.1,<3.0`, plus the contract test.
- **FR-56** marked shipped in `RUNTIME_FEATURE_REQUESTS.md`; CLAUDE.md's FR row and adoption pointer.

## 4. Rebuild and settle: done 2026-11-02, and the settle found nothing

1. **Identity counter, window 7** (2026-11-01 22:11:59Z → 11-02 03:55:59Z): no samples at all, so 0
   refused. As in window 6, the api's `/metrics` carried no syscall samples in the window.
2. **Rebuilt** (image `d7fb75f055eb`) and **recreated at 04:24:08Z**, which opens window 8. Healthy at
   04:24:57Z, 0 restarts, 16 plugins, 0 executing agent runs, empty `AgentContinuation` log.
3. **In-container:** `AINDY._version` 2.29.1 from `/usr/local/lib/python3.11/site-packages/AINDY`,
   setuptools 84.2.1.
4. **`memory settle-embedding-logs` dry run: examined 0, settled 0, node pending 0, node gone 0.**
   `--yes` was not run.

**Why 0: FR-56's numbers came from the wrong table.** The 2,387 `pending` rows counted on 11-01 were
in `automation_logs`, our mirror of `job_logs` (`job_log_sync_service.py`). In `job_logs` all 2,387
were already `failed`, *"Stale: never started within 1 hour of creation"*, written by the runtime's
`_cleanup_stale_logs` (the last at 11-01 19:41Z). The admission caps count `job_logs`, so they were
never at risk beyond the last hour's rows. The cleanup writes `job_logs` without our sync, so the
mirror stayed `pending`: `JOB-LOG-MIRROR-STALE-1`.

**What 2.29.1 did fix is visible:** 0 `job_logs` rows created since the recreate, 0 active rows
(`pending`/`running`/`deferred`), 0 nodes pending.

**The mirror was corrected the same day** (owner's OK): the 2,387 drifted `automation_logs` rows took
`status`, `error_message`, `started_at`, `completed_at` and `attempt_count` from their `job_logs` row.
0 drift after.

**The async caps:** nothing in `job_logs` holds a slot now, so setting
`AINDY_ASYNC_MAX_CONCURRENT_PER_USER`/`_GLOBAL` is safe. Whether to set them is the owner's call.

**For the runtime:** the four counts your handoff's ask 3 wanted are above (all 0), with the reason
in FR-56's *Correction*. **One question, your call:** should `memory settle-embedding-logs` also take
`job_logs` rows that are `memory.generate_embedding`, `failed` with *"Stale: never started within 1
hour of creation"*, `attempt_count` 0, and whose node is embedded? There are 2,387 here. They record as
failed work the sweep did. If not, we leave them as they are.

Still owed here: after a day, check that no new `memory.generate_embedding` row has appeared in
`job_logs`.
