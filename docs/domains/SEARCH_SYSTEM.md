---
title: "Search System"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# Search System — Canonical Definition & Evolution Plan

---

## 1. System Definition (Canonical)

The Search System is a **multi-surface AI retrieval stack** that turns queries into ranked, actionable results across SEO analysis, lead discovery, and research workflows.

It is not a single endpoint.

It is a **search orchestration layer** intended to:

* process queries
* retrieve sources
* score relevance
* persist outcomes
* feed back into execution

---

## 2. Core Lifecycle (Canonical Pipeline)

```
Query -> Processing -> Retrieval -> Ranking -> Output
```

### Query

User or system-provided search intent:

* free text
* domain-specific templates
* task or research prompts

---

### Processing

Normalization and pre-processing:

* tokenization
* query expansion
* domain filtering

---

### Retrieval

External or internal source fetch:

* web search
* stored research results
* memory recall

---

### Ranking

Scoring and ordering:

* relevance
* fit / intent scores
* semantic similarity

---

### Output

Structured results:

* ranked leads
* SEO insights
* research summaries

---

## 3. Core Components

---

### 3.1 SEO Analysis (AI SEO)

**Implementation:**

* `apps/search/routes/seo_routes.py`
* `apps/search/services/seo_services.py`

**Current Capabilities:**

* keyword extraction
* readability
* keyword density
* AI meta description (`/seo/meta`)

**Missing:**

* AI SEO improvement suggestions (stubbed)
* competitor benchmarking
* AI search ranking feedback loop

---

### 3.2 Lead Generation (B2B AI Search)

**Implementation:**

* `apps/search/services/leadgen_service.py`
* `apps/search/routes/leadgen_router.py`
* `apps/search/models/leadgen_model.py`

**Current Capabilities:**

* GPT-4o lead scoring
* DB persistence
* Memory Bridge logging
* Memory Orchestrator recall for prior leadgen context
* External retrieval via `apps/search/services/research_engine.web_search()` with structured response parsing + fallback

**Missing:**

* provider-backed lead search with richer parsing (current structured parsing is minimal)
* query template system (documented but not implemented)

---

### 3.3 Research / DeepSearch

**Implementation:**

* `apps/search/services/research_engine.py`
* `apps/search/routes/research_results_router.py`
* `apps/search/services/research_results_service.py`

**Current Capabilities:**

* research result storage
* memory logging (capture engine)
* Memory Orchestrator recall attached to `/research/query` results
* Live summary generation via `apps/search/services/research_engine.ai_analyze()`
* Live external retrieval via `apps/search/services/research_engine.web_search()`

**Missing:**

* external provider reliability/coverage guarantees (current integration is best-effort)

---

### 3.4 Memory Search (Semantic Recall)

**Implementation:**

* `AINDY/routes/memory_router.py`
* `AINDY/db/dao/memory_node_dao.py`

**Current Capabilities:**

* semantic similarity search (`/memory/nodes/search`)
* resonance recall (`/memory/recall`)

**Note:**

This capability exists but is not wired into the Search System flows documented under `AINDY/Search System/`.

---

## 4. Architectural Layers

### Retrieval Layer

* External search (implemented in research + leadgen flows)
* Internal search (Memory Bridge recall)

### Orchestration Layer

* FastAPI routes
* service modules

### Persistence Layer

* Postgres models for leadgen + research
* Memory Bridge for search outcomes

---

## 5. Current Implementation (Reality)

**Implemented:**

* basic SEO analysis endpoints
* lead scoring + DB persistence
* research result storage
* Memory Orchestrator recall used in LeadGen and Research query flow
* semantic memory search (separate system)
* live external retrieval in research and leadgen flow

**Missing:**

* (none of the original roadmap items remain) — unified search pipeline, reusable
  hybrid orchestration, shared ranking, and SEO/LeadGen/Research UI are all
  implemented; see the Phase Mapping table and Next Steps below.

---

## 6. System Classification

The Search System is currently:

> A unified multi-surface retrieval stack: SEO, LeadGen, and Research share one
> `search_service`, a normalized `SearchRequest`/`SearchResponse` contract, a shared
> lexical+hybrid ranking layer, a `search.query` agent tool, and the `unified_search`
> workflow. Semantic memory recall is integrated into the leadgen/research flows.

It is now (Phase v4, 2026-07-17):

* a closed-loop AI search optimizer — outcomes are captured (`SearchResultFeedback`,
  implicit + explicit) and, behind `AINDY_SEARCH_OUTCOME_WEIGHTING`, re-weight future
  query ranking; the flag is off by default pending a live-data soak before the flip
* an AI SEO optimizer — SEO *improvement* suggestions ship via `seo_improvement_suggestions` (§3.1)

---

## 7. Evolution Plan (System Roadmap)

---

### Phase v1 — Stabilize Search Surfaces

**Goal:** Align live endpoints with documented behaviors

**Actions:**

* normalize SEO endpoints
* remove stubbed responses or mark them explicitly
* document leadgen retrieval integration ✅

---

### Phase v2 — Retrieval Integration

**Goal:** Enable real retrieval for leadgen + research

**Actions:**

* wire `apps/search/services/research_engine.py` into `/research/query` ✅
* replace mocked `run_ai_search()` results with real provider calls ✅
* integrate Memory Orchestrator recall into search flows ✅

---

### Phase v3 — Ranking Unification

**Goal:** Shared ranking layer

**Actions:**

* unify relevance scoring across SEO, leadgen, research - DONE

A shared lexical relevance signal (`lexical_relevance`) plus a `composite_score`
(0.6 relevance / 0.4 surface quality) now live in `apps/search/services/search_scoring.py`.
The `rank_items` ranker in `apps/search/schemas/search_schema.py` applies them so
every surface's `SearchResponse.results` carry one unified `score` (surface quality
preserved under `metadata.quality_score`, relevance under `metadata.relevance`).
Leadgen and research results are reordered by the composite; SEO is annotated
without reordering (it is an analysis surface, not retrieval).

**Semantic seam (SEARCH-RANKING-EMBEDDINGS-1, wired 2026-06-28):** relevance is
pluggable. `rank_items` takes a `relevance_fn` and defaults to
`default_relevance_provider()` — lexical unless `AINDY_SEARCH_EMBEDDING_RANKING`
opts into the hybrid `EmbeddingRelevanceProvider`, which scores cosine similarity
over the runtime embedding stack (`AINDY.memory.embedding_service`) and falls back
to lexical automatically when the backend is unavailable. App-profile/CI runs stay
lexical and deterministic (testing-mode embeddings return zero vectors → fallback).
**Tests:** `tests/unit/test_search_ranking.py`.

---

### Phase v4 — Feedback & Memory Loop

**Goal:** Closed-loop search system

**Actions:**

* persist outcomes to Memory Bridge — DONE
* feed results into future query weighting — DONE (flag-gated)

**Result-feedback capture (2026-07-17):** `SearchResultFeedback` + `feedback_service`
record whether a result actually *worked* — both implicit (`click` / `dwell` /
`convert` / `dismiss`) and explicit (`thumbs_up` / `thumbs_down`), since not every
user thumbs. Signals are deduped per `(user, query, result_ref, signal)`; an explicit
vote clears the opposing thumbs (latest opinion wins). `get_result_outcome_weights`
sums per `result_ref` into a blended per-query weight. Captured via
`POST /apps/search/feedback` + `GET /apps/search/feedback/weights` and the
`sys.v1.search.record_feedback` syscall.

**Outcome→query weighting (2026-07-17, opt-in):** when
`AINDY_SEARCH_OUTCOME_WEIGHTING` is enabled, `sys.v1.search.query` looks up the
per-query outcome weights and passes them into `rank_items`, which nudges each
result's composite by a small, bounded amount (`outcome_nudge`, `tanh`-saturated at
±0.15) toward results the user acted on and away from ones they dismissed. Relevance
+ quality stays the dominant axis; the applied `outcome_weight` / `outcome_nudge` are
recorded on each item's `metadata`. Default off → ranking is byte-for-byte unchanged.
**Tests:** `tests/unit/test_search_result_feedback.py`, `tests/unit/test_search_ranking.py`.

---

### Phase v5 — UI + Dashboard Integration - DONE

**Goal:** Operational surface

**Actions:**

* integrate SEO + LeadGen UI into client - DONE
* add result history views - DONE

The Research, SEO, and LeadGen surfaces are now routed (`/search/research`,
`/search/seo`, `/search/leadgen`) and reachable from the sidebar + app-shell nav
(the SEO tool was previously built but orphaned, and the sidebar links pointed at
dead `/research`, `/seo`, `/leadgen` paths). A shared `client/src/components/app/SearchResults.jsx`
renders the unified ranked `results[]` with per-item rank/relevance score badges
and an overall `search_score`; Research surfaces ranked sources and SEO/Research/
LeadGen each show a `SearchHistory` result-history view.
**Tests:** `client/src/test/search-nav.test.jsx`, `client/src/test/search-results.test.jsx`.

---

## 8. Technical Debt

### Structural

* ✅ a unified query-processing layer now exists (`apps/search/services/search_service.py`)
  — the previously-disconnected SEO/LeadGen/Research modules share it, the
  `SearchResponse` contract, ranking, the `search.query` tool, and the
  `unified_search` workflow

### Functional

* ✅ leadgen search now uses real retrieval (orchestrator + provider)
* ✅ research search executes via `/research/query`
* ✅ ranking unified: shared lexical relevance + composite score order results across surfaces
* ✅ SEO improvement suggestions shipped (§3.1) — `seo_improvement_suggestions`
* ✅ Phase v4: outcomes are captured (`SearchResultFeedback`) and, behind
  `AINDY_SEARCH_OUTCOME_WEIGHTING`, re-weight future query ranking via `outcome_nudge`

### Conceptual

* ✅ semantic recall is now integrated into the leadgen/research flows (was previously
  a separate, unintegrated system)

---

## 9. Phase Mapping

| Phase | Component            | Status      | Required Action |
| ----- | -------------------- | ----------- | --------------- |
| v1    | Surface Alignment    | Partial     | Normalize       |
| v2    | Retrieval Integration| Complete    | Maintenance only |
| v3    | Ranking Unification  | Complete    | Maintenance only |
| v4    | Feedback Loop        | Complete (opt-in) | Flag-gated; soak then flip default |
| v5    | UI Integration       | Complete    | Maintenance only |

---

## 10. Next Steps

### Step 1 - Create a unified search service - DONE
**Files:** `apps/search/services/search_service.py`  
**Outcome:** external, internal, semantic, and hybrid search requests route through one reusable interface — `search_service.py` is the shipped single entry point backing every surface (dispatched via `sys.v1.search.query`, Steps 5–6).

### Step 2 - Standardize search request and result schemas - DONE
**Files:** `apps/search/schemas/search_schema.py`, `apps/search/schemas/__init__.py`, `apps/search/services/search_service.py`, `apps/search/routes/leadgen_router.py`, `apps/search/flows/search_flows.py`  
**Outcome:** A shared `SearchRequest` / `SearchResultItem` / `SearchResponse` contract plus per-surface adapters (`leadgen_to_search_response`, `research_to_search_response`, `seo_to_search_response`, dispatcher `to_search_response`) now normalize every surface into one ranked shape. Leadgen and research emit compatible `results` items (`title`, `url`, `snippet`, `score`, `metadata`) and consistent top-level fields (`query`, `search_type`, `search_score`, `memory`, `learning_context`, `history_id`).

**Backward compatibility:** changes are additive — leadgen rows keep `company` / `reasoning` / `overall_score` (consumed by `client/src/components/app/LeadGen.jsx`); the shared keys are added alongside them. Research, which previously returned no result list, now also returns a normalized `results` array.

**Tests:** `tests/unit/test_search_schema_contract.py` (`-m app_profile`).

### Step 3 - Move hybrid retrieval into the shared search layer - DONE
**Files:** `apps/search/services/leadgen_service.py`, `apps/search/routes/research_results_router.py`, `apps/search/services/search_service.py`  
**Outcome:** memory recall plus external retrieval is implemented once in `search_service` and reused across search surfaces (`build_learning_context`/`attach_learning_context` thread recall through the shared layer).

### Step 4 - Add shared search history and reuse - DONE
**Files:** `apps/search/models/search_history.py`, `apps/search/models/leadgen_model.py`, `apps/search/models/research_results.py`, `apps/search/services/research_results_service.py`, `apps/search/services/search_service.py`  
**Outcome:** search outcomes are persisted to a shared `SearchHistory` model and reusable across the system (`get_search_history` / `get_search_history_item` / `delete_search_history_item` in `search_service`), instead of staying siloed by feature. **Phase v4 (2026-07-17):** result outcomes are now also captured explicitly (`SearchResultFeedback`) and, behind `AINDY_SEARCH_OUTCOME_WEIGHTING`, re-weight future query ranking (`get_result_outcome_weights` → `rank_items`).

### Step 5 - Integrate unified search into agent tools - DONE
**Files:** `apps/search/agents/tools.py`, `apps/search/agents/capabilities.py`, `apps/search/syscalls.py`
(runtime registration surfaces are consumed, not owned: `AINDY.agents.tool_registry`, `AINDY.kernel.syscall_registry`)
**Outcome:** A single `search.query` agent tool now backs all surfaces. It dispatches the new `sys.v1.search.query` syscall, which routes by `search_type` (`research` | `leadgen` | `seo_analysis` | `memory`) through `search_service` and returns the normalized `SearchResponse` (Step 2 contract). The legacy `leadgen.search` / `research.query` tools remain for backward compatibility.

**Tests:** `tests/unit/test_search_unified_tool_and_flow.py`.

### Step 6 - Expose unified search to workflow execution - DONE
**Files:** `apps/automation/flows/flow_definitions.py`, `apps/search/bootstrap.py`
(runtime execution surface consumed, not owned: `AINDY.runtime.flow_engine`)
**Outcome:** The `unified_search` workflow (`search_validate` → `search_query_execute`) dispatches `sys.v1.search.query` and surfaces the ranked `SearchResponse` under the `search_result` state key. Search is now a reusable workflow capability rather than a research-only utility. The flow is registered by reference (string syscall dispatch), so no new cross-app import dependency is introduced.

**Tests:** `tests/unit/test_search_unified_tool_and_flow.py`.

---

## 11. Governance Notes

* This document is the **canonical reference** for Search System architecture.
* Any changes must align with:

  * documented lifecycle
  * retrieval integrity
  * Memory Bridge integration rules

* Deviations must be recorded in:

  * `TECH_DEBT.md`
  * `docs/architecture/EVOLUTION_PLAN.md`

---

## 12. Summary (Operational Truth)

The Search System is not complete when it stores results.

It is complete when:

> Queries trigger real retrieval, results are ranked and persisted, and outcomes feed back into future search behavior.
