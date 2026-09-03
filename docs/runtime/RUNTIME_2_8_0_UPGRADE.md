---
title: "Runtime 2.8.0 upgrade — adoption"
last_verified: "2026-09-03"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.8.0 upgrade — adoption

Floor moved `>=2.7.0,<3.0` → `>=2.8.0,<3.0`.

**This one changes the schema. 2.7.0 did not.** Do not pattern-match off the release we
adopted yesterday.

---

## 1. ★★ The schema step — and why our container will stop rather than crash-loop

2.8.0 adds one additive, nullable column: `flow_runs.graph_signature`, runtime Alembic
revision `0018`. Verified against the migration itself rather than the handoff's summary:

```sql
ALTER TABLE flow_runs ADD COLUMN IF NOT EXISTS graph_signature VARCHAR(64);
```

`revision = "0018"`, `down_revision = "0017"`. Our deployed database is stamped at `0017`
(confirmed in the 2.7.0 bring-up log: *"stamped alembic_version_runtime to revision
0017"*), so it chains directly. Additive, nullable, guarded by `IF NOT EXISTS` and a
table-existence check, with a symmetric guarded downgrade — consistent with the
idempotency rule in `docs/operations/MIGRATION_POLICY.md`.

**This is runtime-owned.** It lands in `alembic_version_runtime`, not our
`alembic_version` line. No app migration is needed and none was written.

### What actually happens on our next bring-up

The handoff warns that a bare `bootstrap-schema` exits `3` on additive drift, and that
under `set -e` with `restart: unless-stopped` this is a crash loop that looks like a
broken image. **We are already hardened against that** — `docker/entrypoint.sh` branches
on the exit code and has since 2.3.0, written after adopting 2.1.0 produced exactly that
crash loop here on 2026-08-15 (FR-13 / FR-14).

So the failure mode is not a loop; it is a **clean stop with instructions**:

```
[entrypoint] bootstrap-schema exit 3: an ADDITIVE reconcile is required.
[entrypoint] This is the safe-to-automate case — columns/indexes are added, never dropped.
[entrypoint] Either set AINDY_BOOTSTRAP_RECONCILE=1 and restart, or apply it out-of-band:
[entrypoint]   docker compose run --rm --no-deps --entrypoint aindy-runtime api bootstrap-schema --reconcile
```

`docker-compose.prod.yml:64` sets `AINDY_BOOTSTRAP_RECONCILE: "${AINDY_BOOTSTRAP_RECONCILE:-false}"`,
so the default is off and the variable is overridable per invocation.

### We are deliberately NOT flipping that default

The runtime now certifies exit `3` as safe to automate, so defaulting it on would be
defensible. The entrypoint keeps it opt-in on purpose, and the comment there states why:
a production schema change should stay *a decision someone makes* rather than a side
effect of a container restart. Turning it on as part of a routine version bump would
quietly delete that property for every future release, not just this one.

**So the schema step is an operator action, and this is it:**

```bash
# one-off, with the stack down or up — applies the additive column and exits
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml \
  run --rm --no-deps --entrypoint aindy-runtime api bootstrap-schema --reconcile

# or, for a single bring-up only
AINDY_BOOTSTRAP_RECONCILE=1 docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml up -d
```

Only exit `3` is safe to automate. `4` (offline migration) and `5` (manual repair) need a
person, and `4` deliberately wins over `3` so no entrypoint can auto-reconcile a database
that needs one. The entrypoint already refuses both.

---

## 2. What the column buys — and why it will not quarantine anything on upgrade

A suspended `FlowRun` used to be restored against whatever flow definition the process
held at that moment, so a node renamed or an edge rerouted between suspend and resume
executed against a definition the run was never planned for — silently, reported as
success. A run now fingerprints its flow's *shape* at start and quarantines on mismatch:
`status="dead_letter"`, reason beginning *"flow topology changed while run was
suspended"*.

It covers node identity and edge topology. It deliberately does **not** cover node
bodies, node config, or branch predicates — a changed predicate that reroutes control
flow is not caught. That is the narrow version, and narrow is why it stays switched on.

**Nothing is quarantined by the upgrade itself:** rows predating the column have no
fingerprint, and absent means "cannot tell" and proceeds as before.

**App-side impact: none, checked rather than assumed.** We never reference
`graph_signature` (runtime-owned table). The only place we touch this vocabulary is
`client/src/components/app/Assistant.jsx:20`, which lists `dead_letter` among terminal
statuses — it keys on *status*, not on the reason string, so a new reason passes through
unchanged. The operator DLQ surface displays reasons rather than enumerating them.

---

## 3. §3 does not apply to us

`AINDY_ASYNC_SCHEDULER_DISPATCH` is no longer refused under `EXECUTION_MODE=distributed`,
but it is **opt-in there and does not take the default**. We run `thread`
(`RUNTIME_2_7_0_UPGRADE.md` §1 established that our compose never sets `EXECUTION_MODE`,
unlike the runtime's own), where this half shipped in 2.7.0 and its default has not moved.

Nothing to do, and nothing changed for us.

---

## 4. No dependency pins moved

The handoff states this and it holds: `nltk` stays at `3.10.3`, so the
`PYSEC-2026-3740` exemption added in `RUNTIME_2_7_0_UPGRADE.md` §3 remains accurate and
needs no revisiting. `EffectRecord.status` gains `partial` and `unknown` as *vocabulary*
only — no migration, nothing emits them yet, and the syscall envelope is still
`success | error`.

---

## 5. Steps taken

1. `pyproject.toml` floor → `aindy-runtime>=2.8.0,<3.0`.
2. `tests/unit/test_runtime_dependency_contract.py` → `"<3.0,>=2.8.0"`, in lockstep.
3. No entrypoint change — it already handles exit `3`.
4. No compose change — the reconcile default stays off, deliberately (§1).

---

## 6. Verification

Local runtime code is exactly v2.8.0: the sibling checkout is one docs commit past the
tag, and `git diff --name-only v2.8.0..HEAD` filtered of `*.md` and `docs/` is empty.

| check | result |
|---|---|
| `test_runtime_dependency_contract.py` | pass |
| app-profile subset (7 files, `-m app_profile`) | 55 passed |
| boot smoke | `default-apps`, `app_plugins_loaded=True`, count **16** |
| `FlowRun.graph_signature` present in model metadata | **True** |
| `scripts/check_app_imports.py` | 37 declared, 0 undeclared |
| `ruff check apps/ tests/` | clean |

### What this does not establish

**The schema step has not been executed.** The local stack was brought down for unrelated
reasons (host memory exhaustion — see below), so `bootstrap-schema` has not been run
against the deployed database on this version. The exit-3 path is verified by reading the
entrypoint, not by observing it fire.

The quarantine in §2 has not been exercised. Doing so needs a suspended run and a
deliberately altered flow shape; nothing here proves the guard fires or that it stays
quiet when it should.

---

## 7. Note on the deployment state at adoption

At the time of this adoption the local stack is **down**, and not because of this
release. The host has 7.7 GB of RAM against a 23.6 GB commit charge; the 2.7.0 bring-up
reached `serve` and answered `/api/version` correctly, then degraded — `/health` 500,
14 postgres cluster reinits, ~55k hard page faults/sec. Containers totalled ~443 MB, so
the pressure is host-side, not the stack's.

Consequence for whoever brings this up next: **do the reconcile from §1 first**, and do
not read a slow or unhealthy boot as evidence about 2.8.0 until
`\Memory\Available MBytes` is healthy. That is the same misattribution
`CLAUDE.md`'s scheduler-saturation section warns about.
