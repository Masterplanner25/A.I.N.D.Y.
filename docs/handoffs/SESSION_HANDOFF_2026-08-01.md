# Session Handoff — 2026-08-01

**Arc:** started as "look at the LinkedIn surface", became a product-identity investigation, ended
with a resolver that lets a MasterPlan measure achievement instead of activity.

Three PRs merged (#172, #173, #174). `main` at `dd20728`.

---

## 1. What shipped

| PR | Area | What |
|---|---|---|
| **#172** | analytics / masterplan | `/analytics` rewired onto the live social engine; `create_masterplan` repaired; compute routes now serialize |
| **#173** | masterplan / analytics | Diagnosis brief + goal-attainment spec + **Phase 0** resolver (`tasks` unit) |
| **#174** | analytics / freelance / social | **Phase 1** — `get_goal_metric` syscalls; resolvable units 1 → 5 |

All green on CI, all verified live against the running stack before merge.

---

## 2. The three surfaces walked

### `/analytics` — had never worked (walk-log item 18, CLOSED)

`canonical_metrics`, the table the surface exists to populate, held **0 rows**. Three independent
breaks, each reproduced live:

1. **Form ≠ API.** Sent `reach`/`interactions`/`followers`; `LinkedInRawInput` accepts none of
   those and requires `scope_type` + `members_reached`. HTTP 422 on every submit.
2. **Backend fails on a correct payload.** The ingest node dispatches `data.model_dump()` (a dict)
   across a syscall, but `linkedin_adapter` does attribute access (`raw.likes`) → `AttributeError`
   → 500. Structurally incapable of succeeding.
3. **Prerequisite uncreatable.** `/apps/compute/create_masterplan` 500'd unconditionally.

Zero test coverage on the whole path — which is why three simultaneous breaks went unnoticed.

**Fixed:** `/analytics` now renders `GET /apps/social/analytics` (real posts, impressions, clicks,
engagement, trend) **including `signals`**, which the Feed panel had been dropping. LinkedIn
backend parked, not deleted, per owner decision — nothing consumes `canonical_metrics`.

### MasterPlan — engine strong, surface a keyhole

A full Genesis run was executed for the first time, producing **plan 4** — the first MasterPlan the
system had ever created — plus **3 dependency-chained tasks derived from the AI's phases**.
Genesis, synthesis, audit, lock, posture classification, ETA/projection and WCU all work.

But the plan list API returns **6 scalars** and `GET /apps/masterplans/{id}` **500s**, so almost
none of it reaches the browser. The screen is thin because of the API, not the design.

Full diagnosis: `MASTERPLAN_REDESIGN_BRIEF.md`.

### RippleTrace — starved, not misbuilt

4,297 LOC, ~50 routes, 11 engines, 5 tables — **all empty**. Seeded 2 drop points + 3 pings and
most of it works: ripples, influence graph, causal graph (found a real downstream link at
confidence 0.4), recommendations, learning stats.

**It is the most *generic* domain in the repo** — `{title, platform, url, core_themes,
tagged_entities, intent}`, nothing owner-specific. It has zero rows because it has **no data
supply**: no external ingestion anywhere, so every ping must be hand-entered.

Also two products under one name: `rippletrace_services.py` (content influence) vs
`rippletrace_service.py` (execution-trace analysis).

---

## 3. The product thesis (owner, this session)

> *"The main thing I wanted was to be able to use the infinity algorithm — that's the product. The
> question is how is everything else feeding it."*

This reframes everything into a gap list. **Verified feeder map:**

- **Score (5 weighted KPIs):** tasks, arm, watcher, masterplan, freelance
- **Three axes:** tasks · freelance + value declarations · score history
- **Loop (`gather_support_state`, 9 sources):** memory, metrics, observability, goals, tasks,
  social, search, freelance, system state

**Two tiers matter:** social/search/memory/goals feed the *loop* (what you're told to do) but not
the *score* (your number).

**Feeds nothing:** **rippletrace (the largest domain)**, authorship, autonomy, bridge,
network_bridge.

### Star vs hub

Docs and code both implement a **star** — each domain wires to Infinity directly; masterplan is a
peer, not a spine (`gather_support_state` does not include it). But MasterPlan's five never-written
progress columns map exactly onto domains — `gross_revenue`←freelance, `books_published`←authorship,
`active_playbooks`←rippletrace, `platform_live`←social. That is a **hub design expressed as
columns, never implemented and never documented**.

**Owner's call: star is enough for now — feed MasterPlan better.**

---

## 4. Nothing moves the MasterPlan

Three things can move a plan, all measuring *activity*: task completion (0.6), schedule (0.4), WCU.
Complete every task on schedule having earned and shipped nothing → perfect progress.

**Structural cause:** the anchor declares `goal_value`/`goal_unit` with **no counterpart**. There is
no `goal_current` — `goal_value` is write-only, never compared to anything. The typed alternative
has the mirror flaw: the fields exist and nothing writes them, which is exactly why `evaluate_phase`
is permanently unsatisfiable (one always-False term in an AND-chain).

**Shipped (phases 0+1, unwired to scoring):** resolve declared goals against real domain signals
**on read, over syscalls**. No column, no write path, no migration, no new cross-app import.
Read-only at `GET /apps/analytics/goal-attainment`.

Units: `tasks` ✅ · `usd` ✅ · `impressions`/`clicks`/`posts` ✅ · `playbooks` ❌ (table empty) ·
`books` ❌ (no publication concept).

**Proof it works:** completing a real task moved attainment `0.0 → 0.333`. A goal of 1000 USD with
250+150 delivered and a 999 pending order → `400.0` (pending correctly excluded).

**Next: Phase 2 (shadow).** The proposed `0.40 attainment / 0.35 completion / 0.25 schedule` split
is **asserted, not derived**, and a `tasks` goal double-counts to 0.75. Compare distributions before
flipping. Spec: `MASTERPLAN_GOAL_ATTAINMENT_SPEC.md`.

---

## 5. Recurring patterns

### Dead twins — now six instances

| Personal/dead v1 (wired) | General v2 (built, elsewhere) |
|---|---|
| LinkedIn manual ingest | system-fed social analytics |
| 13 manual KPI calculators | Infinity score engine |
| `books_required`/`studio`/`playbooks` | `Goal`/`GoalState`, anchor |
| `/apps/compute/masterplans` | `/apps/masterplans/` |
| ARM's own KPI service | Infinity recomputing the same 3 KPIs |
| `evaluate_phase` ×3 byte-identical | only `projection_service`'s imported |

The ARM one was already flagged in `INFINITY_ALGORITHM_SUPPORT_SYSTEM.md:166` (2026-06-29).

**Diagnostic that works: check whether the table has rows.** `canonical_metrics = 0` exposed three
simultaneous breaks no code reading had caught.

### Dict-where-object — a second bug class, hit twice

A domain converts its public contract to dicts (correct for cross-domain boundaries); a consumer is
never updated.

- `apps/social/services/linkedin_adapter.py:5` — `raw.likes` on a `model_dump()` dict
- `apps/rippletrace/services/prediction_engine.py:64` — `thresholds.velocity_trend` on
  `ensure_learning_thresholds`, explicitly typed `-> dict[str, Any]`

**Worth a sweep of every `apps/*/public.py` consumer.**

---

## 6. Open defects (found, not fixed)

| # | Defect | Severity |
|---|---|---|
| 1 | `GET /apps/masterplans/{id}` → **500** (`Completion finalization failed: execution.completed`) | blocks the detail view |
| 2 | `POST /genesis/lock` requires `draft` in body, but its service prefers `session.draft_json` | high |
| 3 | That 400 is raised pre-pipeline → `RouteExecutionViolation` rewrites it as an opaque **500** | high — makes #2 undiagnosable |
| 4 | `velocity_trend` dict/object bug → `/narrative/*`, `/predictions/{id}` 500 | medium |
| 5 | Genesis **never signals readiness** — only flipped when the user typed "I'm ready to lock this in" | UX, explains "it never made a plan" |
| 6 | `evaluate_phase` unsatisfiable; triplicated | design decision |
| 7 | No import/upload path for an existing plan | design gap |

---

## 7. Environment

✅ `main` at `dd20728`, clean, branches deleted
✅ Stack healthy on a **freshly rebuilt image** — first time this session running merged code
✅ Test data cleared: 0 plans, 8 original tasks, 0 drop points/pings, genesis session 1 restored
✅ Vite up on `:5173`, proxy verified
🔑 `admin@local.test` / `KpiWalk!2026`

### The Docker outage — two independent causes

1. **`com.docker.backend` had been wedged since July 22** — 10 days, predating the session.
   `tasklist | findstr` missed it; `Get-Process` found it. Restarting Docker Desktop does nothing
   while those processes live — needs a force-kill + `Restart-Service com.docker.service`.
2. **An image build filled C: to 3.2 GB free**, which stopped WSL starting Ubuntu, surfacing as
   `Wsl/Service/CreateInstance/E_FAIL ... Error code: 6`. **Check `docker system df` and free disk
   before any build.**

Then a 401 revealed a **second, native `dockerd`** holding `:8000` with its own copy of the
project — **invisible to `docker ps`**, because Docker Desktop hijacks `/var/run/docker.sock` so
both CLIs report only DD's containers (identical container IDs, which looks like proof of one
stack). The tell was `docker-proxy -container-ip 172.18.0.3` — an IP no DD container had.

**Resolved permanently:** native `docker`, `docker.socket`, `containerd` are now `disabled` in
Ubuntu, so they will not return on boot. Reclaimed 35.7 GB of build cache; Docker's footprint went
~45 GB → ~18 GB.

---

## 8. Where to pick up

**Ready now**
- **Phase 2 (shadow)** for goal attainment — but it only teaches you something if real usage flows
  through it. Consider using the system for a while first.
- **Defects 1–4** are small and independent. #1 blocks the MasterPlan detail view entirely.
- **The `public.py` dict/object sweep** — one bug class, two confirmed instances.

**Decisions, not tasks**
- **RippleTrace's data supply.** It is generic, working, and starved. `social` already auto-tracks
  impressions/clicks; wiring that into pings would give it a real feed. Otherwise it is 4,297 LOC
  contributing nothing to the product.
- **Genesis: partner or funnel?** It has long-term memory but **no conversation transcript** — each
  turn sees only a six-field summary plus your new message. Passing the last N turns is cheap. The
  build doc's language ("Let's discover your destiny architecture") implies partner; what shipped
  is a form-filler with a chat interface.
- **The non-feeders** — authorship, autonomy, bridge, network_bridge are ~8 routes combined. Give
  them a signal path or stop carrying them as domains.

**Still parked:** 2c flag soak, client error telemetry (#28), dual trace ids (#33), ARM path
confinement (#20, security), `/analytics`'s LinkedIn backend.

---

## 9. One honest note

I misdiagnosed the Docker outage twice — first reporting the Docker Desktop processes as dead when
they were wedged, then retracting the "two stacks" conclusion on matching container IDs before
confirming it was right after all. The retraction was the wrong call: identical container IDs look
like proof of one stack, but the socket hijack makes both CLIs report the same containers
regardless. Comparing data between the "two" stacks was also worthless — both queries went through
the same socket.

The pattern from prior sessions holds: **shape and contract inferences were reliable** (every API
break was reproduced exactly as predicted); **environment inferences needed evidence**, and I
asserted a few before I had it.
