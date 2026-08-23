---
title: "Formula and Algorithm Overview"
last_verified: "2026-08-22"
api_version: "1.0"
status: current
owner: "app-team"
---

﻿---
title: "Formula and Algorithm Overview"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# Formula and Algorithm Overview

This document extracts and documents computational formulas and algorithmic processes strictly from the current implementation. Verified against code 2026-07-05.

> **Scope note.** Business-logic formulas are **app-owned** (`apps/*`) and verified against
> this repo. The remaining `AINDY/*` references are **runtime-owned primitives**
> (`aindy-runtime`), consumed as a published dependency — verified against the sibling
> `aindy-runtime` checkout (2026-07-05): the memory-bridge primitives
> (`AINDY/memory/memory_persistence.py`, `AINDY/memory/bridge.py`,
> `AINDY/memory/memory_capture_engine.py`), `AINDY/routes/health_router.py`, and
> `AINDY/main.py` all exist there. The ARM/DeepSeek analysis logic moved *out* of the
> runtime into the app layer (`apps/arm/services/deepseek/`); the old
> `AINDY/services/deepseek_arm_service.py` resolves to no file in either repo (see
> `TECH_DEBT.md` DOCS-MIGRATION-1).

## 1. Explicit Mathematical Formulas

### Calculation Services (`apps/analytics/services/calculations/calculation_services.py`)
- `calculate_twr(task)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - LHI = time_spent × task_complexity × skill_level
  - TWR = (LHI × ai_utilization × time_spent) / task_difficulty
  - Notes: `time_spent` appears twice in the final TWR formula.

- `calculate_effort(task)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Effort = (time_spent × task_complexity) / (skill_level + ai_utilization + 1)

- `calculate_productivity(task)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Productivity = (ai_utilization × skill_level) / (time_spent + 1)

- `calculate_virality(share_rate, engagement_rate, conversion_rate, time_factor)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Virality = (share_rate × engagement_rate × conversion_rate) / (time_factor + 1)

- `calculate_engagement_score(data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - If total_views == 0 ? 0
  - Score = ((likes × 2) + (shares × 3) + (comments × 1.5) + (clicks × 1) + (time_on_page × 0.5)) / total_views
  - Returned as `round(score, 2)`

- `calculate_ai_efficiency(data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - If total_tasks == 0 ? 0
  - Score = (ai_contributions / (human_contributions + 1)) × (total_tasks / 10)
  - Returned as `round(score, 2)`

- `calculate_impact_score(data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - If reach == 0 ? 0
  - Score = (engagement / reach) × 100 + (conversion × 2)
  - Returned as `round(score, 2)`

- `income_efficiency(eff)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Income efficiency = (focused_effort × ai_utilization) / (time + capital)

- `revenue_scaling(rs)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Revenue scaling = ((ai_leverage + content_distribution) / time) × audience_engagement

- `execution_speed(es)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Execution speed = (ai_automations + systemized_workflows) / decision_lag

- `attention_value(input_data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Attention value = (content_output × platform_presence) / time

- `engagement_rate(input_data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Engagement rate = total_interactions / total_views

- `business_growth(input_data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Business growth = (revenue - expenses) / scaling_friction

- `monetization_efficiency(input_data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Monetization efficiency = total_revenue / audience_size

- `ai_productivity_boost(input_data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - AI productivity boost = (tasks_with_ai - tasks_without_ai) / time_saved

- `lost_potential(input_data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Lost potential = (missed_opportunities × time_delayed) - gains_from_action

- `decision_efficiency(input_data)`
  - Reference: `apps/analytics/services/calculations/calculation_services.py`
  - Decision efficiency = automated_decisions / (manual_decisions + processing_time)

### Projection Service (`apps/masterplan/services/projection_service.py`)
- `project_completion(masterplan, twr_values)`
  - Reference: `apps/masterplan/services/projection_service.py`
  - If `twr_values` is empty ? return `None`
  - `conservative` = percentile(TWR, 30)
  - `aggressive` = percentile(TWR, 70)
  - `optimal` = max(TWR)
  - `remaining_days` = (target_date - today).days
  - `effective_rate` = rate / COMPRESSION_DIVISOR (COMPRESSION_DIVISOR = 100)
  - `adjusted_days` = remaining_days / effective_rate
  - `projected_eta` = today + adjusted_days (days)
  - If `rate <= 0` or `effective_rate <= 0`, return `target_date`.
  - Returns dict with `conservative_eta`, `aggressive_eta`, `optimal_eta`.

- `evaluate_phase(plan)`
  - Reference: `apps/masterplan/services/projection_service.py`
  - `phase_end` = start_date + (duration_years × 365 days)
  - `thresholds_met` = all of:
    - total_wcu >= wcu_target
    - gross_revenue >= revenue_target
    - books_published >= books_required
    - (platform_required is False) OR platform_live
    - (studio_required is False) OR studio_ready
    - active_playbooks >= playbooks_required
  - Returns 2 if thresholds_met OR now >= phase_end; else returns 1.

### SEO Routes (`apps/search/routes/seo_routes.py`)
- `analyze_seo` (`POST /seo/analyze`) and `analyze_seo_compat` (`POST /seo/analyze_seo/`)
  - Reference: `apps/search/routes/seo_routes.py`
  - Both handlers **delegate** to `analyze_seo_content` → `seo_analysis` (§SEO Services below); they differ only in input schema and default `top_n`. There is no inline readability heuristic — readability comes from `textstat.flesch_reading_ease`.
  - Returns whatever `seo_analysis` produces: `{word_count, readability, top_keywords, keyword_densities}`.
  - _(Corrected 2026-07-05: the previously-documented inline `readability = 100 - (len(words)/200 × 10)` block no longer exists.)_

### SEO Services (`apps/search/services/seo_services.py`)
- `keyword_density(text, keyword)`
  - Reference: `apps/search/services/seo_services.py`
  - `words = nltk.word_tokenize(text.lower())`
  - `keyword_norm = keyword.lower()`
  - `density = round((count(words, keyword_norm) / len(words)) × 100, 2)`
- `seo_analysis(text, top_n)`
  - Reference: `apps/search/services/seo_services.py`
  - keywords = extract_keywords(text, top_n)  # list of (keyword, count); preprocessing and filtering occur inside extract_keywords()
  - word_count = len(nltk.word_tokenize(text))
  - readability = textstat.flesch_reading_ease(text)
  - densities = {kw[0]: keyword_density(text, kw[0]) for kw in keywords}
  - Returns:
    - `top_keywords = [kw[0] for kw in keywords]`
    - `keyword_densities = densities`
  - Full return dict: `{word_count, readability, top_keywords, keyword_densities}`
 - `extract_keywords(text, top_n)`
   - Reference: `apps/search/services/seo_services.py`
   - tokens = nltk.word_tokenize(text.lower()) filtered to `.isalnum()`
   - returns `Counter(words).most_common(top_n)`

### Analytics Rate Calculator (`apps/social/services/rate_calculator.py`)
- Rates are calculated with division-by-zero guards:
  - Reference: `apps/social/services/rate_calculator.py`
  - interaction_rate = interaction_volume / passive_visibility (if visibility else 0)
  - attention_rate = deep_attention_units / passive_visibility (if visibility else 0)
  - intent_rate = intent_signals / unique_reach (if reach else 0)
  - conversion_rate = conversion_events / intent_signals (if intent else 0)
  - discovery_ratio = active_discovery / passive_visibility (if visibility else 0)
  - growth_rate = growth_velocity / unique_reach (if reach else 0)

### Analytics Adapter (`apps/social/services/linkedin_adapter.py`)
- interaction_volume = likes + comments + shares
- intent_signals = profile_views + link_clicks
- canonical_data updated with rates from `calculate_rates`.
  - Reference: `apps/social/services/linkedin_adapter.py`

### Freelance Metrics (`apps/freelance/services/freelance_service.py`)
- `update_revenue_metrics`:
  - total_revenue = sum(price) for delivered orders
  - Also computes `avg_execution_time`, `income_efficiency`, `ai_productivity_boost`, and `avg_delivery_quality` via `_average(...)` (not `None`).
  - Adds + commits the `RevenueMetrics` row (does not return it).
  - _(Corrected 2026-07-05: earlier text claimed the non-revenue fields were `None`.)_

### Task Services (`apps/tasks/services/task_service.py`)
- `complete_task`:
  - Reference: `apps/tasks/services/task_service.py`
  - If started, `time_spent += (now - start_time).total_seconds()`
  - Sets `status = "completed"`, `end_time = now`, unlocks downstream tasks, emits `TASK_COMPLETED`.
  - Persists a `save_calculation`-via-syscall of **raw seconds** under `"Task Time Spent (seconds)"` — it does **not** divide by 3600 and does **not** compute TWR here.
  - _(Corrected 2026-07-05: earlier text claimed a `/3600` hours conversion, an inline TWR computation, and a `twr_score += (twr_score × 0.1)` Mongo increment — none of those exist.)_
- `orchestrate_task_completion` (the completion side-effects, separated from `complete_task`):
  - Updates MongoDB `metrics_snapshot`: `$inc execution_velocity: 1` and `$set infinity_score` / `execution_speed_score` (no `twr_score` field).
  - Also drives memory capture, MasterPlan ETA reprojection, and Infinity scoring.
  - _(Note: `complete_task` has no already-completed guard — tracked in `TECH_DEBT.md` → TASK-COMPLETE-IDEMPOTENCY-1.)_

### RippleTrace Services (`apps/rippletrace/services/rippletrace_services.py`)
- `log_ripple_event`:
  - Generates `id` if absent: `ripple-{timestamp}`

### Health Check (`AINDY/routes/health_router.py`)
- Measures endpoint latency:
  - `elapsed_ms = round((time.time() - start) * 1000, 2)`
  - Reference: `AINDY/routes/health_router.py`
- `avg_latency_ms = statistics.mean(latencies)`
  - Reference: `AINDY/routes/health_router.py`
- `status = "healthy"` if no component errors and all endpoints ok; else `"degraded"`.

## 2. Aggregation Logic

### Batch Processing (`apps/analytics/services/calculations/calculations.py`)
- For each list field in `BatchInput`, computes list of metric values using corresponding function:
  - e.g., `results["AI Productivity Boost"] = [ai_productivity_boost(x) for x in batch_data.ai_productivity_boost]`
- Returns a dict keyed by metric name with list values.

### Analytics Summary (`apps/analytics/routes/analytics_router.py`)
- Early return:
  - If no telemetry records exist: `return {"message": "No telemetry records found."}`
- For `group_by == "period"`:
  - Reference: `apps/analytics/routes/analytics_router.py`
  - Sums per-period totals for each metric.
  - Recomputes rates using per-period totals with `or 1` guards for denominators.
  - Rates calculation block reference: `apps/analytics/routes/analytics_router.py`
- For global summary:
  - Totals are sums across all records.
  - Rates recomputed using totals with `or 1` guards.
  - Rates calculation block reference: `apps/analytics/routes/analytics_router.py`

### Research Results (`apps/search/services/research_results_service.py`)
- Maintains a singleton runtime trace `_memory_trace` and appends nodes to it.

## 3. Decision Algorithms

### Masterplan Activation (`apps/masterplan/routes/genesis_router.py`)
Pseudocode:
```
if plan_id not found:
  raise 404
set all MasterPlan.is_active = False
set selected plan.is_active = True
set activated_at = now
commit
```

### Genesis Locking (`apps/masterplan/services/masterplan_factory.py`)
Pseudocode:
```
if session not found: error
if session.status == "locked": error
if no existing plans:
  version_label = "V1", is_origin = True, parent_id = None
else:
  version_label = "V{count+1}", is_origin = False, parent_id = last_plan.id
horizon = draft.time_horizon_years (default 5)
start_date = now
target_date = start_date + horizon*365 days
posture = determine_posture(draft)
create MasterPlan(...)
session.status = "locked"
commit
```

### Task State Transitions (`apps/tasks/services/task_service.py`)
Pseudocode:
```
start_task(name):
  if task not found -> return message
  if start_time not set:
    set start_time = now
    status = "in_progress"
  else:
    return already started message

pause_task(name):
  if task not found -> return message
  if status == "in_progress":
    time_spent += (now - start_time).total_seconds()
    status = "paused"
  else:
    return not in progress message

complete_task(name):
  if task not found -> return message
  if start_time set:
    time_spent += (now - start_time).total_seconds()
  status = "completed"          # no already-completed guard (TASK-COMPLETE-IDEMPOTENCY-1)
  end_time = now
  unlock downstream tasks; emit TASK_COMPLETED
  save_calculation("Task Time Spent (seconds)", time_spent)   # raw seconds, not TWR
  # completion side-effects (memory, Mongo velocity, ETA, Infinity) run in
  # orchestrate_task_completion, not here
```

### Memory Bridge Permission Validation (`apps/bridge/routes/bridge_router.py`)
Pseudocode:
```
expected = JWT(authenticated request)
if expected != signature: 403
if ts + ttl < now: 403
```
Reference: `apps/bridge/routes/bridge_router.py`

### Social Feed Scoring (`apps/social/routes/social_router.py`)
Pseudocode:
```
relevance = 1.0
if trust_tier_required == INNER_CIRCLE:
  relevance = 2.0
```

## 4. External Model Processing Logic

### Genesis LLM (`apps/masterplan/services/genesis_ai.py`)
- Sends system and user messages to OpenAI chat completions.
- Parses `response.choices[0].message.content` as JSON.
- Fallback: returns static dict if JSON parsing fails.
- Reference: `apps/masterplan/services/genesis_ai.py` (call), `apps/masterplan/services/genesis_ai.py` (json.loads).

### LeadGen Scoring (`apps/search/services/leadgen_service.py`)
- Calls OpenAI chat completions with system prompt.
- Attempts to parse JSON; if output not JSON, extracts substring with regex.
- Fallback: returns scores of 0 on exception.
- Reference: `apps/search/services/leadgen_service.py` (score_lead), `apps/search/services/leadgen_service.py` (regex extraction), `apps/search/services/leadgen_service.py` (json.loads).

### ARM / DeepSeek (`apps/arm/services/deepseek/deepseek_code_analyzer.py`)
- **App-owned.** The ARM analysis/generation business logic moved from the pre-split
  runtime `AINDY/services/deepseek_arm_service.py` (which no longer exists in either repo)
  into the app layer at `apps/arm/services/deepseek/` (`deepseek_code_analyzer.py`,
  `config_manager_deepseek.py`, `file_processor_deepseek.py`, `security_deepseek.py`).
- Validates file path; runs `run_analysis` / `generate_code` synchronously; persists
  `ARMRun` / `ARMLog` and a Memory Bridge node.
- _(Corrected 2026-07-05: repointed from the dead runtime path. The earlier "truncate DB
  summaries to 1000 / 250 chars" detail is unverified in the new location — treat as historical
  until re-checked against `deepseek_code_analyzer.py`.)_

## 5. Memory Bridge Algorithms

### Node Creation (`AINDY/memory/memory_persistence.py`)
- Creates a `MemoryNodeModel` with:
  - id: provided or generated UUID
  - content: string coercion
  - tags: list coercion
  - node_type: default "generic"
  - extra: dict
- Persists and returns the DB row.

### Link Creation (`AINDY/memory/memory_persistence.py`)
Pseudocode:
```
if source_id == target_id: error
if source_id or target_id not in memory_nodes: error
create MemoryLinkModel(source_id, target_id, link_type)
commit
```

### Tag Filtering (`AINDY/memory/memory_persistence.py`)
- `find_by_tags(tags, mode)`:
  - If mode == "OR": OR of `tags.contains([t])`
  - Else: AND by successive `tags.contains([t])`

### Relationship Traversal (`AINDY/memory/bridge.py`)
- `find_by_tag` recursively traverses `MemoryNode.children` tree and collects nodes with tag.

## 6. Background Task Algorithms

### Reminders (`apps/tasks/services/task_service.py`)
Pseudocode:
```
loop forever:
  now = datetime.now()
  for task in tasks:
    if reminder_time and now >= reminder_time and status != completed:
      print reminder
      reminder_time = None
      commit
  sleep 60s
```

### Recurrence (`apps/tasks/services/task_service.py`)
Pseudocode:
```
loop forever:
  tasks = tasks where status == completed
  (no recurrence logic implemented)
  sleep 60s
```

### Startup Thread Stubs (`AINDY/main.py`)
- Startup event defines local `handle_recurrence` and `check_reminders` that only log and do not loop.

## 7. Data Transformation Pipelines

### LinkedIn Analytics (`apps/social/services/linkedin_adapter.py`) — PARKED, non-functional
- Input: `LinkedInRawInput`
- Transform: compute interaction_volume and intent_signals; compute rates via `calculate_rates`
- Output: canonical dict persisted to `CanonicalMetricDB` (`apps/analytics/routes/analytics_router.py`)
- **Status:** this pipeline has never produced a row. The adapter does attribute access
  (`raw.likes`) but the ingest node dispatches `data.model_dump()` across a syscall boundary, so
  it receives a dict → `AttributeError` → HTTP 500. Its UI was removed in walk-log item 18; the
  routes remain registered but unused, and nothing consumes `CanonicalMetricDB`. Fix the
  dict/object mismatch before relying on any of it.

### Research Results (`apps/search/services/research_results_service.py`)
- Input: `ResearchResultCreate`
- Persist: `ResearchResult` ORM record
- Side effect: create `MemoryNode` in runtime trace and persist via `create_memory_node`

### SEO Analysis (`apps/search/routes/seo_routes.py`, `apps/search/services/seo_services.py`)
- Input: raw content or SEOInput
- Transform: compute word counts, readability, keyword densities
- Persist: `save_calculation` called for readability and word count (and avg density)

### LeadGen (`apps/search/services/leadgen_service.py`)
- Input: query string
- Transform: run AI search (mocked), score leads via OpenAI
- Persist: `LeadGenResult` ORM entries
- Side effect: `create_memory_node` per lead

### ARM/DeepSeek (`apps/arm/services/deepseek/deepseek_code_analyzer.py`)
- Input: file_path (+ optional instructions)
- Transform: analyze/generate; track duration
- Persist: `ARMRun` and `ARMLog` entries; Memory Bridge node
- _(App-owned since the split; was `AINDY/services/deepseek_arm_service.py`.)_

## 8. Known Algorithmic Gaps
- Magic numbers:
  - `COMPRESSION_DIVISOR = 100` in `apps/masterplan/services/projection_service.py`.
  - Multiple fixed multipliers in `calculate_engagement_score` and `calculate_impact_score`.
- Division-by-zero safeguards are inconsistent:
  - Some functions guard (e.g., `calculate_engagement_score`, `calculate_ai_efficiency`, `calculate_impact_score`), others do not (e.g., `execution_speed`, `engagement_rate`, `attention_value`).
- _Resolved (verified 2026-07-05):_ `generate_meta_description` in `apps/search/services/seo_services.py` is now defined **once** (the duplicate was removed).
- _Resolved (verified 2026-07-05):_ `apps/search/services/leadgen_service.py::score_lead` no longer contains duplicated/dead scoring logic — a single try/except with one `return` and a zero-score exception fallback.
- _Corrected (2026-07-05):_ `apps/search/routes/seo_routes.py` has two route handlers — `analyze_seo` (`POST /seo/analyze`) and `analyze_seo_compat` (`POST /seo/analyze_seo/`) — but they are **not** divergent inline implementations; both delegate to the same `analyze_seo_content` → `seo_analysis` service.
- In `AINDY/memory/bridge.py`, `create_memory_node` is reported to persist to `CalculationResult` with placeholder values — **runtime-owned (`aindy-runtime`), not verifiable from this repo.**


