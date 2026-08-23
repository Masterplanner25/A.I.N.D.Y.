---
title: "Runtime 2.6.0 Upgrade — adoption plan (2.4.1 → 2.6.0, through 2.5.0)"
last_verified: "2026-08-22"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.6.0 upgrade — adoption plan

**Status: EXECUTED 2026-08-23.** The stack runs `aindy-runtime 2.6.0`, schema at
`alembic_version_runtime=0017`. Results in §8; §7 is still the rollback.

We are on **2.4.1** (container and local venv agree). Two releases are published:
**2.5.0** (2026-08-20) and **2.6.0** (2026-08-23T02:39). We adopt straight to 2.6.0, but **2.5.0's
schema step and default flips still apply** because we are crossing them.

Sources: `aindy-runtime/docs/runtime/APP_HANDOFF_v2.5.0.md`, `…v2.6.0.md`.

---

## 1. What we are crossing

| From 2.5.0 | Effect here |
|---|---|
| `execution_units` +3 nullable columns (`env_spec`, `env_applied`, `env_evidence_class`), alembic `0017` | **Schema step required** on our existing DB. Additive; every existing row is `NULL`, which is defined to behave as before |
| `AINDY_CHILD_CONTEXT_CLAMP` on | A nested context can no longer widen a grant. §3 |
| `AINDY_SYSCALL_IDEMPOTENCY` on | 8 syscalls dedup **within one execution unit**. Two legitimate calls in different runs are untouched |
| `AINDY_NODUS_WARM_POOL` on | Warm worker pool (4) instead of a fresh subprocess. Any warm-path failure falls back to a fresh subprocess |
| `register_tool(..., isolation=…)` | **Nothing to do** — verified: no app declares `isolation=` anywhere |

| From 2.6.0 | Effect here |
|---|---|
| FR-18 liveness digest | Growth stops upstream. The reclaim half we already did on 2026-08-22 (3796 MB → 182 MB) |
| FR-19 `X-AINDY-Envelope: v1` | One client rule replaces per-route knowledge in 11 modules. **Not in this plan** — §6 |
| FR-20 raised 4xx survives | Stale masterplan links 404 instead of 500 |
| FR-21 Webhooks + DLQ panels ship upstream | **Two** of our panels become deletable, not five. **Not in this plan** — §6 |
| FR-22 `route_inventory.json` in the wheel | Lets us *derive* the app-owned surface. Corrects a premise of ours — §5 |
| FR-17 async jobs record start/finish | **Expect more `system_events` rows**, not fewer. That is the fix working |
| `nodus-lang` 5.0.4 → 5.1.0 | Transitive; no pin of ours moves |

**No route began enforcing a new scope in either release, so no caller loses access.**

---

## 2. The schema step is the only step that can hurt

`bootstrap-schema` exits **3** on an additive reconcile. Our entrypoint already handles this
correctly (FR-14 adoption, `docker/entrypoint.sh:63-79`): it prints the exact remedy and exits 3
rather than looping, because `AINDY_BOOTSTRAP_RECONCILE` defaults **off** so a schema change stays
a decision. **We are not flipping that flag.**

Out-of-band, after a dump:

```bash
# 1. dump first — excludes the telemetry table, so this is ~17 MB and takes seconds
docker exec aindy-apps-monolith-postgres-1 sh -c \
  'pg_dump -U aindy -d aindy --exclude-table-data=system_events -Fc -f /tmp/pre260.dump'
docker cp aindy-apps-monolith-postgres-1:/tmp/pre260.dump ./pre-2.6.0.dump

# 2. reconcile explicitly, not via the entrypoint
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml \
  run --rm --no-deps --entrypoint aindy-runtime api bootstrap-schema --reconcile
```

Record `alembic_version_runtime` before and after; expect `0016` → `0017`.

---

## 3. The clamp — what we can and cannot claim

2.5.0 offers a pre-upgrade check: grep logs for `child_context WIDENED authority`. **Run on
2026-08-22 it returned 0 — and that result is weak evidence.** Our api container was recreated at
21:33 the same evening, so the log covers a few idle hours, not the window since 2026-08-16 that
the check assumes. Do not record "0 widenings" as proof.

**The code-level evidence is the strong half, and it is reassuring.** The handoff names one
reachable site: `_handle_agent_suggest_tools` (`apps/automation/syscalls/syscall_handlers.py:690`,
registered at line 842 as `sys.v1.agent.suggest_tools`). It widens to `analytics.read` for an
*optional* cached-suggestions lookup, inside `try/except`, with a full KPI-based fallback beneath.
Clamped, it logs a warning and recomputes — degraded silently in the good sense.

The other 18 widening functions reach the clamp only through `_dispatch_owner_syscall` and are
never registered.

**Verification after upgrade:** call `sys.v1.agent.suggest_tools` and assert it still returns
suggestions, with a WARNING logged rather than an error surfaced.

---

## 4. Steps, in order

1. **Dump** (§2 step 1). Verify the file is non-trivial before continuing.
2. **Move the pin** — `pyproject.toml` `>=2.4.1,<3.0` → `>=2.6.0,<3.0`, **and**
   `tests/unit/test_runtime_dependency_contract.py:18`, which asserts the exact string
   `"<3.0,>=2.4.1"`. These two must move together or the suite fails.
3. **Rebuild the image.** `docker compose build api`. Verify inside the image before deploying:
   `pip show aindy-runtime` → 2.6.0.
4. **Stop the stack gracefully** — `stop -t 120`; checkpoints here have measured 21s and the
   compose file sets no `stop_grace_period`.
5. **Reconcile** (§2 step 2). Confirm `alembic_version_runtime` = `0017`.
6. **Start** with both compose files **and both profiles** — `--profile full --profile mail`, or
   redis is absent and the api reports healthy while erroring.
7. **Verify** (§5).

---

## 5. Verification — what to check, and one premise to re-test

Ordinary boot checks: `boot_profile=default-apps`, `app_plugins_loaded=true`,
`app_plugin_count=16`, all five containers healthy, 0 tracebacks.

Release-specific:

- **Idempotency degradation.** Watch `aindy_effect_gate_outcomes_total{outcome="degraded"}` against
  `reserved`. The gate is **not** exactly-once under contention — a call losing the insert race
  degrades to `AT_LEAST_ONCE`. If degraded is a meaningful fraction, our guarantee is weaker than
  the flag name suggests.
- **Liveness digest.** Expect **two or three** `health.liveness.completed` rows shortly after
  restart (posture providers populate lazily), then near-silence — not zero. Re-measure
  `system_events` growth the next day; `HEALTH-EVENT-VOLUME-1` closes only if it flattens.
- **More async-job rows, not fewer** (FR-17). An increase is correct.
- **A stale masterplan link should 404, not 500** (FR-20).
- **Nodus warm pool** — if anything looks odd, `AINDY_NODUS_WARM_POOL=0` restores the old path
  exactly and is the first diagnostic, not a fix.

### The premise to re-test

FR-22 states that **35 `/apps/*` routes are served by the runtime alone**. If true,
`scripts/check_api_reference.py` — scoped to `APP_PREFIX = "/apps/"` — has been enforcing over
runtime-owned routes, and the "app half / runtime half" framing in `API_REFERENCE.md` and in FR-22
as we filed it does not fall where the prefix implies.

Test it directly after upgrading:

```python
import json
from importlib.resources import files
inv = json.loads(files("AINDY").joinpath("route_inventory.json").read_text())
runtime_served = {(e["method"], e["path"]) for e in inv["routes"]}
# subtract from the booted surface to derive the genuinely app-owned set
```

**If it holds, our own FR-22 needs amending** — we asked the runtime to guard "its" routes on the
assumption the prefix split ownership. It does not.

---

## 6. Deliberately NOT in this plan

Each is real work unlocked by 2.6.0, and each deserves its own change:

- **FR-19 envelope rule** — collapse 11 client API modules onto `X-AINDY-Envelope: v1`. Note the
  runtime's own caveat: the header is **absent** on errors, handler-built `Response` objects, and
  routes with a response adapter, and absence means *not enveloped*, never *unknown*. A blanket
  unwrap stays wrong. Our stated preference — make every `/apps/*` route enter the pipeline — is
  still ours to do and removes the two shapes rather than labelling them.
- **FR-21 panel deletion** — `WebhooksPanel.jsx` and `DeadLetterQueuePanel.jsx` only. **Timing
  trap:** the console ships as package data *inside the wheel*, so verify against the new image,
  not the running one, before deleting anything.
- **`check_api_reference.py` rewire** onto `route_inventory.json` (§5).
- **CORS.** No runtime response header was readable cross-origin before 2.6.0 — `CORSMiddleware`
  had no `expose_headers`. `X-Trace-ID` has never been readable by the Vite page that wanted it,
  which is a candidate explanation for walk-log item 33 and worth re-checking `TRACE-ID-DUAL-1`
  against.

---

## 7. Rollback

- **Image:** the previous image is retained while a container references it; `aindy-apps-monolith-api:runtime-2.5.0` also exists locally from an earlier build. Re-tag and recreate.
- **Schema:** the reconcile is **additive** — three nullable columns. An older runtime ignores
  columns it does not know, so a downgrade does not require dropping them. Verify against the dump
  rather than assuming.
- **Defaults:** every flip has an off switch accepting `0/false/no/off` —
  `AINDY_CHILD_CONTEXT_CLAMP`, `AINDY_SYSCALL_IDEMPOTENCY`, `AINDY_NODUS_WARM_POOL`.
- **Data:** `pre-2.6.0.dump` from §2.

**The one-way door is not the schema — it is the liveness digest changing what gets recorded.**
That is desirable, but it means the pre-upgrade `system_events` growth rate cannot be re-measured
after the fact. It was measured on 2026-08-22: ~98 MB/day.


---

## 8. Executed — 2026-08-23

Ran in the planned order. Rollback handles created first: image `aindy-apps-monolith-api:runtime-2.4.1`
(and `:runtime-2.5.0` from an earlier build), plus a 17.1 MB pre-upgrade dump held outside the repo.

| Step | Result |
|---|---|
| Dump | 17.1 MB, `--exclude-table-data=system_events` |
| Pin | `>=2.6.0,<3.0` in `pyproject.toml` **and** the contract test, together |
| Image | built; verified **inside the image** before deploying: `aindy-runtime 2.6.0`, `nodus-lang 5.1.0` |
| Stop | graceful, `stop -t 120`; postgres logged `database system is shut down` |
| Reconcile | `0016 → 0017`; `env_spec`/`env_applied` `jsonb`, `env_evidence_class` `varchar`, all nullable |
| Boot | healthy in 100s; `default-apps`, 16 plugins, **0 tracebacks** |

### FR-14 behaved exactly as documented

A bare `bootstrap-schema` named all three missing columns and reported
`state=upgrade_required operator_action=startup_reconcile exit_code=3`. A precise refusal, not a
crash loop — which is the whole point of that request.

### FR-18 — measured across the boundary

| | 2.4.1 | 2.6.0 |
|---|---|---|
| liveness rows | **160 in the final hour** | **1 in the first 3 minutes** |
| payload per row | ~28 kB, 26 keys | **356 bytes, 10 keys** |

`/health/detail` still serves the full 26-key snapshot on demand.

**A correction to our own earlier number.** `HEALTH-EVENT-VOLUME-1` recorded ~98 MB/day, derived
from a 34-day total. Measured live before this upgrade, the database went **182 MB → 232 MB in
about seven hours** — closer to **170 MB/day**. The 34-day figure understated it because the stack
was not running continuously across those days.

### FR-19 / CORS — confirmed, and it explains an old mystery

`access-control-expose-headers` now carries exactly
`X-AINDY-Envelope, X-Trace-ID, X-Request-ID, X-EU-ID, X-API-Version, X-Version-Warning`. Before
2.6.0 no runtime response header was readable cross-origin at all, so the Vite page has never been
able to read `X-Trace-ID` — worth re-testing `TRACE-ID-DUAL-1` against, since that finding was made
from the browser side.

A 401 carries **no** envelope header, matching the contract that absence means *not enveloped*.
**Not verified:** the header on a successful enveloped response — that needs an authenticated
request.

### FR-22 — the premise was wrong, and it was ours

Read from the wheel without booting: `route_inventory.json` has **126 entries, of which exactly 35
are under `/apps/*`** — `/apps/memory/` (22) and `/apps/coordination/` (13). *(The handoff says
"coordination, memory, agent"; there are no agent routes in the file.)*

So `scripts/check_api_reference.py`, scoped to `APP_PREFIX = "/apps/"`, has been enforcing over 35
runtime-owned routes, and of the 265 `/apps/*` entries in our reference **230 are genuinely ours**.
Our FR-22 asked the runtime to guard "its" surface on the assumption that the prefix marked the
boundary. It does not. FR-22 amended accordingly.

### Not exercised

`aindy_effect_gate_outcomes_total` produced nothing — an idle stack dispatches nothing under
contention. The idempotency degradation warning in §5 is **unverified, not clean**, and should be
checked once there is real traffic.
