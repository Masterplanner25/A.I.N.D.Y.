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

## 4. Rebuild and settle

Owed after merge, in this order:

1. Read `aindy_payload_identity_mismatch_total` (window 7, from 2026-11-01 22:11:59Z); the recreate
   resets it.
2. Rebuild (a pin move re-downloads the dependency layer) and recreate the api.
3. In-container check: `AINDY._version` 2.29.1 from site-packages, setuptools ≥ 84.1.0.
4. Health, 16 plugins, 0 restarts, the `AgentContinuation` log.
5. `memory settle-embedding-logs` dry run. Expected on the 11-01 numbers: about 2,387 to settle, 0 left.
6. `--yes` on the owner's word. Record the four counts here (examined, settled, node pending, node
   gone) and send them to the runtime.
7. After a day: no new `memory.generate_embedding` row `pending` with `started_at` NULL for longer than
   a minute.
