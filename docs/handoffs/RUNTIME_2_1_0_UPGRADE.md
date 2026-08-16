---
title: "Upgrading to aindy-runtime 2.1.0"
last_verified: "2026-08-15"
api_version: "1.0"
status: current
owner: "platform-team"
---

# Upgrading to `aindy-runtime==2.1.0`

**Released 2026-08-15. Minor — and the thing to be careful about is that nothing forces you to
notice it.** `recommended_runtime_requirement` still reports `>=2.0,<3.0`, and our pin was
already `>=2.0.0,<3.0`, so **2.1.0 would have arrived on the next `--no-cache` rebuild with no
decision made**.

That is the whole difference from 2.0.0, which forced a conversation by moving the pin. This
release does not. So the work here is *checking behaviour changes*, not performing an upgrade —
and raising the floor so the version we run is a choice rather than a side effect.

Every claim below was checked against **this** stack — the running containers and the live
database — on 2026-08-15. Where something needs no action, that is a measured result.

---

## TL;DR

| | Action |
|---|---|
| Version pin | **Moved deliberately** — `>=2.1.0,<3.0`, so a rebuild can't silently change the minor under us |
| Database / migrations | **A required manual step on any existing DB** — `bootstrap-schema --reconcile`, or the container crash-loops. See §1a |
| `memory_agents_list` owner-scoping | **None now**, but `AgentRegistry.jsx` consumes it via a runtime-owned route — see §2a before building on FR-12b |
| `/health/deep` bus string | **None.** We don't read that field anywhere |
| Admin agent route status codes | **None.** Referenced only in a walk log, never called |
| `capability_scope` now a tuple | **None.** Zero references in `apps/` or `client/` |
| Reserved-namespace hijack | **Checked — no drift.** All 7 system rows intact |
| FR-11 / FR-12 / FR-12b / FR-13 | **All shipped.** Closed in the tracker; adoption is separate work |

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml build --no-cache api
# REQUIRED on an existing database, before the api can start — see §1a:
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml \
  run --rm --no-deps --entrypoint aindy-runtime api bootstrap-schema --reconcile
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml --profile mail up -d api
```

**Both compose files, every time** — a single-service `up` without the overlay recreates the api
without `MONGO_URL` and silently degrades the social layer.

---

## 1a. The upgrade does not apply itself, and the failure mode is a crash loop

**This contradicts the handoff and was found the hard way, on this stack.**

`APP_HANDOFF_v2.1.0.md` §1 says migration `0016` *"only widens what is accepted … so there is
nothing to backfill and no data to prepare"*, and FR-13 calls the new columns *"purely additive,
no backfill"*. Both statements are true about **data**. Neither is true about **deployment**.

Our entrypoint runs the runtime's own recommended command, bare, under `set -e`
(`docker/entrypoint.sh:32`). On 2.1.0 against an existing database it exits non-zero:

```
[entrypoint] runtime schema: aindy-runtime bootstrap-schema
error: runtime-owned schema is not ready: Runtime-owned schema requires an explicit additive reconcile:
  Runtime table 'agents' is missing required column 'metadata'.
  Runtime table 'agents' is missing required column 'updated_at'.
Re-run with --reconcile for an additive column/index fix, or perform the required offline
migration before retrying.
```

`set -e` turns that into an exit, `restart: unless-stopped` turns the exit into a **crash loop**,
and the api never reaches `serve`. The stack was down until reconciled by hand.

The refusal is *correct behaviour* — `bootstrap-schema` deliberately will not alter tables without
an explicit opt-in, which is the right default for a command that might run against production.
The gap is that **the runtime recommends `bootstrap-schema` as the deploy entrypoint command**,
and that recommended entrypoint breaks on every additive runtime schema release. Filed as
**FR-14**.

The fix applied here:

```
ok: reconciled runtime-owned tables to packaged metadata.
ok: stamped alembic_version_runtime to revision 0016.
```

`agents.metadata` (`jsonb`, nullable) and `agents.updated_at` (`timestamptz`, nullable) created;
all 7 rows intact. **The agents table was CSV-snapshotted first** — additive-only was also the
claim during the 2.0.0 upgrade, where the verified-flag backfill silently did not run (FR-8).
Nothing was lost this time, but the snapshot cost nothing.

**Whether our entrypoint should pass `--reconcile` itself is an open decision** — see §7.

---

## 1. Why the floor moved even though nothing required it

The pin `>=2.0.0,<3.0` already admits 2.1.0. Leaving it there is defensible and we did not.

The behaviour changes in §2 are small but real, and they are *version-conditional*. With a floor
of `2.0.0`, "which runtime is this?" has different answers in the container, a contributor's
venv, and CI, and nothing surfaces the difference. Raising the floor to `2.1.0` costs one line
and makes the answer deterministic — which is the same reason every prior adoption here raised
it (`1.6.0`, `1.8.0`, `1.10.2`, `2.0.0`).

`tests/unit/test_runtime_dependency_contract.py` asserts the **exact specifier string**, so the
pin and the test move together or CI fails. That is deliberate: it makes a silent pin drift
impossible.

---

## 2. The four behaviour changes, and why each is inert here

Checked individually rather than assumed, because "probably fine" is how the FR-9 email
regression got shipped.

### 2a. `memory_agents_list` is owner-scoped — the one that lands on our code

The handoff flags this as landing directly on us, and it is right that we wire it:
`apps/memory/bootstrap.py:96` registers `"memory_agents_list": "memory_agents_list_result"`.

| | |
|---|---|
| Before | every active agent, to every caller |
| After | `owner_user_id IS NULL OR owner_user_id = <caller>` |

**It changes nothing today** — every agent row is un-owned (`owner_user_id` NULL on all 7), so
`owner_user_id IS NULL OR owner_user_id = <caller>` matches every row for every caller.

**But it is consumed, and there is a live UI on the other end of it.** Grepping this repo for
`memory_agents_list` returns exactly one hit — the registration above — which makes it look
unconsumed. It is not. The consuming route is **runtime-owned**, which is why an app-repo grep
misses it:

```
client/src/components/platform/AgentRegistry.jsx:459   getAgents()
client/src/api/agent.js:11                             GET /apps/memory/agents
AINDY/routes/memory_router.py:525                      @router.get("/agents")
  -> _mem_run_flow("memory_agents_list", {}, db, str(current_user["sub"]))
```

So the trap is **not** hypothetical future work — the roster UI already exists and already calls
the newly scoped flow. It renders identically today and will **silently narrow** the moment any
agent gets an `owner_user_id`, which is exactly what FR-12b makes possible for the first time.

The failure mode is quiet: no error, no empty state, just a roster that stops showing agents
belonging to other users. **Whoever builds on FR-12b owns deciding what `AgentRegistry` should
show** — every agent visible to an admin, or only the caller's. That is a product decision the
scoping change forces, not a bug to fix.

> **Method note.** The first pass of this section claimed nothing consumed the flow, on the
> strength of a single-repo grep. That is the same inference error recorded in
> `SESSION_HANDOFF_2026-08-06.md` §3 and §11 — concluding absence from a search that could not
> have found the thing. In a two-repo split, "no reference in `apps/`" does not mean "no
> caller"; the runtime owns routes mounted under `/apps/*`.

### 2b. `/health/deep` reports the bus `degraded`, not `disabled`

We don't read it. `grep` for `health/deep` across `apps/`, `client/src` and `scripts/` returns
only two unrelated `event_bus` hits (`apps/arm/routes/arm_router.py` publishing
`arm.config.updated`, and two diagnostic scripts calling `_start_event_bus`).

The underlying fix is worth knowing anyway: three consecutive failed publishes used to latch the
bus off **permanently**, so one transient Redis blip ended cross-instance WAIT/RESUME for the
life of the process. It now suspends and recovers on a circuit breaker
(`AINDY_EVENT_BUS_PUBLISH_RECOVERY_SECS`, default 60).

### 2c. Admin agent routes return real status codes

`POST /platform/admin/agents/register` with a reserved namespace is now `409`;
`DELETE /platform/admin/agents/{missing}` is now `404`. Both were previously `500`
`{"error": "internal_error"}`.

Nothing here calls them — the only matches in the repo are three lines of
`docs/handoffs/FRONTEND_WALK_LOG.md` describing them.

**This is our own documented pattern showing up in the runtime**: a 4xx raised before pipeline
entry served as an opaque `internal_error`. It caused four of seven defects in our frontend walk
and is now guarded in our CI. Same shape, different repo.

### 2d. `TenantContext.capability_scope` is a `tuple`

Only mutation raises; `in`, `len`, iteration and `has_capability` are unchanged. Zero references
to `capability_scope` in `apps/` or `client/src`, so there is nothing to change.

---

## 3. The reserved-namespace hijack — checked, clean

FR-12's writeup surfaced a real vulnerability in the pre-2.1.0 admin route: the seven platform
system namespaces were unreserved, so registering with `memory_namespace: "runtime"` took the
**idempotent-update** branch and silently rewrote the platform's own Runtime agent row — name,
type and description — for anyone with admin on the deployment. Boot did not repair it, because
the seed only inserted when the row was absent.

Queried on this stack 2026-08-15:

```
memory_namespace |   name   | agent_type | is_active | owner_user_id
-----------------+----------+------------+-----------+---------------
 arm             | ARM      | system     | t         |
 genesis         | Genesis  | system     | t         |
 memory          | Memory   | system     | t         |
 nodus           | Nodus    | system     | t         |
 platform        | Platform | system     | t         |
 runtime         | Runtime  | system     | t         |
 sylva           | SYLVA    | system     | t         |
```

Seven rows, all `system`, all active, none owned, all names matching the platform spec. **No
drift.** Worth having checked rather than assumed — a rewritten row would have been invisible
until something read it, and `sylva` in particular is a namespace we already reasoned about when
naming the agent face.

---

## 4. What this unblocks, and what we deliberately did not build

FR-12 + FR-12b give us the agent registration API whose absence was the blocker in
`TERMINAL_AGENT_SCOPE.md` §4a, and FR-13 gives `agents.metadata` / `updated_at` — together, the
"identity outliving the vendor" shape that FR-13 argued for.

**None of it is wired in this PR.** Adopting a runtime version and building a product surface on
it are separate pieces of work, and mixing them makes both harder to review. The adoption is
here; the surface belongs with the Collaborator face work.

One contract detail to carry into that work, because it is easy to get backwards:
**`memory_namespace` is derived (`u:<user_id>:<slug>`), not accepted.** The runtime's reasoning is
sound — a caller-chosen namespace would have to `409` on a row the caller cannot see, which is a
cross-tenant existence oracle. That is the same class of finding as the enumeration-oracle
question in our own auth walk.

---

## 5. Verification performed

| Check | Result |
|---|---|
| App-profile boot smoke on 2.1.0 | `boot_profile=default-apps`, `app_plugins_loaded=True`, `app_plugin_count=16` |
| App-profile test subset + dependency contract | 55 passed |
| Cross-app import boundaries | `scripts/check_app_imports.py` clean |
| Live `agents` table | 7 system rows, no drift (§3) |
| Image rebuild | `--no-cache`, `aindy-runtime==2.1.0` baked |
| Schema reconcile | required (§1a) — reconciled, `alembic_version_runtime` = `0016` |
| Post-recreate | healthy in ~25s, 16 plugins, `MONGO_URL` present, `aindy-runtime==2.1.0` |
| Data after reconcile | users 25, tasks 8, agents 7 — unchanged |

---

## 6. Open on the runtime side that we should track

**`GUEST-CONFINE-1` (P0, demonstrated) — this one is ours to know about, because we run Nodus
scripts.** A guest script executed through the runtime reaches `subprocess`, network and the host
environment **without passing the syscall dispatcher, the capability token, the effect ledger or
the egress guard**. Demonstrated, not inferred: a guest script created a file on the host
filesystem.

The sandbox-escape gate's "17/17 PASS" does **not** cover this — that suite certifies the Tier-2
extension sandbox reached through `plugin_host.py`, and the guest VM is a different seam that has
never been in its scope. Both statements are true and not in conflict.

**Until it ships: treat Nodus script content as trusted input.** It arrives through an
authenticated route, but it is data, not deployed code. Recorded in `TECH_DEBT.md`.

Also open, worth knowing rather than acting on:

- **`IDEM-11`** — the at-most-once effect gate is off by default and only one registered syscall
  declares its execution guarantee. Duplicate-effect exposure in default configuration is real.
- **`HTTP-SCOPE-GAP-1`** — scope checks reach a small minority of HTTP routes.
- **A JWT will stop bypassing scopes** in a later release. Today `enforce_api_key_scope` gates
  API-key callers only, so an interactive session is *more* privileged than any API key. **The
  runtime team asked for our view on which scopes the UI actually needs** — that is an open
  question for us to answer, not a change to absorb.

### One correction back to the runtime team

The handoff says *"Your `FR-7` status is stale … only the document is behind"* and *"You run
2.1.0"*. Neither is true of this repo as of 2026-08-06: `RUNTIME_FEATURE_REQUESTS.md` has carried
**`FR-7 — ✅ CLOSED in 2.0.0`** since then, with all four fixes verified against the installed
wheel and line numbers recorded. And we were on **2.0.1** until this PR. No action needed on our
side; flagging so the note isn't repeated a third time.

**Next available FR number: `FR-15`** — FR-14 was filed from this upgrade (§1a).

---

## 7. Decided: the entrypoint reconciles only when told to

**Resolved 2026-08-15 — option C.** `docker/entrypoint.sh` now reads
`AINDY_BOOTSTRAP_RECONCILE` (default **off**):

- **unset/false** — bare `bootstrap-schema`, as before, but a refusal now prints the exact remedy
  instead of scrolling the raw runtime error forever.
- **1/true/yes/on** — `bootstrap-schema --reconcile`, so an additive upgrade applies unattended.

Wired in `docker-compose.prod.yml` as `${AINDY_BOOTSTRAP_RECONCILE:-false}`, so it is settable
from `.env` on a local or dev stack and stays off in production. The reasoning is the same as the
Mailpit profile gate: **make the convenient behaviour available and non-default**, so nothing
surprising happens where it matters.

> **What we deliberately did NOT change: `restart: unless-stopped`.**
> A bounded policy (`on-failure:5`) would surface a schema refusal in seconds instead of looping.
> It would also stop the stack coming back after a host reboot — which is precisely what recovered
> this deployment twice during the August power cuts. Unattended reboot recovery is worth more
> than a faster failure signal, and with the reconcile flag available the crash loop has a remedy
> that does not cost it.

### The options, for the record

Not obvious at the time, because the risks genuinely differ.

`docker/entrypoint.sh:32` runs `aindy-runtime bootstrap-schema` bare. §1a is what that costs on an
additive schema release.

| | Behaviour | Cost |
|---|---|---|
| **A — leave it bare** | Every additive runtime release crash-loops the container until someone runs `--reconcile` by hand | Safe, loud, and exactly what just happened. Fine for one operator; bad for an unattended deploy |
| **B — always `--reconcile`** | Additive DDL applied automatically at boot | Never blocks a deploy. But it silently alters a production schema on container start, and it fires on *every* boot, not just upgrades |
| **C — opt-in env var** | e.g. `AINDY_BOOTSTRAP_RECONCILE=1`, set in compose for dev, unset in prod | Keeps prod explicit while local/dev stops breaking. One more knob |

B stayed defensible to the end, because the runtime *already* self-migrates its own schema during
`serve` — the real inconsistency is that `bootstrap-schema` is stricter than the command running
immediately after it. C wins on blast radius, not on elegance.
