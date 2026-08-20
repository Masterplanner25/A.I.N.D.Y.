---
title: "Session Handoff — 2026-08-20"
last_verified: "2026-08-20"
api_version: "1.0"
status: current
owner: "app-team"
---

# Session Handoff — 2026-08-20

**Arc:** started as "login times out after 30 seconds", found a healthcheck that had been killing
the PostgreSQL cluster 155 times, fixed it, **declared victory too early**, and on the second look
found the machine itself was the wall. Ended somewhere more useful than it started: a defect
write-up whose central claim the owner corrected, which changed the fix.

**2 PRs merged (#234, #235).** Stack pinned to `aindy-runtime==2.4.1`. The **local host cannot
currently hold the stack up** (§4) — everything below that needs a running stack is blocked on
that, not on code.

---

## 1. What shipped

| PR | Area | What |
|---|---|---|
| #234 | compose | Mongo healthcheck no longer OOM-kills the PostgreSQL cluster; API `start_period` 40s → 240s |
| #235 | docs | Genesis latency defect amended (§8); new `DEFECT_INFINITY_RECALC_DEBOUNCE.md` |

Plus this handoff and two `CLAUDE.md` corrections (§5).

---

## 2. The outage, and the four layers between symptom and cause

`docker-compose.mongo.yml` probed with `mongosh --eval "db.adminCommand('ping').ok"` every **10s on
a 5s timeout**. `mongosh` is a **Node** process — ~1.3GB virtual, ~130MB resident, slow to start.
On a paging host it could not finish inside 5s, so a fresh one spawned while previous ones were
still resident.

```
mongosh pile-up
  -> Docker VM hits GLOBAL OOM (constraint=CONSTRAINT_NONE, not container-scoped)
  -> kernel kills POSTGRES backends
  -> postmaster terminates all backends and reinitializes the cluster   <- 155 times
  -> API loses its DB mid-request, restarts (7x), scheduler saturates
  -> "login times out"
```

Fixed with a `bash` `/dev/tcp` connect (no spawn, no allocation, 0.8s vs a blown 5s timeout),
interval 10s → 30s, plus `mem_limit: 768m` on mongo so an unbounded container can never reach
*global* OOM again. Zero cluster reinitialisations since.

**Two mistakes worth keeping:**

- **`CMD-SHELL` was wrong.** `/bin/sh` in `mongo:7` is dash and `/dev/tcp` is a bash builtin, so
  the first version failed with `Directory nonexistent` — which reads like a broken container
  rather than a broken probe. Caught by checking the health log instead of trusting the deploy.
- **Declared fixed while the host was already thrashing.** The sub-second login measurements were
  real and landed in a brief calm window. The owner reported it still timing out. See §4.

---

## 3. The Genesis latency defect — the owner's correction changed the fix

`DEFECT_GENESIS_MESSAGE_LATENCY.md` §4 asserted *"a conversational turn is not a scoring event"*
and offered, as a remedy, "recalculate on lock."

**The owner rejected the premise**: a turn *is* a scoring event, measurable in several ways; the
real problem is *"real work loaded with nowhere to go."*

Checking that against the code proved the correction and narrowed the defect:

- `score_history` is **append-only** and already carries **`trigger_event`** and **`score_delta`**
  beside all five sub-scores. **The turn-level score already has a correct, purpose-shaped home** —
  the architecture had made this decision before the defect was written up. "Recalculate on lock"
  would have deleted real signal.
- What genuinely has no consumer is narrower: the **response field**. `Genesis.jsx:185` reads
  `data.reply` and `data.synthesis_ready` and contains no reference to `orchestration`.
- So the defect is **placement** (synchronous, on the one serialised slot) plus **destination**
  (the response copy, not the persisted one) — two faults, neither requiring a product decision.

**A correction inside the correction:** §4's own remedy cites `register_async_job` as "already used
by this domain." It is — by `masterplan` — but **analytics registers none at all** (11 exist across
8 other apps), `analytics.infinity_execute` is `register_job` (a *synchronous* callable lookup),
and `register_async_job("genesis.message")` runs the whole workflow including the LLM call, so it
cannot serve a turn whose reply the client awaits. **The remedy is new code, not wiring.**

### 3.1 A separate defect found on the way

`DEFECT_INFINITY_RECALC_DEBOUNCE.md`. Both guards around `infinity_orchestrator.execute()` are
keyed on `trigger_event`, which `user_scores` stores only for the **most recent** run:

- **The debounce cannot fire in alternating traffic.** Scheduled stamps `scheduled` → chat turn
  mismatches and recalculates → stamps `genesis_message` → next scheduled mismatches. Separately
  the window is `_ANALYTICS_DUPLICATE_DEBOUNCE_SECONDS = 1`, a double-submit guard rather than a
  rate limit. Raising the window alone would not help; the mismatch short-circuits first.
- **The lease embeds the trigger**, so two different-trigger recalcs for one user take *different*
  leases and may overlap, both upserting one row. **Grounded in code, not reproduced.**

**Low severity today, high at real usage** — which is the point. `SOAK_AUDIT_2026-08-15` concluded
every measurement gate is usage-blocked; this is the shape of defect that converts *finally getting
usage* into a new problem.

---

## 4. The host is the current wall

Measured 2026-08-20:

| | |
|---|---|
| Physical RAM | 7.7 GB |
| **Committed** | **26.7 GB** (3.5x overcommit) |
| Available | 98–180 MB |
| **Hard page faults/sec** | **~56,000** |
| Docker VM load average | 14.16 on 8 CPUs |
| Docker VM memory | **fine** — 2.8 GB available |

The VM has memory and no CPU, because the host spends its cycles paging. The decisive observation:
the API container sat `running` with **zero restarts** and produced **no log output for five
minutes** having previously logged twice a second. That is a frozen process, not a slow one.

Largest committed consumers: `claude.exe` x4 (**4.25 GB**), `vmmemWSL` (3.97 GB), `WindowsTerminal`
(1.63 GB), `OneDrive.Sync.Service` (1.62 GB), and a cycling Nodus benchmark suite from the
`Coding Language` repo.

**One durable lever, not yet applied:** the Docker VM is allocated 3.97 GB and uses ~872 MB.
Capping it at 2.5 GB in the user's `.wslconfig` returns ~1.4 GB to Windows at no cost to the
stack. Needs `wsl --shutdown`. The owner is working in other repos and deferred this deliberately.

---

## 5. `CLAUDE.md` changes

- **"18 registration categories total" → 40.** The registry exports 40 `register_*` functions.
- **New: the three job mechanisms.** `register_scheduled_job` and `register_job` are in the
  registry; **`register_async_job` is not** — it lives in `AINDY.platform_layer.async_job_service`.
  Registering a job does not make it async. This exact confusion produced the wrong remedy in a
  shipped defect doc (§3).
- **New section: "When the API hangs: the scheduler saturation trap."** The `max_instances`
  warning is a consequence, never the culprit, and the full fingerprint has now been produced by
  two unrelated causes. Gives a three-step cheapest-first check order (PostgreSQL reinit count,
  host paging via the *correct* Windows counters, boot-in-progress) before touching app code.

Everything else in `CLAUDE.md` was verified and left alone: the runtime pin matches `main`
(`>=2.4.1,<3.0`), all 16 apps are registered, and every path in the Key file locations table
exists. **Nothing was found stale enough to trim.**

---

## 6. Open, in the order it probably matters

| Item | Blocked on |
|---|---|
| **MasterPlan V4 import** (22,749 chars; cap raised to 80,000) | Genesis latency fix **and** a host that can run the stack |
| **Genesis latency fix** — §3, remedy is new code in `apps/analytics/bootstrap.py` | Nothing. Writable now. |
| **Infinity recalc debounce** — §3.1 | Confirm §2's race on a non-thrashing host first |
| **Image rebuild** — container is on runtime **2.3.0**, `main` is **2.4.1**; also missing #216's leadgen gate and #234's compose fixes | Host (a build is what exhausted the disk twice before) |
| **PR #228** (vite 8) | Known: `manualChunks` must become a function for Rolldown |
| **Leadgen backfill audit** — `scripts/audit_leadgen_fixtures.py`, read-only, never run | `DATABASE_URL` / a live stack |
| **`AINDY_ASYNC_HEAVY_EXECUTION`** measurement (FR-15a) | Live stack |
| **Worth §2b normalisation** | Nothing; must land before any declarations UI |
| Specs: capacity/runway, starting position, self-trust ph1, terminal agent ph1–2, cognitive operations ph1, Domain Engine ph1–2 | Prioritisation |

**Suggested next session:** the Genesis latency fix (§3). It is the only item that is
simultaneously the V4 blocker, writable without a healthy stack, and already fully specified —
including the correction that stops it from being implemented the wrong way.

---

## 7. Practice note

The recurring failure this session was **declaring a fix verified from a measurement taken inside a
window where the underlying condition happened to be quiet.** It happened once with the login
latency (§2) and was avoided twice afterwards only by re-checking: the `CMD-SHELL` probe looked
deployed but was failing, and the `localhost` vs `127.0.0.1` split looked like an IPv6 shadow but
was really the API wedging between two consecutive tests.

On a host this loaded, a single green measurement means very little. Take two, separated.
