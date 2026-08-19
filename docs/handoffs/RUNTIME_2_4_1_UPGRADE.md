---
title: "Upgrading to aindy-runtime 2.4.1"
last_verified: "2026-08-19"
api_version: "1.0"
status: current
owner: "platform-team"
---

# Upgrading to `aindy-runtime==2.4.1`

**Two handoffs, one upgrade.** `2.4.0` is where the behaviour changed; `2.4.1` is a patch on top
that fixes a `nodus-lang` isolation bug and carries the grouped dependency bumps. The runtime team
is explicit: **upgrade to 2.4.1, not 2.4.0.**

Floor moved to `>=2.4.1,<3.0`.

---

## TL;DR — every documented caveat, checked against this repo

The 2.4.0 handoff enforces scopes on **91 of 126 routes** (previously 29). That sounds alarming
and is not, for us — but "not for us" is a measurement, not an assumption:

| Caveat | Our exposure |
|---|---|
| §1.2 platform API keys need specific scopes | **Zero keys exist.** `select count(*) from platform_api_keys` = 0 |
| §1.3 CLI `nodus run/upload` needs `flow.execute` on a platform key | Not used; no key to hold a scope |
| §1.1 JWT sessions | Unaffected by design, and upstream tests drive the real routes to prove it |
| §2 `nodus-lang` 5.x deny-by-default embedding | **We construct `NodusRuntime` nowhere** |
| 2.4.1 §1 warm-pool guest-memory leak | **`AINDY_NODUS_WARM_POOL` is unset** → latent, never live |
| 2.4.1 §2 `Mako` 1.4 raises floors to py 3.10 / MarkupSafe 2.0 | py `>=3.11`, MarkupSafe `3.0.3` |
| 2.4.1 §2 `prometheus-fastapi-instrumentator` handler labels | **Not imported anywhere in `apps/`** |
| 2.4.1 §2 SQLAlchemy 2.0.52 `aliased()` / `to_metadata()` | **Neither API used in `apps/`** |

Nothing required an app-side change. The pin move is the whole upgrade.

---

## 1. The security release, and why it lands softly here

`2.4.0` closes `KEY-SCOPE-ESCALATION-1`, which was serious: **a `flow.read`-only API key could
mint itself a `platform.admin` key, promote its own user row to admin, and rotate the platform JWT
signing key** — choosing the new secret, and therefore able to forge tokens for any user. All
demonstrated end to end against real PostgreSQL rather than inferred.

It lands softly here for one reason only: **we have never issued a platform API key.** That is
luck of usage, not of design, and it is worth writing down because the next deployment of this app
may not share it.

### The one part of §1.4 that does apply to us

The handoff recommends reviewing `users.is_admin` for accounts you did not promote yourself.
Checked 2026-08-19:

| Account | Created | Note |
|---|---|---|
| `shawnknight@the-master-plan.com` | 2026-08-17 | the owner's real account, promoted deliberately |
| `admin@local.test` | 2026-07-23 | **legacy verification throwaway** |
| `shawn@local.test` | 2026-08-05 | **legacy verification throwaway, despite the name** |

Before this release, admin mostly meant "can reach `/platform`". **After it, admin derives
`platform.admin`, which satisfies every gate in §1.2** — including `/platform/keys` and
`/platform/ops/rotate-secret-key`. Two forgotten test accounts now hold the strongest authority
the system grants.

**Recommended: demote or delete both.** Not done here — deleting users is destructive, and
`local-stack-accounts` records that purge scripts must never target `is_admin`. It is a decision,
not a cleanup.

---

## 2. `nodus-lang` 4.2.0 → 5.0.4 is a language major, and was checked as one

The runtime pins it exactly, so this arrives whether or not we want it. A major version of the
language our `.nd` workflow is written in deserves more than a version-number glance:

```
$ nodus check apps/analytics/nodus/reasoning_apply_v1.nd
apps/analytics/nodus/reasoning_apply_v1.nd: OK
```

Verified with the **venv's** CLI, not the system one — both happen to be 5.0.4, but that is a
coincidence worth not relying on. It is the only `.nd` in the repo.

### The isolation bug is the interesting part of 2.4.1

`nodus-lang <= 5.0.2` bound `GLOBAL_MEMORY_STORE` at **import**, so every `NodusRuntime` in one
process shared a single guest memory dict — and `memory_put` / `memory_get` are guest builtins any
`.nd` script can call. With a warm worker pool, two tenants' scripts could read each other's
values.

**We were never exposed, because `AINDY_NODUS_WARM_POOL` is off.** But the runtime team's note on
*why their own docs missed it* is the part worth carrying:

> `nodus_worker_pool.py` asserted that a reused process *"never leaks state between runs"*, on the
> strength of `run_one` rebuilding per-request state. True of the state the runtime owns, false
> for the channel that mattered: **`run_one` cannot reset a module global living inside a
> dependency.**

That generalises, and it has a direct consequence for us: **before ever enabling
`AINDY_NODUS_WARM_POOL`, re-run the upstream isolation test** — 2.4.1 §4 attaches it as a
precondition. Had we soaked that flag a week ago, we would have soaked it on a pin that made the
pool's own safety claim false.

---

## 3. Verification performed

| Check | Result |
|---|---|
| Full unit suite | green |
| Contract / boundary / model / bootstrap tests | green |
| App-profile boot smoke | `default-apps`, `app_plugins_loaded=True`, 16 plugins |
| `nodus check` on every `.nd` in the repo | 1 file, OK |
| Installed set | runtime 2.4.1, nodus-lang 5.0.4, Mako 1.4.1, SQLAlchemy 2.0.52 |

**One observation recorded rather than dismissed.** A single early run logged
`System started with degraded domains: search` and failed
`test_known_flow_results_registered`. It did not reproduce: the same file passes alone, the same
five-file combination passes on re-run, and the full unit suite is clean with zero occurrences of
the warning. Recorded because a degraded domain is a real signal and this repo has a documented
habit of attributing load-dependent flakes to whatever changed most recently — **if `search`
degrades again, this note is the first data point, not the discovery.**

---

## 4. Not in this release, so nobody goes looking

- **No feature requests moved.** `FR-6` items 2+3 and `FR-14`'s remaining half are exactly where
  `2.3.0` left them. This release is authorization, dependency adoption and packaging.
- **No schema change.** Contract `2026-08-15.1`, Alembic head `0016`. `bootstrap-schema` exits 0.
- **No new env var, no route added, no consumer pin movement** (`recommended_runtime_requirement`
  stays `>=2.0,<3.0`).

### Packaging now ships what it should

`llms.txt` / `llms-full.txt`, `CONTRIBUTORS.md`, and the Rust scorer's *source* (not the compiled
artifact — a `.pyd` inside a `py3-none-any` wheel installs a broken binary for anyone on a
different OS/arch). Also fixed: `recursive-include AINDY *.json` had been sweeping ~200 Cargo
fingerprint files, some embedding the building machine's absolute paths. Never reached PyPI, but
it was a local-build hazard.

---

## 5. Still open upstream

- **`TOOL-SEAM-ISOLATION-1`** — the one actionable P0: `execute_tool` runs tools in-process with
  the live DB session, so authority checks at that seam are advisory with respect to the code that
  runs next.
- **`GUEST-CONFINE-1` residual** — the guest VM is confined, but nothing sets its `cwd`, so
  `allowed_paths` inherits the server's working directory (`/home/aindy` in Docker, which holds
  `alembic/`). The escape is closed; the *bound* is an undeclared inherited default.
- **`IDEM-12`** — a second `agent.undo` re-invokes every compensator. Latent only because zero
  compensators are registered.
- **`ROUTE-EFFECT-BYPASS-1` D**, **`CAPABILITY-PROVIDER-TIMEOUT-1`** — see 2.4.0 §8.

**Next available FR number: `FR-18`.**
