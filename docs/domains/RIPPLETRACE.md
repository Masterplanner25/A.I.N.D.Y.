---
title: "RippleTrace"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# RippleTrace

## 1. System Role
RippleTrace is the system's influence and signal-analysis layer. It tracks content origins, ripple signals, derived patterns, and higher-level relationship views.

It is not the memory system and it is not the canonical execution runtime.
It is also not the current `SystemEvent` execution-observability layer.

## 2. Core Domain Model
- `DropPointDB`: origin content being tracked
- `PingDB`: reactions or ripple signals tied to a drop point
- derived layers: deltas, predictions, recommendations, strategies, playbooks, narratives, influence graphs, and causal graphs

## 3. Active Route Surfaces
Canonical domain routes:
- `POST /rippletrace/drop_point`
- `POST /rippletrace/ping`
- `GET /rippletrace/ripples/{drop_point_id}`
- `GET /rippletrace/drop_points`
- `GET /rippletrace/pings`
- `GET /rippletrace/recent`
- `POST /rippletrace/event`

Compatibility routes:
- `/dashboard`
- `/top_drop_points`
- `/analyze_ripple/{drop_point_id}`
- `/ripple_deltas/{drop_point_id}`
- `/emerging_drops`
- `/predict/{drop_point_id}`
- `/prediction_summary`
- `/recommend/{drop_point_id}`
- `/recommendations_summary`
- `/influence_graph`
- `/influence_chain/{drop_point_id}`
- `/causal_graph`
- `/causal_chain/{drop_point_id}`
- `/narrative/{drop_point_id}`
- `/narrative_summary`
- `/strategies`
- `/strategy/{strategy_id}`
- `/strategy_match/{drop_point_id}`
- `/build_playbook/{strategy_id}`
- `/playbooks`
- `/playbook/{playbook_id}`
- `/playbook_match/{drop_point_id}`
- `/generate_content/{playbook_id}`
- `/generate_content_for_drop/{drop_point_id}`
- `/generate_variations/{playbook_id}`
- `/learning_stats`
- `/evaluate/{drop_point_id}`

These compatibility endpoints are now served by the app-owned
`apps/rippletrace/routes/legacy_surface_router.py` (registered via the app bootstrap),
not `AINDY/main.py`.

## 4. Product Surface
- The frontend graph experience depends on the compatibility graph endpoints:
  - `/influence_graph`
  - `/causal_graph`
  - `/narrative/{drop_point_id}`
- Those routes were restored specifically to keep the GraphView and related dashboard flows working after `AINDY/main.py` cleanup.

## 5. Current Reality
Implemented:
- drop-point and ping persistence
- retrieval APIs
- dashboard snapshot generation
- delta, prediction, recommendation, narrative, influence, and causal analysis services
- graph-oriented frontend consumption through compatibility routes
- a separate `SystemEvent` observability layer exists for runtime and agent activity, but it is not the RippleTrace domain model
- execution-side RippleTrace graph building now exists on top of `SystemEvent` via `ripple_edges`
- causal event stitching now includes parent/child linkage and event -> memory links (`stored_as_memory`)
- **trace_id lineage is now structurally sound**: `SyscallDispatcher` propagates `trace_id` and `execution_unit_id` across nested syscall chains via `ContextVar`. Every call in a chain (`flow.run → memory.read → event.emit`) shares one `trace_id` — a single coherent unit in both `AgentEvent` logs and RippleTrace graphs. This was the root cause of fragmented execution graphs.

Still true:
- RippleTrace is tightly coupled to the monolith
- the compatibility surface is operationally useful but architecturally legacy
- no separate worker/eventing model exists for heavy RippleTrace computation
- the current `causal_graph` implementation is heuristic over drop points, themes, entities, timing, and velocity; it is not a true execution-causality graph
- the legacy content-domain `causal_graph` remains heuristic even though execution-side causality is now structurally modeled

## 6. Next Steps

### Step 1 - Add end-to-end validation for causal graph generation - DONE
**Files:** test coverage around `AINDY/core/system_event_service.py`, `apps/rippletrace/services/rippletrace_service.py`, `AINDY/memory/memory_capture_engine.py`  
**Outcome:** a single execution can be verified to produce reconstructable event and memory causality. Trace propagation fix makes this verifiable — a single `trace_id` now appears across all `SYSCALL_EXECUTED` events for a given run.

**Validation:** `tests/unit/test_rippletrace_causality.py` (app_profile) proves a single
execution's event **and** memory causality is reconstructable through the app-owned
`rippletrace_service`. One case builds a branched trace (an `async_child` branch plus a
`stored_as_memory` memory-node target) from `system_events` + `link_events` /
`link_event_to_memory`, then asserts node/edge counts, root + terminal detection, the
dominant path, ripple span, the event→memory edge, and user-scoped `count_trace_events`.
A second case drives the *real* `emit_system_event` and
`MemoryCaptureEngine.evaluate_and_capture` paths and asserts the same reconstruction —
covering `system_event_service` and `memory_capture_engine`. The harness compiles the
Postgres types (JSONB/UUID/Vector) to SQLite equivalents, so this runs in the fast lane.

### Step 2 - Expand execution graph validation in the frontend - DONE
**Files:** `client/src/components/platform/RippleTraceViewer.jsx`, supporting API consumers  
**Outcome:** the proofboard surface remains aligned with the newer execution-side RippleTrace graph, including memory-node targets and async branches.

**Validation:** `client/src/test/rippletrace-viewer.test.jsx` renders the RippleTrace
Proofboard against an execution graph that mixes system events, a memory-node target, and
an async branch, asserting the graph surfaces the memory node, the `stored_as_memory` and
`async_child` edges, and that the Trace Summary reflects `ripple_span` / root / terminal —
keeping the proofboard aligned with the execution-side graph.

## 7. Standalone build comparison (2026-07-05)

The original standalone RippleTrace MVP (`C:\dev\Rippletrace`, app code under
`rippletrace_mvp/`) was compared against this app. **The engine port is comprehensive
and in several ways ahead of the standalone** — every standalone engine (delta,
prediction, recommendation, learning, influence, causal, narrative, strategy, playbook,
content) exists under `apps/rippletrace/services/`, and the distinctive logic survived:

- **Adaptive learning loop is intact and richer.** `prediction_engine` reads learned
  thresholds live via `learning_engine.get_learning_thresholds`, and `adjust_thresholds`
  self-tunes them from prediction-vs-outcome accuracy — the standalone's single most
  valuable mechanism. The monolith learns **four** params (`velocity_trend`,
  `narrative_trend`, `early_velocity_rate`, `early_narrative_ceiling`) vs the standalone's
  two, and persists them through `apps/automation/public` rather than a local singleton.
- **Momentum-alignment causal heuristic**, **weighted typed influence edges**,
  **spike/delta rates**, and **narrative inflection detection** all carried over.
- **Beyond the standalone:** per-engine circuit breakers (`engine_registry`), the
  execution-side trace graph over `SystemEvent` (`rippletrace_service`, absent in the
  standalone), syscalls, and a registered flow strategy.

**One genuine regression — LLM content generation was dropped.** The standalone
`content_generator` produced drafts via `gpt-4o-mini` with a platform-aware prompt and a
clean template fallback (`source` provenance), and `generate_variations` produced real
variants. This app's `content_generator.py` is **template-only**; `generate_variations`
only appends "(1)/(2)/(3)". Since A.I.N.D.Y. is an LLM platform, the fix is to route
generation through the runtime LLM primitive (e.g. a registered agent tool), keeping the
template output as the deterministic fallback. Tracked: `TECH_DEBT.md` →
**RIPPLETRACE-CONTENT-LLM-1**.

## 8. Original blueprint concepts not yet built

Captured from `RippleTrace Blueprint.txt` so the original vision is not lost. These were
aspirational in the standalone too (partially realized or never built), so they are
**product ideas, not regressions from the port**:

- **Ghost Visibility Tracker** — detect name/keyword pickups where you are *not* explicitly
  tagged (untagged influence). No implementation in either build.
- **Time Rings visualization** — the "spiderweb meets sonar" radial graph with Day 1 / 7 /
  30 concentric rings. The current graph is a generic force/edge layout.
- **Narrative Energy Score** — an emotional/strategic-significance metric, distinct from the
  log-dampened ping-count `narrative_score`.
- **Silent Pings as a first-class taxonomy** — emails/DMs/follows/"pattern syncs" as distinct
  ping types (today only loosely inferred via `connection_type`).
- **Exportable PDF Proofboard** — a shareable executive influence summary.
