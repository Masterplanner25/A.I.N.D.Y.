---
title: "Freelancing System"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# FREELANCING SYSTEM

> **Status update (2026-06-28).** This roadmap was written against an earlier
> state and is partly stale. Already shipped since: Stripe webhook payment
> fulfillment, refunds, subscription billing/renewal/cancellation, idempotency
> on all create/payment/refund operations, 11 freelance flow definitions, 11
> freelance `SystemEvent` types, and populated delivery/efficiency metrics —
> i.e. much of Phases 3–4 and the observability gaps. **Phase 1 (lead → client →
> order lineage) is now implemented** (see Phase 1 below). Remaining real gaps:
> agent-driven execution (Phase 2, touches runtime-owned `AINDY/`) and the
> autonomous optimization loop (Phase 5, depends on the Autonomous Reasoning
> Module). Treat the per-section "Not implemented" lists below as historical
> except where corrected.

> **Addendum (2026-07-05) — Phases 2/5 are app-doable via registration hooks, not
> `AINDY/` edits.** The per-phase "Files to modify: `AINDY/…`" lists (Phases 2, 3, 5)
> repeat the anti-pattern corrected in `docs/architecture/AGENTICS.md` and
> `docs/domains/AUTONOMOUS_REASONING_MODULE.md`: apps extend the runtime through its
> registration surface (`AINDY.platform_layer.registry`); they do not edit runtime
> code. **Phase 2** (freelance launches bounded agent runs) is app-side — register
> freelance agent tools via `register_tool` (as analytics/search/arm/tasks/masterplan
> already do; freelance has no `apps/freelance/agents/tools.py` yet — that absence *is*
> the gap) and create runs through the runtime agent-run API, mirroring ARM Phase 3's
> `reasoning.evaluate` tool. **Phase 5** consumes the now-shipped reasoning layer
> (`apps/analytics/services/reasoning/`), not a freelance-specific engine. Read the
> `AINDY/…` file lists below as runtime internals for context, not app work.
>
> the monolith now defaults to `nodus_vm` (PR #52; the runtime's own default remains
> `agent_flow`), so freelance agent runs would execute through it; freelance-specific `.nd` workflows (Phase 3 "later")
> still await the runtime `register_nodus_workflow` surface. The remaining freelance
> gaps (Phase 2 agent execution, Phase 3 client workflow automation / freelance `.nd`
> workflows, Phase 5 autonomous loop) are tracked in `TECH_DEBT.md` →
> **APP-DEBT-MIGRATED-1** ("Freelance commercial workflow incomplete").

## 1. System Reality

### What this system is intended to be

The Freelancing System is intended to be a revenue-oriented application built on
top of A.I.N.D.Y.'s core layers.

Its target role is:

- capture leads and client orders
- convert opportunities into structured work
- coordinate delivery workflows
- capture client feedback and commercial outcomes
- feed those outcomes back into memory, metrics, and future decisions

That makes it a business application layer, not core infrastructure.

### What exists today

#### Implemented

- `apps/freelance/routes/freelance_router.py`
  - authenticated CRUD-style routes for orders, delivery, feedback, and metrics

- `apps/freelance/services/freelance_service.py`
  - order creation
  - AI-generated delivery and manual delivery updates via `ai_output`
  - external delivery dispatch through configured email, webhook, or Stripe payment-link channels
  - feedback capture
  - revenue aggregation
  - execution/income metric calculation
  - Memory Bridge logging for order, delivery, and feedback events

- `apps/freelance/models/freelance.py`
  - `FreelanceOrder` (now carries `client_id` linking to a `ClientAccount`)
  - `ClientFeedback`
  - `RevenueMetrics`
  - `PaymentRecord`, `RefundRecord`, `WebhookEvent`

- `apps/freelance/models/client_account.py`
  - `ClientAccount` — commercial client/account entity (Phase 1)

- `apps/freelance/services/intake_service.py`
  - lead → client → order intake: `get_or_create_client`,
    `link_order_to_client`, `convert_lead_to_order`, `get_client_lineage`,
    `list_clients` (Phase 1)

- `client/src/components/app/FreelanceDashboard.jsx`
  - dashboard for orders, ratings, and latest revenue snapshot

- `apps/search/services/leadgen_service.py`
  - separate but relevant lead discovery/scoring capability
  - recalls prior leadgen memory, calls external search, scores leads, stores results, writes memory

- `apps/search/routes/leadgen_router.py`
  - user-facing lead generation API

#### Partially implemented

- Lead intake
  - lead generation exists
  - freelance orders exist
  - **lead → client → order lineage now exists** (Phase 1): a `ClientAccount`
    entity, orders auto-linked to a client on creation, and
    `intake_service.convert_lead_to_order` to turn a discovered lead into a
    linked client + order without re-entering commercial context

- AI-assisted delivery
  - orders support generated `ai_output`
  - delivery generation can run through the automation system
  - external delivery can run through email and webhook connectors
  - Stripe payment link mode is implemented through hosted checkout URLs
  - fulfillment confirmation is still manual unless a Stripe webhook is added

- Metrics
  - total delivered revenue is stored
  - delivery quality, time-to-completion, and income efficiency are populated
  - broader per-user revenue history and richer connector-specific metrics are still incomplete

- Memory capture
  - freelance and leadgen actions are written to memory
  - those memories do not yet drive a dedicated commercial optimization loop

#### Not implemented

_(Corrected 2026-06-28 — several previously-listed items now exist.)_

- proposal generation, outreach, and quoting
- freelance-specific **agent** execution flows (Phase 2)
- Nodus-backed freelance workflows
- autonomous client prioritization or pricing decisions (Phase 5)
- a closed feedback loop that changes execution based on freelance outcomes (Phase 5)

Already shipped (no longer "not implemented"): webhook-based payment
fulfillment, refunds, subscription billing, freelance flow definitions, and
freelance `SystemEvent` emission for order/delivery/payment/refund/subscription
actions.

### Payment Links

- Stripe support is implemented in payment-link mode only.
- A.I.N.D.Y. creates a hosted Stripe Payment Link and stores the returned URL on the order.
- The system does not yet confirm payment completion automatically.
- To automate fulfillment after payment, add a Stripe webhook handler or use manual confirmation.

## 2. Correct Classification

The Freelancing System is:

> an application layer built on top of A.I.N.D.Y. core services

It is not:

- a core execution subsystem
- a foundational infrastructure layer
- a complete autonomous business engine

### Why

- core system layers already exist elsewhere:
  - Agentics for execution
  - Memory Bridge for recall/capture
  - Infinity loop for KPI-driven next-action logic
  - `SystemEvent` for durable event persistence
  - Nodus as the intended execution substrate

- the current freelance implementation is domain-specific business logic:
  - orders
  - delivery
  - feedback
  - revenue

- it does not provide reusable platform infrastructure
- it should consume core services rather than duplicate them

Verdict:

- not a core subsystem
- not completely disconnected either
- currently a thin application layer with partial integrations and major automation gaps

## 3. Current Code Reality

### Freelancing-specific code that is real

- `apps/freelance/services/freelance_service.py`
- `apps/freelance/routes/freelance_router.py`
- `apps/freelance/models/freelance.py`
- `apps/freelance/schemas/freelance.py`
- `client/src/components/app/FreelanceDashboard.jsx`

This code now supports AI-assisted delivery generation, linked automation hooks, external email/webhook delivery, and memory logging, but it is still not a complete commercial automation layer.

### Adjacent capabilities that could support it

- `apps/search/services/leadgen_service.py`
- `apps/search/services/research_engine.py`
- `AINDY/agents/agent_runtime.py`
- `AINDY/runtime/flow_engine/runner.py`
- `AINDY/runtime/nodus_adapter.py`
- `apps/analytics/services/orchestration/infinity_orchestrator.py`
- `apps/analytics/services/orchestration/infinity_loop.py`
- `AINDY/memory/memory_capture_engine.py`

These are relevant, but they are not assembled into a true freelancing execution system today.

### What the repo does not contain

- no freelance-specific agent workflow in `apps/automation/flows/flow_definitions.py`
- no freelance-specific nodes in the flow engine
- no freelance-specific tool surface in `AINDY/agents/agent_tools.py`
- no `.nd` freelance workflows
- no freelance-specific event schema beyond typed `SystemEvent` emission
- no reasoning service for lead pursuit, pricing, or project strategy

## 4. Integration Analysis

### A. Agent Runtime

#### Current reality

- there is no direct freelance -> agent runtime integration
- freelance orders are not created or delivered as `AgentRun`s
- no freelance route calls `AINDY/agents/agent_runtime.py`

- indirect support exists only through generic tools:
  - `leadgen.search`
  - `research.query`
  - `arm.analyze`
  - `arm.generate`

#### Correct target

- freelance workflows should be able to run as agent plans when work benefits from structured execution
- examples:
  - lead research
  - proposal drafting
  - delivery artifact generation
  - client follow-up packaging

- not every client/job should automatically be an agent run
- the correct boundary is:
  - Freelancing System owns commercial workflow state
  - Agent Runtime executes bounded work units inside that workflow

### B. Nodus Execution Layer

#### Current reality

- no freelance code executes through Nodus
- no freelance `.nd` workflows exist
- no freelance route calls `AINDY/runtime/nodus_execution_service.py`

#### Correct target

- Nodus should eventually be the execution engine for repeatable freelance workflows
- examples:
  - lead qualification flow
  - project kickoff flow
  - delivery assembly flow
  - follow-up flow

- the Freelancing System should define business workflows
- Nodus should execute them

### C. Autonomous Reasoning

#### Current reality

- there is no freelance-specific reasoning layer
- no service decides:
  - which leads to pursue
  - which clients to prioritize
  - what strategy or pricing to use

- lead scoring exists in `apps/search/services/leadgen_service.py`, but that is isolated scoring logic, not a general reasoning loop

#### Correct target

Autonomous Reasoning should inform:

- lead prioritization
- next-best client action
- delivery prioritization
- pricing and packaging suggestions
- escalation from manual handling to agent execution

This should consume:

- memory
- KPIs
- recent outcomes
- feedback
- revenue performance

### D. Memory Bridge

#### Current reality

- freelance order, delivery, and feedback events are logged to memory via `MemoryCaptureEngine`
- leadgen also logs search outcomes and discovered leads to memory

#### Missing

- no unified client memory model
- no explicit memory summaries for account history or project history
- no systematic use of client outcome memory to influence future commercial decisions

#### Correct target

- each client interaction should become retrievable context
- outcomes should influence future recommendations and prioritization
- memory should support:
  - lead follow-up
  - delivery continuity
  - client preference recall
  - postmortem learning

### E. Infinity Loop

#### Current reality

- no freelance route or service directly triggers freelance-specific Infinity logic
- the current Infinity loop reasons mostly about task state, focus, AI usage, and execution quality
- leadgen and agent completion may indirectly affect score-related behavior elsewhere

#### Correct target

- freelance outcomes should influence the scoring/orchestration layer
- examples:
  - delivered work
  - positive client feedback
  - revenue conversion
  - stalled client pipelines

- the Infinity loop should eventually help decide:
  - continue delivery
  - follow up on a lead
  - create a task for a client account
  - review weak-performing revenue channels

### F. RippleTrace / SystemEvent

#### Current reality

- freelance services use logging and memory capture
- they do not emit a normalized freelance execution envelope through `SystemEvent`
- leadgen likewise writes memory but is not consistently represented as durable business events

#### Correct target

all significant freelance actions should be observable events, including:

- lead discovered
- lead scored
- order created
- work package started
- delivery completed
- feedback received
- revenue recorded

This should make commercial workflows inspectable in the same way execution workflows are becoming inspectable.

## 5. Gap Analysis

### Missing components

- client/account entity beyond raw order rows
- pipeline state between leadgen and freelance order creation
- freelance-specific agent tools and workflows
- freelance flow definitions in `apps/automation/flows/flow_definitions.py`
- Nodus workflow representation for freelance operations
- commercial metrics beyond raw revenue
- evented observability for freelance actions
- reasoning-driven optimization for outreach, prioritization, or pricing

### Missing integrations

- freelance -> agent runtime
- freelance -> Nodus execution
- freelance -> autonomous reasoning
- freelance -> Infinity loop as a first-class signal source
- freelance -> `SystemEvent` / RippleTrace observability

### Duplicated or fragmented logic

- lead qualification lives in `apps/search/services/leadgen_service.py`
- client order management lives separately in `apps/freelance/services/freelance_service.py`
- research capability lives in `apps/search/services/research_engine.py`
- none of these are composed into one commercial workflow model

### Misplaced responsibilities

- the current roadmap frames Freelancing too much like a standalone subsystem
- in reality, most automation it needs already belongs in lower layers:
  - execution in Agentics/Nodus
  - decision logic in Autonomous Reasoning
  - recall and learning in Memory Bridge
  - auditability in `SystemEvent`

The Freelancing layer should orchestrate business intent, not re-implement those foundations.

## 6. Correct Architecture

```text
A.I.N.D.Y. Core
  -> Memory Bridge
  -> SystemEvent / RippleTrace
  -> Autonomous Reasoning
  -> Agentics / Flow Engine / Nodus

Freelancing Layer
  -> lead intake
  -> client/project state
  -> commercial workflow rules
  -> delivery coordination
  -> revenue metrics

Business Workflows
  -> lead qualification
  -> outreach / proposal prep
  -> order execution
  -> delivery follow-up
  -> feedback learning
```

### Boundaries

#### A.I.N.D.Y. Core owns

- execution
- reasoning
- memory
- eventing
- policy and approvals

#### Freelancing Layer owns

- client-facing commercial workflow state
- domain rules for orders, delivery, and revenue
- mapping business stages to execution requests

#### Freelancing Layer should not own

- its own execution engine
- its own reasoning engine
- its own memory platform
- its own observability substrate

## 7. Implementation Plan

### Phase 1. Lead Intake + Storage - DONE

Objective:

- unify lead discovery and freelance intake into one commercial entry path

**What shipped (2026-06-28):**

- New `ClientAccount` model (`apps/freelance/models/client_account.py`,
  table `freelance_client_accounts`) — a commercial client owned by a freelancer
  `user_id`, identified by client email, recording `source`
  (`manual`/`order`/`leadgen`) and a soft `lead_id` reference to the originating
  leadgen result (no cross-app FK).
- `FreelanceOrder.client_id` FK → `ClientAccount`; `freelance_service.create_order`
  now resolves/creates the client and links every order at insert time.
- `apps/freelance/services/intake_service.py`: `get_or_create_client` (never
  downgrades a richer origin), `link_order_to_client`, `convert_lead_to_order`
  (carries the lead's company/url/context/reasoning into the order so commercial
  context is not re-entered), `get_client_lineage`, `list_clients`.
- `apps/search/public.get_lead_by_id` — public accessor so freelance reads leads
  through the search contract, not its internals.
- Routes/flows: `GET /freelance/clients`, `GET /freelance/clients/{id}` (lineage),
  `POST /freelance/intake/from-lead` (+ matching flow nodes/results).
- Migration `a1c2e3f4b5d6_add_freelance_client_accounts` (idempotent, guarded).

**Tests:** `tests/unit/test_freelance_intake.py` (app_profile) — order→client
linking, email→client reuse, no source downgrade, lineage + listing, the public
lead accessor, and full lead→client→order conversion.

Success criteria — met:

- system can track lead → client → order lineage (`get_client_lineage`)
- user can query commercial state via the clients/lineage endpoints

**Deferred:** a dedicated clients view in `FreelanceDashboard.jsx` (UI is Phase 4
territory); storing the reverse `client_id` on `leadgen_results` (lineage is held
on the freelance side via `ClientAccount.lead_id`).

### Phase 2. Agent-driven Task Execution

Objective:

- let the Freelancing layer request bounded work from Agentics rather than doing everything manually

Files to modify:

- `AINDY/agents/agent_runtime.py`
- `AINDY/agents/agent_tools.py`
- `apps/freelance/services/freelance_service.py`
- `apps/freelance/routes/freelance_router.py`
- `apps/automation/flows/flow_definitions.py`

Files to create:

- `services/freelance/execution_service.py` _(planned; not yet present)_
- freelance-oriented tool handlers or agent wrappers

Expected behavior:

- freelance workflows can launch agent runs for scoped tasks such as research, drafting, packaging, and delivery preparation

Success criteria:

- at least one freelance workflow creates an auditable `AgentRun`
- freelance layer references agent results rather than storing only manual output strings

### Phase 3. Client Workflow Automation — DONE (2026-07-17)

Objective:

- define repeatable commercial workflows above the raw services

Shipped: two multi-step, state-threaded client-workflow flows in
`apps/freelance/flows/freelance_flows.py`, registered via `register_flow` (app-owned —
no runtime edit) and run through the existing flow engine, each step its own observable
`FlowHistory` entry:

- **`freelance_client_onboarding`** — `onboarding_intake` → `onboarding_dispatch` →
  `onboarding_summarize`: convert a qualified lead into a client + order, then dispatch
  delivery generation when the intake asked for it (resilient — a dispatch failure is
  recorded, not raised, since the client/order are already committed), and return a
  consolidated envelope with a `next_action`. The order id minted at step 1 threads
  forward to drive the dispatch step. Exposed at `POST /apps/freelance/clients/onboard`.
- **`freelance_order_fulfillment`** — `fulfillment_deliver` → `fulfillment_metrics`:
  attach the deliverable to an order, then refresh revenue metrics in the same flow so
  they reflect the delivery. Exposed at `POST /apps/freelance/orders/{order_id}/fulfill`.

**Tests:** `tests/unit/test_freelance_client_workflow.py` (node contracts + full-chain
state threading), `tests/integration/test_freelance_client_workflow.py` (endpoint
contracts).

Deferred (not app-doable): repo-managed freelance `.nd` workflows when Nodus becomes the
primary execution surface — gated on the same runtime execute-to-completion work as the
analytics `reasoning_apply_v1` native-Nodus routing (see `TECH_DEBT.md`).

Success criteria — met:

- ✅ two end-to-end freelance workflows execute through the existing flow layer
- ✅ workflow state is durable and inspectable (per-step `FlowHistory`)

### Phase 4. Revenue Tracking + Metrics

Objective:

- move from raw revenue snapshots to meaningful commercial performance metrics

Files to modify:

- `apps/freelance/services/freelance_service.py`
- `apps/freelance/models/freelance.py`
- `apps/freelance/routes/freelance_router.py`
- `client/src/components/app/FreelanceDashboard.jsx`

Expected behavior:

- compute real metrics for delivery speed, conversion, and AI leverage
- expose them in API and dashboard

Success criteria:

- metrics fields are populated from real data
- dashboard reflects workflow performance rather than only counts and revenue

### Phase 5. Autonomous Optimization

Objective:

- connect commercial outcomes to reasoning, memory, and observability

Files to modify:

- `apps/analytics/services/orchestration/infinity_orchestrator.py`
- `apps/analytics/services/orchestration/infinity_loop.py`
- `AINDY/core/system_event_service.py`
- `AINDY/memory/memory_capture_engine.py`
- future reasoning service files from `docs/domains/AUTONOMOUS_REASONING_MODULE.md`

Potential files to create:

- `services/freelance/recommendation_service.py` _(planned; not yet present)_
- `services/reasoning/` _(planned; not yet present)_ commercial evaluators when the reasoning layer is formalized

Expected behavior:

- the system can recommend what lead to pursue, what client to follow up with, and what work to prioritize based on outcomes and memory

Success criteria:

- freelance activity emits durable events
- commercial outcomes influence future suggestions or task creation
- no duplicate business-specific reasoning engine is created outside the main reasoning layer

## 8. Relationship to Other Roadmaps

### AGENTICS.md

This document depends on `docs/architecture/AGENTICS.md`:

- Freelancing should consume Agentics for execution
- it should not implement a separate execution runtime

### AUTONOMOUS_REASONING_MODULE.md

This document depends on `docs/domains/AUTONOMOUS_REASONING_MODULE.md`:

- Freelancing should consume the shared reasoning layer for prioritization and adaptation
- it should not implement a separate reasoning engine

### EVOLUTION_PLAN.md

This document aligns with `docs/architecture/EVOLUTION_PLAN.md`:

- Freelancing should evolve after or alongside completion of shared execution, reasoning, and observability layers
- it should not bypass the core architecture

### TECH_DEBT.md

This document aligns with `TECH_DEBT.md`:

- current debt is not just missing features
- the bigger issue is incomplete integration with the platform layers it should sit on top of

## 9. Final Assessment

The Freelancing System is real, but only in a narrow form.

What exists today:

- order storage
- manual delivery updates
- feedback capture
- basic revenue aggregation
- memory logging
- adjacent lead generation support

What it is today:

- a partial application layer

What it is not today:

- a core subsystem
- an autonomous revenue engine
- a true agent-driven or Nodus-driven business workflow system

The correct path is to build Freelancing on top of A.I.N.D.Y.'s shared
execution, reasoning, memory, and event layers rather than expanding it into a
parallel infrastructure stack.
