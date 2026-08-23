---
title: "Agentics"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# AGENTICS

Ownership note:

- this document belongs to the A.I.N.D.Y. repo
- it should not be treated as the runtime execution contract
- the runtime execution contract lives in the separate `aindy-runtime` repo
- the apps-side dependency boundary is documented in
  [Runtime Dependency](./RUNTIME_DEPENDENCY.md)

This document covers the Agentics app-domain feature: gap analysis, completion
roadmap (Phases A–E), Nodus integration plan, and relationship to other
roadmaps.

For the runtime execution contract — public API, capability enforcement,
per-step retry, recovery/replay, and state machine — see the runtime repo's
`AGENT_RUNTIME.md`.

Date basis: current workspace state.

## App-side status (2026-06-29)

This doc is the artifact whose work produced the `aindy-runtime` split — which is
why Phases A–E below list mostly `AINDY/` files. Per the apps/runtime boundary,
**apps do not edit runtime; they extend it through registration hooks**
(`AINDY.platform_layer.registry`). App-ownable surface by phase:

- **A — Execution Integrity:** *mixed.* App-owned: the client
  `AgentConsole.jsx` / `AgentApprovalInbox.jsx`, the app router
  `apps/agent/routes/agent_router.py`, and the completion hook. Runtime-owned: the
  execution core (`agent_runtime`, `flow_engine/runner`, `async_job_service`,
  `stuck_run_service`).
- **B — Nodus Integration:** *runtime-owned.* No app lever — there is no
  registration surface for the Nodus VM / `.nd` workflows; making Nodus the
  primary substrate is a runtime feature request in `aindy-runtime` (same gap
  noted in `AUTONOMOUS_REASONING_MODULE.md` Phase 4).
- **C — Autonomous Loop:** *strong app lever.* The execute/defer/ignore decision
  policy is app-owned (`apps/agent/agents/triggers.py` via
  `register_trigger_evaluator`, used for every trigger type through the "default"
  fallback), and app schedulers/flows drive the trigger→decide loop; the
  autonomous-controller plumbing and bounded-loop primitives are runtime.
- **D — Multi-Agent Coordination:** *mostly runtime.* The only registerable lever
  is the agent ranking strategy (`apps/masterplan/agents/ranking.py` via
  `register_agent_ranking_strategy`). Delegation, the agent registry, and conflict
  resolution are runtime-internal.
- **E — Production Hardening:** *runtime-owned* (durable workers, queue isolation,
  event retention). Apps contribute tests and `register_async_job` usage only.

**Hardened (2026-06-29):** the app-owned decision levers — previously untested —
now have coverage in `tests/unit/test_agentics_app_levers.py`: the autonomy
trigger evaluator (execute/defer/ignore policy), the agent ranking strategy, and
the post-run completion hook that enforces the Infinity loop. The per-phase
"Exact files/modules affected: `AINDY/...`" lists below should be read as the
*runtime* work; the app-side levers are the registration hooks named here.

## Status update — Phase B substantially resolved (2026-07-05)

**Supersedes the "Nodus is not the primary execution path" conclusion throughout
this doc (§1 *Partially working / Not implemented*, §4 Phase B, §5 *Verdict*, and
the *Summary*).** Those sections predate the RTR-1 work and are retained below as
the historical baseline the roadmap was built from — they are no longer current.

- **`nodus_vm` is now this monolith's DEFAULT agent-execution backend** (the runtime's
  own default remains `agent_flow`; the monolith opts in) on every
  non-test boot (`apps/agent/bootstrap.py::_select_execution_backend` →
  `os.environ.setdefault("AINDY_AGENT_EXECUTION_BACKEND", "nodus_vm")`, PR #52,
  2026-07-05). An explicit env value (ops override / pytest ini) always wins; the
  integration harness stays on `agent_flow` because it runs no scheduler heartbeat.
- **Phase B core objective is met at the app-default level.** RTR-1 §5 is fully
  validated on live-Postgres CI (`tests/integration/test_nodus_vm.py`, runtime
  `>=1.5.3`): both gates hard-assert that app-manifest tools **resolve, dispatch,
  and complete their DB writes inside the `nodus_worker` subprocess**, and that a
  WAIT/resume run drives to a terminal state. This closes the gap the doc's §1/§5
  describe as "Nodus is used only for restricted ad hoc execution."
- **Still open, and tracked (not app edits):**
  - Full-surface validation of nodus_vm-as-default — real multi-step LLM plans,
    completion hooks, and Infinity orchestration under the default — is not yet
    CI-proven (only the two §5 gates are). Tracked: `TECH_DEBT.md`
    → **RTR-1-NODUS-COMPLETION** (reopen trigger).
  - `.nd` workflow authoring/storage/versioning in-repo and agent-plan→`.nd`
    compilation (Phase B's remaining sub-goals) still have no app registration
    surface — a runtime `register_nodus_workflow`-style hook is a feature request in
    `aindy-runtime`. Tracked: `TECH_DEBT.md` → **APP-DEBT-MIGRATED-1** ("Nodus-native
    reasoning execution deferred (runtime)").
  - Phases D (multi-agent delegation/registry/conflict, minus the done ranking
    lever) and E (durable workers, queue isolation) remain runtime-owned. Tracked:
    `TECH_DEBT.md` → **APP-DEBT-MIGRATED-1** ("Agentics completion is runtime-owned").

**Verdict:** this doc is **tracked**, and now **current** at the top; the body
sections listed above are historical. Every open Agentics item has a `TECH_DEBT.md`
entry with a reopen trigger, and the runtime-owned items are handed to
`aindy-runtime`.

## 1. System Reality

### What Agentics currently does

Agentics is no longer conceptual. A.I.N.D.Y. already has a functioning
single-agent execution layer built from:

- `AINDY/agents/agent_runtime.py`
- `AINDY/agents/agent_tools.py`
- `AINDY/runtime/nodus_adapter.py`
- `AINDY/runtime/flow_engine/runner.py`
- `AINDY/routes/agent_router.py`
- `apps/agent/models/agent_run.py`
- `apps/agent/models/agent_event.py`
- `AINDY/agents/capability_service.py`

The current lifecycle is:

`goal -> GPT plan -> approval gate -> scoped capability minting -> deterministic execution -> event log -> memory capture -> infinity loop follow-up`

### Production-ready or close to production-ready

- Agent run creation, approval, rejection, replay, recovery, step inspection, and event timeline APIs are implemented in `AINDY/routes/agent_router.py`.
- The agent planner is live in `AINDY/agents/agent_runtime.py` and uses GPT-generated structured plans over a fixed tool registry.
- The execution path is deterministic in practice because approved plans are executed through `PersistentFlowRunner` in `AINDY/runtime/flow_engine/runner.py` via `AINDY/runtime/nodus_adapter.py`.
- Per-run scoped capability enforcement exists in `AINDY/agents/capability_service.py` and is checked both before flow execution and before tool execution.
- Agent lifecycle audit persistence exists through `AgentRun`, `AgentStep`, `AgentEvent`, and `SystemEvent`.
- Recovery and replay paths exist through `AINDY/agents/stuck_run_service.py` and `AINDY/agents/agent_runtime.py`.
- The frontend has both an operator console and a dedicated approval inbox:
  - `client/src/components/platform/AgentConsole.jsx`
  - `client/src/components/platform/AgentApprovalInbox.jsx`

### Partially working or transitional

- The execution backbone is A.I.N.D.Y.'s internal flow engine, not the real Nodus DSL/VM path. `AINDY/runtime/nodus_adapter.py` is an adapter over `PersistentFlowRunner`, not an adapter over the installed Nodus compiler/VM.
- The Infinity loop is integrated as post-execution orchestration in `apps/analytics/services/orchestration/infinity_orchestrator.py` and `apps/analytics/services/orchestration/infinity_loop.py`, but it is still heuristic and trigger-based rather than autonomous planning/execution.
- Flow execution exists for ARM, task completion, leadgen, genesis message, genesis conversation, memory execution, and watcher ingest, but strategy learning is mostly structural. `select_strategy()` and `update_strategy_score()` exist, yet there is no broad learned strategy corpus driving the system.
- Async execution exists in `AINDY/platform_layer/async_job_service.py`, but it is an in-process thread-pool queue, not a durable distributed worker system.
- The installed Nodus runtime is used only for restricted ad hoc execution through `AINDY/runtime/nodus_execution_service.py` and `POST /memory/nodus/execute`, not as the primary execution path for agents or flows.

### Not implemented

- Agent plans are not compiled to `.nd` source, bytecode, or VM programs anywhere in this repository.
- There are no checked-in `.nd` workflow assets in the repo.
- The agent runtime does not execute through the installed Nodus compiler/VM stack.
- Nodus execution traces are not the canonical source of `FlowRun`, `AgentEvent`, or `SystemEvent`.
- Multi-agent delegation and coordination are not implemented.
- Autonomous closed-loop agent execution is not implemented beyond post-run suggestion/orchestration.
- RippleTrace is not yet the unified event intelligence layer for Agentics.

## 2. Architecture (Corrected)

### Current implemented architecture

```text
User / API / UI
  -> Agent Runtime
     (`AINDY/agents/agent_runtime.py`)
  -> Tool Registry + Capability Enforcement
     (`AINDY/agents/agent_tools.py`, `AINDY/agents/capability_service.py`)
  -> Internal Flow Engine
     (`AINDY/runtime/flow_engine/runner.py`)
  -> Agent Flow Adapter
     (`AINDY/runtime/nodus_adapter.py`)
  -> Domain Services / Tools
     (tasks, memory, ARM, Genesis, LeadGen, watcher)
  -> Event Persistence
     (`AgentEvent`, `SystemEvent`, `FlowRun`, `FlowHistory`)
  -> Memory Capture
     (`AINDY/memory/memory_capture_engine.py`)
  -> Infinity Follow-up
     (`apps/analytics/services/orchestration/infinity_orchestrator.py`, `apps/analytics/services/orchestration/infinity_loop.py`)
```

### Intended corrected architecture

```text
A.I.N.D.Y. = intelligence + planning + policy + orchestration
Nodus      = declarative workflow language + compiler + VM execution layer

Planner / Runtime policy
  -> Nodus workflow selection or generation
  -> Nodus compile / load
  -> Nodus VM execution
  -> execution events + checkpoints
  -> RippleTrace / SystemEvent ledger
  -> Memory Bridge writes + recall feedback
  -> Infinity loop / higher-order orchestration
```

### Component definitions

- Agent Runtime
  - Current role: plan generation, approval, capability minting, run lifecycle management.
  - Primary files: `AINDY/agents/agent_runtime.py`, `AINDY/routes/agent_router.py`.

- Nodus Execution Layer
  - Intended role: declarative workflow language, compiler, bytecode/VM execution, deterministic traces.
  - Current reality: only partially present through the installed `nodus` package and `AINDY/runtime/nodus_execution_service.py`.
  - Not yet the default execution substrate for Agentics.

- Flow Engine
  - Current role: A.I.N.D.Y.'s actual execution backbone.
  - Primary files: `AINDY/runtime/flow_engine/runner.py`, `apps/automation/flows/flow_definitions.py`, `AINDY/routes/flow_router.py`.
  - Supports DB-backed state, WAIT/RESUME, flow history, and completion capture.

- Infinity Loop
  - Current role: post-execution score recalculation and next-action suggestion.
  - Primary files: `apps/analytics/services/orchestration/infinity_orchestrator.py`, `apps/analytics/services/orchestration/infinity_loop.py`.
  - Not yet an autonomous agent controller.

- Memory Bridge
  - Current role: recall, capture, federated memory, feedback weighting, and Nodus memory helpers.
  - Primary files: `AINDY/memory/memory_capture_engine.py`, `AINDY/memory/nodus_memory_bridge.py`, `AINDY/routes/memory_router.py`.

- RippleTrace / SystemEvent layer
  - Current role: partially split.
  - Durable execution/event ledger exists in `AINDY/db/models/system_event.py` and `AINDY/core/system_event_service.py`.
  - RippleTrace as a higher-order pattern/graph/insight layer remains incomplete.

## 3. Gap Analysis

### Missing capabilities

- Real Nodus-backed agent execution path.
- `.nd` workflow authoring, storage, loading, and versioning inside A.I.N.D.Y.
- Compile-to-bytecode or VM-backed execution for agent plans.
- Unified Nodus trace -> `FlowRun` / `AgentEvent` / `SystemEvent` mapping.
- Agent-to-agent delegation and shared execution contracts.
- Autonomous trigger -> plan -> execute loops without manual initiation.
- Rich egress policy beyond capability checks and per-tool metadata.

### Broken or partial flows

- The naming around "Nodus" is architecturally misleading today:
  - `AINDY/runtime/nodus_adapter.py` does not use the installed Nodus VM.
  - the real installed Nodus runtime is only used by `AINDY/runtime/nodus_execution_service.py`
- The current agent plan format is JSON from GPT, not a declarative Nodus workflow.
- Memory-side Nodus execution is isolated from the flow engine and agent runtime.
- `select_strategy()` and `update_strategy_score()` exist, but the broader adaptive strategy loop is not yet driving runtime behavior across Agentics.
- Async execution is in-process only, so execution durability and worker isolation are limited.

### Inconsistencies

- The repo has two execution concepts:
  - internal flow execution via `PersistentFlowRunner`
  - embedded Nodus runtime execution via `NodusRuntime`
- Agentics documentation that treats Nodus integration as complete is inaccurate.
- Agentics documentation that says the system is not implemented is also inaccurate.
- RippleTrace is not yet the canonical intelligence layer over execution events.

### Architectural drift

- The internal flow engine has become the de facto execution layer that the long-term architecture intended Nodus to own.
- The term "Nodus" is currently used for both:
  - a future primary execution substrate
  - an existing restricted embedded runtime endpoint
- Without consolidation, A.I.N.D.Y. risks carrying two parallel workflow systems indefinitely.

## 4. Agentics Completion Plan

### Phase A - Execution Integrity

Objective:
- Stabilize the current internal agent/runtime path as the transitional production base.

Required components:
- agent runtime lifecycle hardening
- flow/agent/event consistency
- stronger execution ownership and observability

Exact files/modules affected:
- `AINDY/agents/agent_runtime.py`
- `AINDY/runtime/nodus_adapter.py`
- `AINDY/runtime/flow_engine/runner.py`
- `AINDY/platform_layer/async_job_service.py`
- `AINDY/agents/stuck_run_service.py`
- `AINDY/routes/agent_router.py`
- `AINDY/routes/flow_router.py`
- `client/src/components/platform/AgentConsole.jsx`
- `client/src/components/platform/AgentApprovalInbox.jsx`

Success criteria:
- every agent run has one authoritative execution record path
- queued, running, failed, replayed, and recovered states are fully inspectable
- async execution can be resumed or audited without relying on process memory
- no ambiguity remains between agent run state and linked `FlowRun`

### Phase B - Nodus Integration Completion

Objective:
- Make real Nodus the primary execution substrate instead of the internal flow engine naming shim.

Required components:
- Nodus workflow source management
- compile/load pipeline for `.nd` assets or generated workflows
- VM execution adapter into A.I.N.D.Y.'s DB/event model
- checkpoint and trace mapping

Exact files/modules affected:
- `AINDY/runtime/nodus_execution_service.py`
- `AINDY/runtime/nodus_adapter.py`
- `AINDY/runtime/flow_engine/runner.py`
- `AINDY/core/system_event_service.py`
- `AINDY/agents/agent_event_service.py`
- `AINDY/memory/nodus_memory_bridge.py`
- `AINDY/routes/memory_router.py`
- `AINDY/routes/agent_router.py`
- new Nodus workflow asset location in-repo

Success criteria:
- agent execution can run through the installed Nodus compiler/VM path
- `.nd` workflows exist in-repo and are versioned
- Nodus execution emits durable `SystemEvent` and `AgentEvent` records
- `FlowRun` either becomes a Nodus-backed run record or is cleanly superseded

### Phase C - Autonomous Agent Loop

Objective:
- Promote the current post-run Infinity follow-up into a controlled autonomous operating loop.

Required components:
- trigger ingestion
- planner re-entry rules
- policy-based autonomous execution windows
- bounded loop scheduling

Exact files/modules affected:
- `apps/analytics/services/orchestration/infinity_orchestrator.py`
- `apps/analytics/services/orchestration/infinity_loop.py`
- `AINDY/agents/agent_runtime.py`
- `AINDY/core/system_event_service.py`
- `AINDY/routes/observability_router.py`
- scheduler integration under `services/`

Success criteria:
- approved triggers can generate bounded autonomous runs
- loop decisions are persisted and replayable
- no infinite execution chains occur without explicit policy
- next-action generation can become next-run generation under controlled conditions

### Phase D - Multi-Agent Coordination

Objective:
- Extend Agentics from single-agent execution to coordinated agent systems.

Required components:
- agent registry integration with runtime
- delegation contracts
- shared/private memory boundaries
- inter-agent event and approval model

Exact files/modules affected:
- `AINDY/db/models/agent.py`
- `AINDY/routes/memory_router.py`
- `AINDY/memory/nodus_memory_bridge.py`
- `AINDY/agents/agent_runtime.py`
- `AINDY/agents/capability_service.py`
- `AINDY/runtime/flow_engine/runner.py`
- new coordination/orchestration service layer

Success criteria:
- one agent can delegate a scoped task to another
- memory sharing rules are explicit and enforced
- capability tokens can be constrained per delegated sub-run
- operator surfaces show parent/child agent relationships

### Phase E - Production Hardening

Objective:
- Harden the completed Agentics layer for long-running, multi-instance operation.

Required components:
- durable worker model
- execution queue isolation
- standardized policy enforcement
- stronger event and trace retention

Exact files/modules affected:
- `AINDY/platform_layer/async_job_service.py`
- `AINDY/core/system_event_service.py`
- `AINDY/routes/observability_router.py`
- deployment/runtime configuration
- testing under `tests/`

Success criteria:
- execution survives process restarts and multi-instance deployment
- operator audit views cover agent, flow, and Nodus execution uniformly
- failure handling is deterministic and observable
- automated tests cover agent, flow, and Nodus integration paths end to end

## 5. Integration With Nodus

### Current level of integration

The installed Nodus package is real and available in the venv. It exposes a
compiler/runtime stack and an embedded execution API through
`nodus.runtime.embedding.NodusRuntime`.

Current A.I.N.D.Y. integration points are:

- `AINDY/runtime/nodus_execution_service.py`
  - executes source strings through `NodusRuntime.run_source()`
- `AINDY/runtime/nodus_security.py`
  - restricts imports, file access, network access, and operation usage
- `AINDY/memory/nodus_memory_bridge.py`
  - exposes memory operations such as recall/remember/suggest/record_outcome
- `AINDY/routes/memory_router.py`
  - exposes `POST /memory/nodus/execute`

### Missing integration points

- Agent runtime does not generate or execute Nodus workflows.
- `AINDY/runtime/nodus_adapter.py` does not call the Nodus compiler or VM.
- No repository-managed `.nd` modules or packages exist.
- No bytecode artifacts or compiled workflow cache are stored by A.I.N.D.Y.
- Nodus runtime events are not mapped into `AgentEvent` or `FlowHistory`.
- Nodus is not registered as the execution substrate for flow definitions in `apps/automation/flows/flow_definitions.py`.

### Required work to make Nodus the primary execution path

- Define a canonical mapping from agent plan -> Nodus workflow.
- Decide whether plans become:
  - generated `.nd` source
  - templated `.nd` workflows with parameter injection
  - or precompiled Nodus workflow packages
- Replace or wrap `PersistentFlowRunner` with a real Nodus-backed execution adapter.
- Persist Nodus execution traces into A.I.N.D.Y.'s observability model.
- Route memory operations through `NodusMemoryBridge` without isolating them to the memory endpoint only.
- Standardize approval, capability, and egress policy at the Nodus execution boundary.

Verdict:
- Nodus is present.
- Nodus is not yet the primary Agentics execution layer.
- The current system is best described as an internal flow-engine-based Agentics layer with limited embedded Nodus support.

> **Superseded (2026-07-05):** `nodus_vm` is now the app's default agent-execution
> backend and §5 proves app-manifest tools execute to completion in the
> `nodus_worker` subprocess. See the *Status update — Phase B substantially
> resolved (2026-07-05)* section near the top. The verdict above is the pre-RTR-1
> baseline.

## 6. Relationship to Other Roadmaps

### `TECH_DEBT.md`

Agentics-specific debt now centers on:

- the split between the internal flow engine and real Nodus execution
- single-agent limitations
- incomplete autonomous loop behavior
- in-process async execution durability
- incomplete normalization of execution telemetry across domains

### `EVOLUTION_PLAN.md`

The evolution plan should treat:

- current `PersistentFlowRunner` execution as transitional infrastructure
- Nodus as the target core execution substrate
- Agentics completion as a dedicated evolution phase rather than an assumed completed layer

## Summary

Agentics is implemented enough to be operational today, but it is not complete
and it is not yet the intended A.I.N.D.Y. + Nodus architecture.

Current truth:

- A.I.N.D.Y. has a real agent runtime.
- A.I.N.D.Y. has a real internal deterministic flow engine.
- A.I.N.D.Y. has limited embedded Nodus execution for memory-side tasks.
- A.I.N.D.Y. does not yet run Agentics primarily through real Nodus workflows and VM execution.

That is the baseline this roadmap should be built from.

> **Superseded (2026-07-05):** the last line is no longer true — `nodus_vm` is the
> app's default agent-execution backend as of PR #52, and RTR-1 §5 proves execution
> to completion through the Nodus VM subprocess. This summary is the pre-RTR-1
> baseline; see the *Status update — Phase B substantially resolved (2026-07-05)*
> section near the top for current state.
