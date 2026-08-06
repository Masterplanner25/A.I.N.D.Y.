---
title: "Surface Identity — what each surface is for"
last_verified: "2026-08-06"
api_version: "1.0"
status: current
owner: "app-team"
---

# Surface Identity — what each surface is for

**Status:** decisions resolved 2026-08-06 against the original build docs and the current code.
Not an implementation plan; a settling of *what each surface is*, so implementation stops being
a matter of taste.

The frontend walk closed every defect it found and left four items marked "design — owner's
decision" (items 10, 17, 19, 23). Each was read as a separate UI question. They are not. They
are one question asked four times, and the build docs already answer it.

---

## 0. The frame

> *"You didn't build an MVP. You built a platform container. Everything else (LinkedIn, TWR,
> storytelling) becomes a tab."* — `Social Layer/KEY INSIGHTS.txt`

> *"This is not a single product — it is an operating system."* — `The Masterplan_V4`

So the unit of design is not a page. It is a **mode over one engine**. Every decision below
collapses to: *which mode does this belong to, and is it a face or a mechanism?*

Two faces, and everything sorts into them:

| Face | What it is | Modes |
|---|---|---|
| **The agent** | plans and executes *with* you | author (Genesis) · physics (MasterPlan) · work (Tasks) · run (agent) |
| **The trust layer** | how that work becomes known | creator dashboard · footprint · external echo |

Mechanisms (ARM, Nodus, the runtime, the registry, memory) are **not faces**. They are what the
faces run on, and exposing them as product surfaces is the recurring mistake.

---

## 1. Item 17 — the agent face is one surface, and it is half-built

**Resolved: one face, mode-switched.**

Genesis creates the plan, the plan is the physics, tasks are the work, the agent executes.
Splitting them into four top-level routes severed the thing that made them one product.

**Already built — more than expected:**

- `Assistant.jsx:15` — *"The user-facing face for the agent: goal → plan → approve → execute →
  result."* The Assistant **is** the agent's face, in code and in its own comment.
- It already has a **mode bar** (`agent | plan`), URL-linkable via `?mode=genesis`, and line 187
  reads *"Plan mode: the Genesis plan-authoring engine, folded into the one face."*
- Tasks can attach to a plan (`TaskDashboard.jsx:73` sends `masterplan_id`, #157), and completing
  one recalculates the plan's ETA and WCU and cascade-activates it.
- Plan import shipped (#183).

**What remains:** fold Tasks and MasterPlan in as two more modes — the same pattern, applied
twice. (`/genesis` and `/assistant` now redirect into the face; Genesis is a mode, not a route.)

### The suggestion surface is built and pointed at the wrong screen

The clearest example of "exposed workflow" being one wire short:

| Layer | State |
|---|---|
| Runtime | `suggest_tools()` + `register_tool_suggestion_provider()` — shipped in 2.0.1 |
| App | `suggest_tools_for_kpi` — derives suggestions from the **live KPI snapshot**, falling back to the latest analytics adjustment |
| Client API | `getAgentSuggestions()` — exists |
| Consumer | **`AgentConsole.jsx` only — the operator surface** |

So the system already computes *"given your current state, reach for this module"* and shows it
to an admin instead of to the user. Surfacing it on the Collaborator face is a wiring change,
not a feature build, and it is the most direct answer to "what does the agent actually do?"

### What the agent can actually do — 16 tools, audited 2026-08-06

| Module | Tools |
|---|---|
| LeadGen | `leadgen.search`, `leadgen.act` *(drafts outreach, never sends)* |
| Search / SEO / research | `search.query` *(unified over leadgen, research, SEO, memory)*, `research.query` |
| ARM | `arm.analyze`, `arm.generate`, `arm.autotune` |
| Freelance | `freelance.optimize_pricing` *(gated, revertible)*, `freelance.performance` |
| Tasks | `task.create`, `task.complete` |
| Memory | `memory.recall`, `memory.write` |
| Genesis | `genesis.message` |
| Reasoning | `reasoning.evaluate` |
| Diagnostics | `runtime.selftest` |

Each carries a **risk level** (low/medium/high) — that is what drives the approval gate. These
are the modules already exposed as capabilities; what is missing is affordance, not ability.

### Named: **Collaborator** (decided 2026-08-06)

"Assistant" is the generic word for a chat box, applied to something that does goal → plan →
**approve** → execute. The name is what made it read as "another chatbot" — the category the
product is trying not to be in.

**Collaborator** comes from the plan's own subtitle — *"A Unified Ecosystem for AI–Human
Collaboration"* — and from primary goal #3, *"position AI as a thinking partner and execution
amplifier, not a replacement for human agency."* It names the **relationship**, not the entity,
so it does not lock in one agent type.

Two candidates were rejected on evidence rather than taste:

- **SYLVA** — already taken. `AGENT_SYLVA` is one of the runtime's system agent identities
  (`AGENT_ARM`, `AGENT_GENESIS`, `AGENT_NODUS`, `AGENT_SYLVA`, `AGENT_PLATFORM`,
  `AGENT_RUNTIME`, `AGENT_MEMORY`), and the ARM blueprint casts it in a specific role:
  *"SYLVA asks questions, ARM answers with code logic."* Using it would collide with a live
  memory namespace and lock in exactly the agent type the name was meant to avoid.
- **Exodus** — would make Genesis/Nodus/Exodus read as a biblical set. Nodus is Latin for
  *knot*, which is native to Infinite Weave; the theme would be accidental.

**The decisive detail:** one line below `AGENT_SYLVA` sits `AGENT_USER = "user"`, deliberately
**excluded** from `SYSTEM_AGENTS`. The runtime already models *the user's own agent* as distinct
from the system agents. The system agents are characters with roles, so they get persona names.
This one is yours — so it gets a relationship name, and its memory namespace is already `user`.

**Tier collision, resolved by returning to canon.** `Feed.jsx` rendered the `collab` trust tier
as "COLLABORATOR", which would have meant two different things in the two faces. The Social
Layer doc's actual wording is *"inner circle, collab circle, outer ring"* — so the colliding
label was itself a drift. Labels are now `INNER CIRCLE` / `COLLAB CIRCLE` / `OUTER RING`, which
fixes the drift and frees the name.

### This also settles "what is an agent?"

Open since the agent-registry discussion and never resolved:

- **Your agent** = this face. One per user. Its memory namespace is yours.
- **The registry** = the substrate it runs on — the population, the tools, the runs.

One is the face; the other is the mechanism. Both are legitimate; conflating them is what made
the question feel unanswerable.

---

## 2. Item 19 — ARM is an organ, not a surface

**Resolved: retire the product routes; keep the tools.**

`Autonomous Reasoning Module.md` never describes a user feature. It describes A.I.N.D.Y.'s
reasoning organ — *"analyze, refactor, and generate code or logic on demand… audit itself…
learn from every execution"*, closing as *"DeepSeek becomes the 'conscious thought' layer."*
Its §9 future is agent-to-agent: *"multiple ARM instances collaborating."*

**Already built:** `arm.analyze`, `arm.generate`, `arm.autotune` are registered **agent tools**,
and ARM feeds quality signals into Infinity exactly as the blueprint's §8 metric crosswalk
specifies. The organ exists.

**The mismatch is surface only:**

| | |
|---|---|
| ARM routes in the product nav | **6** |
| `analysis_results` rows | 8 |
| `code_generations` / `arm_runs` / `arm_logs` / `arm_autotune_log` | **0** |

Six pages of configuration UI for an organ that has barely run, one of which exposes an internal
capability as though it were a user feature.

**Move:** retire the six product routes; keep ARM as agent tools; if it needs a human view, it
belongs on the operator/platform side ("what has the system been reasoning about"), not in the
product nav. That also frees the **Nodus coding agent** to be the deliberate version of the dev
tool ARM accidentally became — with ARM's tools as its hands.

---

## 3. Item 23 — Identity is two products sharing a word

**Resolved: split, then place each half.**

Audited 2026-08-06. What Identity actually tracks: `speed_vs_quality`, `risk_tolerance`,
`preferred_languages` — probabilistic, with confidence, support and a full distribution, feeding
`get_context_for_prompt()`.

The Creator Dashboard describes something else entirely under the same word — an **Identity
Graph**: *"live model of your semantic footprint… what topics and ideas are associated with
you."*

| Half | What it is | Where it belongs |
|---|---|---|
| `speed_vs_quality`, `risk_tolerance`, `languages` | **your agent's operating parameters** | the agent face (§1) |
| semantic footprint — how you are known | **the trust layer** (§4) | fed by RippleTrace |

Calling the first half "preferences" undersells it: it is the configuration of the thing that
executes for you, so it belongs next to the agent, not in a separate nav slot.

**The known defect stands:** `observe_identity_event` has exactly **one** caller
(`masterplan_factory.py:129`). One observer for a machine built to watch behaviour is the core
design flaw, and task completions, agent runs and flow outcomes are already-instrumented events
that could feed it. That is a build, not a decision.

**Naming caveat.** The Identity-Graph language in the build doc ("searchable as a concept") is
AI-Search-Optimization flavoured, and some of it is aspiration rather than spec. What makes it
*real* is a data supply — and that supply is RippleTrace, which already tracks published work
and its external echoes.

---

## 4. Item 10 — the Trust Feed should not be a feed

**Resolved: social is a mode, and its shape is the Creator Dashboard.**

> *"Social is not a product. It's a mode."* — `KEY INSIGHTS.txt`
>
> *"Scrap 1st/2nd/3rd degrees. Replace with `EngagementScore`, `TrustTier`, `SignalWeight`. Let
> users surface by value, not proximity."*
>
> *"Replace status posts with: learning logs, build-in-public threads, creator dashboards."*

`THE CORE QUESTION.txt` frames the whole layer as **anti-LinkedIn**: proof-of-work instead of
performative posts, a dynamic skills graph instead of a static resume, trust tiers instead of
connection counts.

So the feed reads thin because it renders a **trust/visibility model in the shape of a status
feed** — the wrong presentation for the data underneath. `TrustTier`, `trust_tier_required` and
`engagement_score` already exist in `apps/social/models/social_models.py`. Nothing surfaces them.

**Target shape** (`The Infinite Creator Dashboard.txt`): Command Center · Content Hub with *Idea
Lineage* · Framework Forge · Identity Graph · The Lab. Not posts-and-likes.

### The cold-start question: how do you run a trust network with no users?

Asked directly, and it has a clean answer: **the valuable half is single-player.**

Command Center, Content Hub, Framework Forge, Identity Graph and The Lab are all about *your*
content and *your* footprint. **None of them require a second user.** And the "network" they
measure against is not the local user table — it is the outside world, which is exactly what
RippleTrace already ingests: your published work and where it echoes.

That gives a sequencing that never blocks on population:

1. **n = 1 — Creator Dashboard.** Your own output, lineage, frameworks, momentum. Useful on day
   one with a single account.
2. **n = 1 + world — external signal.** RippleTrace supplies the echo: who referenced you, where,
   how far it travelled. Reputation measured against the internet, not against a headcount.
3. **n > 1 — the network proper.** Trust tiers *between* users, collaboration matching,
   peer-based opportunity. Only this tier needs population, and it is last.

The current stack has **25 users, 1 drop point and 13 pings** — so tier 1 is buildable now, tier
2 needs content ingested, and tier 3 is correctly deferred. Building the feed first inverts that
order, which is why it feels empty.

> Owner has **Moltbook** as a reference for the multi-user half. Not reviewed here; pull it in
> when tier 3 is scoped.

---

## 5. What this means together

The four surfaces resolve to two faces over one engine:

- **The agent** — Genesis authors, MasterPlan is the physics, Tasks are the work, the agent runs
  it, Identity configures it.
- **The trust layer** — the Creator Dashboard shows what the work amounts to, RippleTrace
  supplies the external signal, the footprint is how you are known.

And the differentiator against a chat interface is the same mechanism in both:

> *"Every social post → analyzed → score updated → personal model adjusted. Feedback = fuel."*
> — `KEY INSIGHTS.txt`

That is the identical shape as **emergent domain detection**
(`MASTERPLAN_DOMAIN_ENGINE_SPEC.md` §5a): the system observing what you actually do and updating
its model of you. A chat surface cannot do it — it has no persistent record of your throughput.
This is the product thesis, and it is already half-implemented in three places.

---

## 6. Sequence

Ordered by leverage, not by size. None of it is a rebuild — every item has working machinery
underneath.

1. **Rename and complete the agent face.** Fold Tasks + MasterPlan in as modes; retire the
   standalone `/genesis`; give the surface a name that says what it does.
2. **Retire the six ARM product routes.** Small, purely subtractive, removes an exposed internal.
3. **Split Identity.** Operating parameters to the agent face; footprint to the trust layer.
4. **Feed the inference engine.** Wire `observe_identity_event` to task completions, agent runs
   and flow outcomes. A build, already decided.
5. **Creator Dashboard, n=1.** Replace the feed shape with the dashboard shape, over existing
   `TrustTier` / `engagement_score`.
6. **Domain Engine phases 1–2** (`MASTERPLAN_DOMAIN_ENGINE_SPEC.md`) — the plan's physics become
   the user's own, which is what makes the agent face measure anything real.

---

## 7. Still open

- **Is the plan immutable once locked?** Settled: yes — "update" means authoring V2. Recorded
  here because it defines what the author mode offers.
- **Weight calibration** — `MASTERPLAN_GOAL_ATTAINMENT_SPEC.md` §7.
- **The Nodus coding agent** — precedent exists (ARM began as a coding dev tool); not scoped.
- **Tier 3 social** — needs population and the Moltbook review.
- **Filesystem / CLI access to the user's own files.** Raised 2026-08-06. The agent has **no
  access to user files at all** — none of the 16 tools touch them, there is no upload and no repo
  connection, and ARM reads only the server's own source (now confined to the project root by
  #194). For an agent meant to help you *execute*, and whose user's work products are files, this
  is a real capability gap — organising and working over your actual files, not only writing code.

  The blocker is deployment shape, not appetite: a hosted multi-tenant app cannot read a local
  disk. The mechanism has to be one of upload, a sync client, or a local runner. Two assets
  already exist — the sandbox (`sandbox_runner.py`, the escape-audit gate) for governed
  execution, and #194's pattern of a configurable root plus a containment check, which
  generalises to a per-user root. Nodus is the natural home, and this overlaps the unscoped
  Nodus coding agent.

- **The `/tools` page vs. suggestions.** Manual Tools already exists at `/tools`; if suggestions
  land on the Collaborator face, decide whether that page stays, folds in, or becomes the
  full catalogue behind the suggestions.
