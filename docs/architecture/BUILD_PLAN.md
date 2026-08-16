---
title: "Build Plan — Shipping the Woken Decision Engine"
last_verified: "2026-08-15"
api_version: "1.0"
status: current
owner: "app-team"
---

# Build Plan — Shipping the Woken Decision Engine

## Where this comes from

This is the forward plan that follows the architecture review + validation pass
(2026-07-09 → 2026-07-15). Related material:

- **Strategic diagnosis** — the reconciled architecture map. Originally an external artifact
  (last revision v6, re-audited 2026-07-19); **folded into this document 2026-08-15 and the
  artifact retired**, so the "why" is no longer held outside the repo. See
  [§ Strategic diagnosis, folded in](#strategic-diagnosis-folded-in-from-the-architecture-map).
- **Code-structure reference** — [ARCHITECTURE_MAP.md](./ARCHITECTURE_MAP.md) (layers,
  boundaries, module list). It is the "what exists."
- This document is the "what we build next, in what order."

**One-line thesis.** A.I.N.D.Y. shipped a working Operator-grade *body* (execution,
continuity, orchestration) and left its reasoning *mind* dormant. This pass we
**woke the mind and proved it end-to-end**. The plan below ships that woken mind as a
first-class, user-facing capability and re-tethers the pillars back to the Infinity loop.

## The end state — "one face, delegated engines"

One conversational **face** in the product UI that routes user intent to the engines
behind it, rather than a chat that itself acts (cognition ≠ execution, per Agentics):

- *"form / revise my plan"* → the **Genesis** engine (plan-authoring state machine)
- *"do X"* → the **agent** engine (plan → approve → execute, streamed back)
- *"how am I doing"* → **Infinity** reads / the measurement surface
- later: social / freelance / search as callable capabilities

The face is the agent's mouth; Genesis / agent / Infinity are its faculties. Genesis
**now folds in as a *mode*** within the one conversation (Track 5 — it stays a structured
sub-flow; its state machine was a deliberate fix for the "infinite refinement loop").

## Validated foundation (2026-07-15) — what is already proven

The hard part is done and demonstrated — and, as of **2026-07-19, proven all the way to a
literal Claude-planned `completed` run on real hardware:**

- **The reasoner reasons** — with `AINDY_AGENT_PLANNER_BACKEND=anthropic_chat`, Claude
  (`claude-opus-4-8`) authors a real multi-step, tool-diverse plan (5–6 steps) vs. the keyword
  heuristic's 1.
- **Its plan executes to done — for real, with the Claude planner** — the full HTTP loop
  `register → create (Claude plans) → approve → execute → completed` ran on a native-Linux
  Docker stack, verified at every layer: 6× `AGENT_STEP_COMPLETED`, run status `completed`,
  and real side-effects (3 correctly-named tasks written to Postgres). The "last mile" the
  earlier Tier-2 sessions could only reach `executing` on is now closed.
- **The rails hold** — runtime **1.10.0** adopted (RT-MEMTXN-LEAK-1 sign-in fix + NODUS-WARMPOOL-1 warm-pool closed); APP-DEPLOY-1 closed (`bootstrap-schema`
  deploy split + `ensure_pgvector`); the nodus wall-clock budget + boot allowance are tunable
  (`AINDY_NODUS_MAX_EXECUTION_MS` / `AINDY_NODUS_BOOT_ALLOWANCE_MS`); standing CI guards
  (`deploy-bootstrap-guard`, `serve-run-completion`).
- **Where it runs** — the literal Claude loop needs model egress + a stable, reasonably fast
  datastore. Proven on a **native-Linux Docker engine** (`docker.io` inside WSL2 Ubuntu, or a
  cloud Linux box) — **not** Docker Desktop's VM, whose slow pg exhausts the connection pool
  under the memory-embedding fan-out (see the slow-host tunables + `NODUS-WARMPOOL-1`).
  GitHub-hosted runners still can't reach the LLM (RTR-1-NODUS-APPTOOL-500).

## Status at a glance (2026-07-19)

| Track | What | Status |
|---|---|---|
| **1** | The face — user-facing Assistant (`/assistant`) | ✅ **done** — merged |
| **2** | Reasoner first-class (Claude planner default) | ✅ **done** — proven end-to-end (literal Claude-planned `completed` run on a native-Linux host) |
| **3** | Re-tether Search/Freelance yield → Infinity + `analytics` core | ✅ **done** (3b-lite: observability tether; 3b-full weighting **usage-blocked** — see the soak audit) |
| **4** | Wire orphaned UI (`InfiniteNetwork`, `ProfileView`, `GenesisDraftPreview`) | ✅ **done** — merged |
| **5** | Fold Genesis behind the face (`?mode=genesis`) | ✅ **done** — merged |

All five tracks are shipped. The "one face, delegated engines" end-state is in place: one
Assistant face (`/assistant`) with an **Agent | Plan** toggle routing to the agent engine and
the Genesis plan-authoring engine, and the agent engine now reasons with Claude by default in a
suitably-provisioned deployment. **The remaining open item is not a track** — it's **3b-full**
(which pillar signal moves the canonical Infinity score, and at what weight), a deliberate
values decision now framed as the Worth axis of the three-axis model. See
[INFINITY_SCORE_MODEL.md](./INFINITY_SCORE_MODEL.md).

> **Superseded 2026-08-15.** This item was recorded as "gated on a shadow soak, not on build."
> The soak ran and produced nothing usable — across 294 records Worth is constant and Trajectory
> is entirely NULL. It is **usage-blocked**, not soak-gated. Note the blocker is *not* revenue:
> Worth is computed from **declared** worth (`intent_value_declarations`, 0 rows — the API exists
> with no UI) and Trajectory from estimate-vs-actual pace on completed tasks. See
> [`../handoffs/SOAK_AUDIT_2026-08-15.md`](../handoffs/SOAK_AUDIT_2026-08-15.md).

## Tracks

### Track 1 — The face (MVP) ✅

A user-facing conversational/command surface in `client/` that dispatches to the agent
engine. Today the reasoner is **admin-only** (agent runs live in the `/platform` console);
a normal user has no way to talk to the mind we just woke. This closes that gap.

- **Backend: ready + proven.** `POST /apps/agent/run {goal}`, `GET /apps/agent/runs/{id}`,
  `POST /apps/agent/runs/{id}/approve`, `GET /apps/agent/runs/{id}/steps`,
  `GET /apps/agent/runs/{id}/events`, `GET /apps/agent/runs`. No new backend needed for the MVP.
- **Frontend: the build.** A console/chat in the *user* app (`client/src/…`, routed via
  `AppShell`, not `/platform`): submit a goal → render the plan → inline **approval gate** →
  stream steps + events → show the result. Envelope discipline: read outputs from `body.data`.
- **MVP interaction:** goal → `create` → show plan (`pending_approval`) → Approve → poll/stream
  `steps`/`events` to a terminal state → render result.
- **Dependency:** none. Works with either planner (heuristic or Claude); Track 2 makes it *reason*.
- **Status:** ✅ **done — merged.** `Assistant.jsx` shipped: goal → plan → inline approval gate →
  `useEffect`-polled steps → terminal result, routed via `AppShell` (not `/platform`). See the
  [Track 1 MVP build scope](#track-1--mvp-build-scope) appendix.

### Track 2 — Reasoner first-class (default) ✅

Make the Claude planner the default instead of opt-in.

- Flip `AINDY_AGENT_PLANNER_BACKEND` default `runtime_local → anthropic_chat` in the deployed
  env; set `AINDY_CLAUDE_PLANNER_MODEL` (optional); the deploy image already installs `anthropic`.
- **Status:** ✅ **done — proven end-to-end (2026-07-19).** `docker-compose.prod.yml` makes the
  flip a turnkey `.env` toggle (`AINDY_AGENT_PLANNER_BACKEND=anthropic_chat` + `ANTHROPIC_API_KEY`),
  and the full loop was driven to a literal `completed` on a native-Linux Docker stack: Claude
  authored a 6-step plan → approve → execute → `completed`, with 3 real tasks written to Postgres.
  Getting there also fixed four latent deploy walls now shipped in the compose: `AINDY_BOOT_MODE`
  (serve defaulted to `runtime-only` = zero apps), the planner env pass-through, the 30s DB
  idle-in-transaction reap (→ 120s), and the Nodus per-execution cold-start budget (→ 120s + 60s).
  Turnkey steps: [../deployment/DEPLOYMENT.md](../deployment/DEPLOYMENT.md) ("Enabling the Claude
  planner" + "Tuning for slower / cold-start-heavy hosts").
- **Caveat (host, not code):** the literal loop needs a native-Linux Docker engine — Docker
  Desktop's VM (even via WSL integration, which silently substitutes its own engine) has slow pg
  that exhausts the pool under the memory-embedding fan-out. Use `docker.io` in a WSL2 distro or a
  cloud Linux box. See `NODUS-WARMPOOL-1` in `TECH_DEBT.md`.

### Track 3 — Re-tether the pillars to Infinity

Restore the explicit "this feeds the loop" wiring the review found eroded/lost:

- Search's yield loop and Freelance's real revenue no longer flow into canonical Infinity;
  `analytics` (which *is* Infinity) is flagged `IS_CORE_DOMAIN=False`.
- Make `pillar → Infinity` and `app → runtime` lines explicit; do **not** un-generalize the
  platform — restore purpose, don't undo the split.
- **Dependency:** independent; can proceed in parallel.
- **Status:** ✅ **done (3b-lite) — merged.** Search (leadgen yield) and Freelance (realized revenue)
  now expose `sys.v1.<domain>.get_performance_signals` syscalls that the analytics `dependency_adapter`
  fetches and threads into the Infinity `SupportState` (mirrors social — observability, not KPI math);
  `analytics` flipped to `IS_CORE_DOMAIN=True`. **3b-full deferred:** promoting a signal to actually
  move the canonical Infinity score (and its weight) is a values decision, taken when the weighting is chosen.

### Track 4 — Quick wins (orphaned UI)

Wire the already-built-but-unrouted frontend the review surfaced: `InfiniteNetwork`,
`ProfileView`, `GenesisDraftPreview` (built, no route/importer). Cheap; independent.

- **Status:** ✅ **done — merged.** `InfiniteNetwork` (`/network`) and `ProfileView` (`/profile/:username`)
  routed + nav-linked; `GenesisDraftPreview` imported into `Genesis`; Feed author handles link to profiles.

### Track 5 — Fold Genesis behind the face

Move Genesis from standalone `/genesis` to a *mode* within the one conversation, keeping its
structured state machine (explore → confirm → draft → LOCK). Do this **last**, after Track 1
is proven — its logic survives; only its packaging dissolves.

- **Status:** ✅ **done — merged.** Assistant carries an **Agent | Plan** toggle; `?mode=genesis`
  early-returns the Genesis engine under a shared, linkable mode bar. MasterPlan's "Initialize via
  Genesis" repointed to `/assistant?mode=genesis`. Genesis's state machine is unchanged — only its
  packaging dissolved into the one face.

## Sequencing (as executed)

```
Track 1 (face MVP) ✅ ──► Track 5 (fold Genesis in) ✅
      │
      └─ Track 2 (reasoner default) ✅  — proven end-to-end (literal completed on native-Linux)
Track 3 (re-tether) ✅ ── ran in parallel (3b-lite; 3b-full soak-gated)
Track 4 (quick wins) ✅ ── ran in parallel
```

**As executed:** Track 1 → Track 4 alongside → Track 3 (3b-lite) in parallel → Track 5 last →
Track 2 proven on a provisioned native-Linux host. **All five tracks are shipped.**

## Open decisions

- **Egress env for Track 2** *(resolved)* — a native-Linux Docker engine with Anthropic egress
  (`docker.io` in a WSL2 Ubuntu distro was used to prove the literal loop; a cloud Linux box works
  equally). Docker Desktop's VM is NOT suitable (slow pg → pool exhaustion).
- **3b-full weighting** *(open — **usage-blocked**, not soak-gated)* — which pillar signal is
  promoted to move the canonical Infinity score, and at what weight. A values decision, framed as
  the **Worth axis** of the three-axis model in
  [INFINITY_SCORE_MODEL.md](./INFINITY_SCORE_MODEL.md). Phases A/B/C (measure → shadow → advisory)
  are **shipped**. Unifies with the learned-recursion work below — the two resolve to one decision.

  > **Restated 2026-08-15.** This was recorded as needing *"the Phase-B shadow soak's divergence
  > data, not more build."* The soak has run for weeks and produced no usable divergence data:
  > across 294 shadow records, `worth_score` has **1** distinct value and `trajectory_score` is
  > **entirely NULL**. The blocker is that nothing is generating varied state to measure — elapsed
  > time cannot fix it. It is *not* a revenue blocker: Worth reads **declared** worth
  > (`intent_value_declarations`, 0 rows, API routed but no UI) and `realized_revenue` is
  > observability-only, never folded into the score. Full evidence in
  > [`../handoffs/SOAK_AUDIT_2026-08-15.md`](../handoffs/SOAK_AUDIT_2026-08-15.md). **Do not flip.**
- **Learned recursion (REFLECT calibration)** *(shipped through advisory)* — the learned
  expected-score calibrator: Phase 0 (shadow) and Phase 1 (advisory) are **merged**; Phase 2
  (driving the score) re-opens 3b-full and is soak-gated. Scoped in
  [INFINITY_LEARNED_RECURSION_SCOPE.md](./INFINITY_LEARNED_RECURSION_SCOPE.md).
- **Face surface shape** *(resolved)* — shipped as a dedicated `/assistant` page in the user nav,
  not a global command bar.
- **Streaming** *(resolved for now)* — MVP polls the run/steps endpoints (`useEffect` interval);
  SSE/websocket remains a later upgrade.

## Track 1 — MVP build scope

The agent HTTP backend **and the frontend API client are already built** — `client/src/api/agent.js`
exposes `createAgentRun`, `getAgentRun`, `approveAgentRun`, `rejectAgentRun`, `getAgentRunSteps`,
`fetchRunEvents` (the admin `/platform` `AgentConsole.jsx` uses them). Track 1 is therefore a pure
frontend build over a proven, wired client — no new backend, no new API layer.

**Changes — one new file + two insertions:**

| File | Change |
|---|---|
| `client/src/components/app/Assistant.jsx` *(new)* | The face component — the whole MVP |
| `client/src/App.jsx` | `lazy(() => import("./components/app/Assistant"))` + a `<Route path="/assistant">` (mirrors `Genesis` / `TaskDashboard`) |
| `client/src/components/shared/AppShell.jsx` | Add `{ to: "/assistant", label: "Assistant" }` to the **user** nav group (`/agent` is taken by the `external` admin console) |

**Interaction (state machine):**

```
[goal] → createAgentRun({ goal })
  → poll getAgentRun(runId) until pending_approval → render the PLAN (steps + risk)
  → [Approve] approveAgentRun(runId)  /  [Reject] rejectAgentRun(runId)
  → poll getAgentRunSteps + fetchRunEvents → stream step statuses
  → terminal (completed / failed) → render result
```

Reuse `AgentConsole.jsx` + `AgentApprovalInbox.jsx` as the pattern reference. **Envelope
discipline:** read outputs from `body.data`, not the top level. Get the approve path right — the
"run stuck in `pending_approval` with no inbox entry" gap in `LIVE_VERIFICATION_SCOPE.md` is exactly
this path.

**Out of MVP scope** (later): SSE/websocket streaming (poll for now), tools browser, Infinity
"how am I doing" reads, Genesis-as-a-mode (Track 5).

**Definition of done:** a signed-in user visits `/assistant`, types a goal, sees the plan, approves
it, watches steps run, and sees the result — without touching `/platform`. Works today with
`runtime_local`; flip to Claude (Track 2) in an egress env and it *reasons*.

## Strategic diagnosis, folded in from the architecture map

**Folded 2026-08-15**, when the external artifact (v6, re-audited 2026-07-19) was retired. Every
verdict below was **re-verified against the code on 2026-08-15**, so this is the current state,
not a transcription of the July snapshot.

### The inversion — resolved

The **Infinity Algorithm** is the product: a recursive loop
(`State → Evaluate → Adjust → Act → New State`) that everything else exists to feed or execute.
It lives in `analytics`, which was once flagged `IS_CORE_DOMAIN = False` — one flag containing the
whole drift. It is now `True`. The core is marked core.

### The two re-tether frames

Structure and function, the two ways everything wires back to the core:

- **Node Stack (pillars, under MasterPlan's intent):** Intelligence `infinity` · Memory `bridge` ·
  Visibility `social` · Revenue `freelance`
- **Cognition Stack (the loop, memory as continuity throughout):**
  Perceive `search` → Reason `arm` → Act `leadgen`/`freelance` → Reflect `infinity` ↻

### The agency ladder

From `AGENTICS.md`: *"agency = intent bound to execution with continuity, memory, and time."*

| | | |
|---|---|---|
| **L0** | Assistant | Thinks, suggests. No action |
| **L1** | Tool-using assistant | Optimistic tool calls, no guarantees |
| **L2** | **Operator — where A.I.N.D.Y. is** | Decision separated from execution; state, retries, determinism, observability |
| **L3** | Autonomous system | Self-triggering, self-correcting, "knows when not to act" |

The body was built to L2 and the reasoning half was dormant. That half is now awake: Claude is the
default planner, drove a live run `plan → approve → execute → completed` with three real tasks
written to Postgres, and is user-facing. **The remaining distance to L3 is self-triggering.**

### The genesis flattening — partly recovered

The creation docs specify a nested structure: `REFLECT→EVOLVE` recursion, over a **TWR apex
ranker**, over the weighted composite `P(t) = Σwᵢfᵢ(t)`, over the metric modules. The port
flattened it to a parallel list of KPIs.

Recovered since: the composite and its per-user learned weights (`infinity_service`,
`adapt_kpi_weights`), plus a learned expectation calibrator through shadow + advisory.
**Still missing: the Elo apex ranker** — TWR is a demoted peer route and there is no rating system
(`grep -w Elo` across `apps/` and `client/src` returns nothing, confirmed 2026-08-15). The concept
is reframed, not abandoned, in
[`../handoffs/SELF_TRUST_CALIBRATION_SPEC.md`](../handoffs/SELF_TRUST_CALIBRATION_SPEC.md).

### Two knots, untangled

- **`network_bridge` is an on-ramp, not a domain.** `/user_event` → the identity spine;
  `/connect` → a thin external gateway. Payoff: "bridge" then means only the Memory Bridge, and
  the two-bridge name collision disappears. The sign-in hook shipped in #184.
- **Memory = engine + router + lens.** Engine → runtime (`AINDY.memory`); router → `bridge` (the
  real Memory Bridge); lens → `memory` (a viewer). The v0.1 core header reads
  *"Continuity > Content"* — the symbolic core survived the split intact.

### What the map still had open — status on 2026-08-15

| Map item | Now |
|---|---|
| Close the learning loops (ARM / Freelance / Search) | ✅ **Done** — #122, #126, #127 |
| **Autonomous self-triggering** | ❌ **Open.** No `register_scheduler_jobs` anywhere in `apps/`; the mechanism is FR-3 Next-Action acting, `AINDY_NEXT_ACTION_ACTING` default false |
| **Search's real send** | ❌ **Open** — `apps/search/services/lead_execution_service.py:394`, still *"a real provider send would happen here — intentionally not wired"* |
| **Soak-gated score-drive** (Phase D / Phase 2) | ❌ **Blocked, and not by soak** — see the soak audit |
| Typed `Domain`s → Composite Master Index | Scoped as the Domain Engine, not built |
| Elo apex ranker | Absent; reframed as self-trust calibration |
| Framework Forge · AI Mirror | Absent; reframed as the Creator Dashboard in `SURFACE_IDENTITY_BRIEF.md` |
| **Risk posture & ETA drift** | ❌ **Still sensed, not actuated.** `posture` is read as identity evidence and displayed in flows, but nothing consumes it to re-sequence or steer the plan |

**The July closing line — "what's left = autonomous triggering + closing the learning loops
(+ the soak-gated score-drive)" — still describes the open list**, minus the learning loops. Four
weeks of security, adoption, diagnosis and specs moved everything except those two.

## References

- Reconciled architecture map — **retired as an external artifact 2026-08-15**; its content is
  folded into this document (see the strategic-diagnosis section).
- [`../handoffs/SOAK_AUDIT_2026-08-15.md`](../handoffs/SOAK_AUDIT_2026-08-15.md) — why the
  soak-gated flags cannot be validated on current data.
- [ARCHITECTURE_MAP.md](./ARCHITECTURE_MAP.md) — code-structure reference.
- [PLUGIN_REGISTRY_PATTERN.md](./PLUGIN_REGISTRY_PATTERN.md) — how apps extend the runtime.
- `TECH_DEBT.md` — APP-DEPLOY-1 (closed), RTR-1-NODUS-APPTOOL-500 (egress), NODUS-WARMPOOL-1.
