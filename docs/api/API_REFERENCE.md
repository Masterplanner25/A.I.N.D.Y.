---
title: "App HTTP REST API Reference"
last_verified: "2026-08-02"
api_version: "1.0"
status: current
owner: "apps-team"
---
# API Reference

> **Related:** [`API_CONTRACTS.md`](./API_CONTRACTS.md) is the
> repo's router-file → URL inventory and mount/ownership map (runtime + app routes),
> validated by `scripts/check_api_contracts.py`. This reference documents the
> app-owned endpoint request/response shapes, and its `/apps/*` coverage is guarded
> by `scripts/check_api_reference.py`.

## HTTP API Reference

### ARM — Autonomous Reasoning

#### POST /apps/arm/analyze
Analyze Code

**Body:** complexity: number | null, context: string | null, file_path: string (required), urgency: number | null

**Response 200:** unspecified

#### GET /apps/arm/config
Get Config

**Response 200:** unspecified

#### PUT /apps/arm/config
Update Config

**Body:** updates: map[unspecified] (required)

**Response 200:** unspecified

#### GET /apps/arm/config/suggest
Get Config Suggestions

**Parameters:** window (query): integer

**Response 200:** unspecified

#### POST /apps/arm/config/auto-tune
Auto Tune Config — apply (or, by default, preview) the low-risk config changes ARM's
suggestion engine already computed, behind a safety gate (whitelist, bounds,
min-sessions, cooldown, max-per-run). Dry run unless `apply=true`; every applied run
is auditable and revertible.

**Parameters:** apply (query): boolean (default false), window (query): integer

**Response 200:** unspecified

#### POST /apps/arm/config/auto-tune/revert
Revert Auto Tune — restore the config snapshot captured before a specific auto-tune run.

**Body:** log_id: string (required)

**Response 200:** unspecified

#### GET /apps/arm/config/auto-tune/history
Auto Tune History — list this user's auto-tune runs (applied changes, snapshots, revert state).

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### POST /apps/arm/generate
Generate Code

**Body:** analysis_id: string | null, complexity: number | null, generation_type: string | null, language: string | null, original_code: string | null, prompt: string (required), urgency: number | null

**Response 200:** unspecified

#### GET /apps/arm/logs
Get Arm Logs

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### GET /apps/arm/metrics
Get Arm Metrics

**Parameters:** window (query): integer

**Response 200:** unspecified

### Agent

#### GET /apps/agent/next-action/outcomes
Get Next Action Outcomes — recent Next-Action dispatch outcomes (FR-3): what the runtime
did with each chosen `trigger_execution` (disposition, follow-up run, reason), the
CHOSEN→DISPATCHED chain, and a per-disposition summary. Read-only observability for
soaking autonomous acting (`AINDY_NEXT_ACTION_ACTING`) before flipping it on.

**Parameters:** trace_id (query): string | null, limit (query): integer

**Response 200:** unspecified

#### POST /apps/agent/run
Create Agent Run

**Body:** goal: string (required)

**Response 200:** unspecified

#### GET /apps/agent/runs
List Agent Runs

**Parameters:** status (query): string | null, limit (query): integer

**Response 200:** unspecified

#### GET /apps/agent/runs/{run_id}
Get Agent Run

**Parameters:** run_id (path): string

**Response 200:** unspecified

#### POST /apps/agent/runs/{run_id}/approve
Approve Agent Run

**Parameters:** run_id (path): string

**Response 200:** unspecified

#### GET /apps/agent/runs/{run_id}/events
Get Run Events

**Parameters:** run_id (path): string

**Response 200:** unspecified

#### POST /apps/agent/runs/{run_id}/recover
Recover Agent Run

**Parameters:** run_id (path): string, force (query): boolean

**Response 200:** unspecified

#### POST /apps/agent/runs/{run_id}/reject
Reject Agent Run

**Parameters:** run_id (path): string

**Response 200:** unspecified

#### POST /apps/agent/runs/{run_id}/replay
Replay Agent Run

**Parameters:** run_id (path): string

**Response 200:** unspecified

#### POST /apps/agent/runs/{run_id}/resume
Resume Agent Run

**Parameters:** run_id (path): string

**Response 200:** unspecified

#### GET /apps/agent/runs/{run_id}/steps
Get Run Steps

**Parameters:** run_id (path): string

**Response 200:** unspecified

#### GET /apps/agent/suggestions
Get Tool Suggestions

**Response 200:** unspecified

#### GET /apps/agent/tools
List Tools

**Response 200:** unspecified

#### GET /apps/agent/trust
Get Trust Settings

**Response 200:** unspecified

#### PUT /apps/agent/trust
Update Trust Settings

**Body:** allowed_auto_grant_tools: array[string] | null, auto_execute_low: boolean | null, auto_execute_medium: boolean | null

**Response 200:** unspecified

### Authorship

#### POST /apps/authorship/reclaim
Reclaim Authorship Endpoint

**Parameters:** content (query): string, author (query): string, motto (query): string

**Response 200:** unspecified

### Automation

#### GET /apps/automation/logs
Get Automation Logs

**Parameters:** status (query): string | null, source (query): string | null, limit (query): integer

**Response 200:** unspecified

#### GET /apps/automation/logs/{log_id}
Get Automation Log

**Parameters:** log_id (path): string

**Response 200:** unspecified

#### POST /apps/automation/logs/{log_id}/replay
Replay Automation Log

**Parameters:** log_id (path): string

**Response 200:** unspecified

#### GET /apps/automation/scheduler/status
Get Scheduler Status

**Response 200:** unspecified

#### POST /apps/automation/tasks/{task_id}/trigger
Trigger Task Automation

**Parameters:** task_id (path): integer

**Body:** automation_config: map[unspecified] | null, automation_type: string | null

**Response 200:** unspecified

### Autonomy

#### GET /apps/autonomy/decisions
Get Recent Autonomy Decisions

**Parameters:** limit (query): integer

**Response 200:** unspecified


### Compute

#### POST /apps/compute/ai_productivity_boost
Process Ai Productivity Boost

**Body:** tasks_with_ai: number (required), tasks_without_ai: number (required), time_saved: number (required)

**Response 200:** unspecified

#### POST /apps/compute/attention_value
Process Attention Value

**Body:** content_output: number (required), platform_presence: number (required), time: number (required)

**Response 200:** unspecified

#### POST /apps/compute/batch_calculations
Process Batch Calculations

**Body:** ai_efficiencies: array[object], ai_productivity_boost: array[object], attention_values: array[object], business_growths: array[object], decision_efficiency: array[object], efficiencies: array[object], engagement_rates: array[object], engagements: array[object], execution_speeds: array[object], impacts: array[object], lost_potential: array[object], monetization_efficiencies: array[object], revenue_scalings: array[object], tasks: array[object]

**Response 200:** unspecified

#### POST /apps/compute/business_growth
Process Business Growth

**Body:** expenses: number (required), revenue: number (required), scaling_friction: number (required)

**Response 200:** unspecified

#### POST /apps/compute/calculate_ai_efficiency
Process Ai Efficiency

**Body:** ai_contributions: integer (required), human_contributions: integer (required), total_tasks: integer (required)

**Response 200:** unspecified

#### POST /apps/compute/calculate_effort
Process Effort

**Body:** ai_utilization: integer (required), skill_level: integer (required), task_complexity: integer (required), task_difficulty: integer (required), task_name: string (required), time_spent: number (required)

**Response 200:** unspecified

#### POST /apps/compute/calculate_engagement
Process Engagement

**Body:** clicks: integer (required), comments: integer (required), likes: integer (required), shares: integer (required), time_on_page: number (required), total_views: integer (required)

**Response 200:** unspecified

#### POST /apps/compute/calculate_impact_score
Process Impact Score

**Body:** conversion: integer (required), engagement: integer (required), reach: integer (required)

**Response 200:** unspecified

#### POST /apps/compute/calculate_productivity
Process Productivity

**Body:** ai_utilization: integer (required), skill_level: integer (required), task_complexity: integer (required), task_difficulty: integer (required), task_name: string (required), time_spent: number (required)

**Response 200:** unspecified

#### POST /apps/compute/calculate_twr
Process Task

**Body:** ai_utilization: integer (required), skill_level: integer (required), task_complexity: integer (required), task_difficulty: integer (required), task_name: string (required), time_spent: number (required)

**Response 200:** unspecified

#### POST /apps/compute/calculate_virality
Process Virality

**Body:** conversion_rate: number (required), engagement_rate: number (required), share_rate: number (required), time_factor: number (required)

**Response 200:** unspecified

#### POST /apps/compute/create_masterplan
Create Masterplan

**Body:** books_required: integer (required), duration_years: integer (required), name: string | null, platform_required: boolean (required), playbooks_required: integer (required), revenue_target: number (required), start_date: string (required), studio_required: boolean (required), wcu_target: number (required)

**Response 200:** unspecified

#### POST /apps/compute/decision_efficiency
Process Decision Efficiency

**Body:** automated_decisions: number (required), manual_decisions: number (required), processing_time: number (required)

**Response 200:** unspecified

#### POST /apps/compute/engagement_rate
Process Engagement Rate

**Body:** total_interactions: number (required), total_views: number (required)

**Response 200:** unspecified

#### POST /apps/compute/execution_speed
Process Execution Speed

**Body:** ai_automations: number (required), decision_lag: number (required), systemized_workflows: number (required)

**Response 200:** unspecified

#### POST /apps/compute/income_efficiency
Process Income Efficiency

**Body:** ai_utilization: number (required), capital: number (required), focused_effort: number (required), time: number (required)

**Response 200:** unspecified

#### POST /apps/compute/lost_potential
Process Lost Potential

**Body:** gains_from_action: number (required), missed_opportunities: number (required), time_delayed: number (required)

**Response 200:** unspecified

#### GET /apps/compute/masterplans
Get Masterplans

**Response 200:** unspecified

#### POST /apps/compute/monetization_efficiency
Process Monetization Efficiency

**Body:** audience_size: number (required), total_revenue: number (required)

**Response 200:** unspecified

#### GET /apps/compute/results
Get Results

**Response 200:** unspecified

#### POST /apps/compute/revenue_scaling
Process Revenue Scaling

**Body:** ai_leverage: number (required), audience_engagement: number (required), content_distribution: number (required), time: number (required)

**Response 200:** unspecified

### Coordination

#### GET /apps/coordination/agents
Get Agents

**Response 200:** unspecified

#### POST /apps/coordination/agents/register
Register Agent

**Body:** agent_id: string (required), capabilities: array[string], current_state: map[unspecified], health_status: string, load: number

**Response 200:** unspecified

#### GET /apps/coordination/agents/status
Get Agents Status

**Response 200:** unspecified

#### DELETE /apps/coordination/agents/{agent_id}
Deregister Agent

**Parameters:** agent_id (path): string

**Response 200:** unspecified

#### POST /apps/coordination/agents/{agent_id}/heartbeat
Heartbeat Agent

**Parameters:** agent_id (path): string

**Body:** object | null

**Response 200:** unspecified

#### POST /apps/coordination/conflict/memory
Detect Memory Conflict Route

**Body:** agent_id: string | null, memory_path: string (required)

**Response 200:** unspecified

#### POST /apps/coordination/conflict/run
Detect Run Conflict Route

**Body:** agent_id: string | null, objective: string (required)

**Response 200:** unspecified

#### GET /apps/coordination/graph
Get Coordination Graph

**Response 200:** unspecified

#### GET /apps/coordination/memory/shared
Get Shared Memory

**Parameters:** limit (query): integer, tags (query): string | null

**Response 200:** unspecified

#### GET /apps/coordination/messages/inbox
Get Coordination Inbox

**Parameters:** agent_id (query): string, message_type (query): string | null, include_acknowledged (query): boolean, limit (query): integer

**Response 200:** unspecified

#### POST /apps/coordination/messages/{message_id}/acknowledge
Acknowledge Coordination Message

**Parameters:** message_id (path): string

**Body:** agent_id: string (required)

**Response 200:** unspecified

#### GET /apps/coordination/runs
Get Coordination Runs

**Response 200:** unspecified

#### GET /apps/coordination/runs/{parent_run_id}/children
Get Coordination Run Children

**Parameters:** parent_run_id (path): string

**Response 200:** unspecified

### Dashboard Overview

#### GET /apps/dashboard/overview
Get System Overview

**Response 200:** map[unspecified]

### Flow Engine

#### GET /platform/flows/registry
Get Flow Registry

**Response 200:** unspecified

#### GET /platform/flows/runs
List Flow Runs

**Parameters:** status (query): string | null, workflow_type (query): string | null, limit (query): integer

**Response 200:** unspecified

#### GET /platform/flows/runs/{run_id}
Get Flow Run

**Parameters:** run_id (path): string

**Response 200:** unspecified

#### GET /platform/flows/runs/{run_id}/history
Get Flow Run History

**Parameters:** run_id (path): string

**Response 200:** unspecified

#### POST /platform/flows/runs/{run_id}/resume
Resume Flow Run

**Parameters:** run_id (path): string

**Body:** event_type: string (required), payload: map[unspecified]

**Response 200:** unspecified

### Freelance

#### GET /apps/freelance/clients
List Clients

**Response 200:** unspecified

#### GET /apps/freelance/clients/{client_id}
Get Client Lineage

**Parameters:** client_id (path): integer

**Response 200:** unspecified

#### POST /apps/freelance/clients/onboard
Onboard Client — Phase 3 client-workflow flow. Convert a qualified lead into a client
+ order, then dispatch delivery generation when requested — one multi-step, observable
flow (`freelance_client_onboarding`). Requires an `Idempotency-Key` header.

**Body:** auto_generate_delivery: boolean, client_email: string (required), client_name: string | null, delivery_config: map[unspecified] | null, delivery_type: string | null, lead_id: integer (required), price: number | null, project_details: string | null, service_type: string (required)

**Response 201:** unspecified

#### POST /apps/freelance/deliver/{order_id}
Deliver Order

**Parameters:** order_id (path): integer, ai_output (query): string | null

**Response 200:** unspecified

#### PUT /apps/freelance/delivery/{order_id}
Update Delivery Configuration

**Parameters:** order_id (path): integer

**Body:** delivery_config: map[unspecified] | null, delivery_type: string | null

**Response 200:** unspecified

#### GET /apps/freelance/feedback
Get All Feedback

**Response 200:** unspecified

#### POST /apps/freelance/feedback
Collect Feedback

**Body:** feedback_text: string | null (required), order_id: integer (required), rating: integer | null (required)

**Response 200:** unspecified

#### POST /apps/freelance/generate/{order_id}
Generate Delivery

**Parameters:** order_id (path): integer

**Response 200:** unspecified

#### GET /apps/freelance/intake/actioned-leads
List Actioned Leads — leads the Search Execution Layer has drafted outreach for,
ready to convert into a client + order.

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### POST /apps/freelance/intake/from-action
Intake From Action — convert a Search-actioned lead (LeadAction) into a client +
order. Requires an `Idempotency-Key` header. Completes the lead -> outreach -> client
-> priced-order chain; the order price defaults from the service-price catalog when
none is supplied.

**Body:** action_id: integer (required), client_email: string (required), service_type: string (required), client_name: string | null, price: number | null, project_details: string | null, delivery_type: string | null, delivery_config: map[unspecified] | null, auto_generate_delivery: boolean

**Response 201:** unspecified

#### POST /apps/freelance/intake/from-lead
Intake From Lead

**Body:** auto_generate_delivery: boolean, client_email: string (required), client_name: string | null, delivery_config: map[unspecified] | null, delivery_type: string | null, lead_id: integer (required), price: number | null, project_details: string | null, service_type: string (required)

**Response 201:** unspecified

#### GET /apps/freelance/metrics/latest
Get Latest Metrics

**Response 200:** unspecified

#### POST /apps/freelance/metrics/update
Update Metrics

**Response 200:** unspecified

#### POST /apps/freelance/order
Create Freelance Order

**Body:** auto_generate_delivery: boolean, automation_config: map[unspecified] | null, automation_type: string | null, client_email: string (required), client_name: string (required), delivery_config: map[unspecified] | null, delivery_type: string | null, masterplan_id: integer | null, price: number | null, project_details: string | null, service_type: string (required), task_id: integer | null

**Response 201:** unspecified

#### GET /apps/freelance/orders
Get All Orders

**Response 200:** unspecified

#### POST /apps/freelance/orders/{order_id}/fulfill
Fulfill Order — Phase 3 client-workflow flow. Attach the deliverable to an order, then
refresh revenue metrics so they reflect the delivery — one multi-step flow
(`freelance_order_fulfillment`).

**Parameters:** order_id (path): integer

**Body:** ai_output: string | null, generated_by_ai: boolean

**Response 200:** unspecified

#### GET /apps/freelance/pricing
Get Pricing Catalog — the studio's current default price per service type (the apply
target of the Revenue Intelligence Loop).

**Response 200:** unspecified

#### POST /apps/freelance/pricing/optimize
Optimize Pricing — recommend (and optionally apply) gated, revertible service-price
adjustments from realized outcomes (paid revenue, acceptance, refund rate, ratings).
Dry run unless `apply=true`. Applying writes an internal default price for future
quotes; it never changes an existing order or charges a customer.

**Parameters:** apply (query): boolean (default false)

**Response 200:** unspecified

#### GET /apps/freelance/pricing/recommendations
List Pricing Recommendations — this user's recommendation runs (decisions, status,
revert state).

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### POST /apps/freelance/pricing/revert
Revert Pricing — restore the default price in effect before an applied recommendation.

**Body:** recommendation_id: integer (required)

**Response 200:** unspecified

#### POST /apps/freelance/refund/{order_id}
Refund Order

**Parameters:** order_id (path): integer

**Body:** object | null

**Response 200:** unspecified

#### POST /apps/freelance/subscription/{order_id}/cancel
Cancel Subscription

**Parameters:** order_id (path): integer

**Body:** object | null

**Response 200:** unspecified

### Genesis

#### POST /apps/genesis/audit
Audit Genesis Draft

**Body:** session_id: integer (required)

**Response 200:** unspecified

#### GET /apps/genesis/draft/{session_id}
Get Genesis Draft

**Parameters:** session_id (path): integer

**Response 200:** unspecified

#### POST /apps/genesis/import
Import An Existing Plan — seeds a Genesis session from a plan the user already wrote, in
whatever form it is in. The plan becomes the opening exchange of the conversation so it
can be discussed and refined before being synthesized and locked; it does not create a
MasterPlan directly. Reuses the active session when one exists.

**Body:** content: string (required)

**Response 200:** unspecified

#### POST /apps/genesis/lock
Lock Masterplan Draft

**Body:** map[unspecified]

**Response 200:** unspecified

#### POST /apps/genesis/message
Send Genesis Message

**Body:** map[unspecified]

**Response 200:** unspecified

#### POST /apps/genesis/session
Create Genesis Session

**Response 200:** unspecified

#### GET /apps/genesis/session/{session_id}
Get Genesis Session

**Parameters:** session_id (path): integer

**Response 200:** unspecified

#### POST /apps/genesis/synthesize
Synthesize Genesis Draft

**Body:** map[unspecified]

**Response 200:** unspecified

#### POST /apps/genesis/{plan_id}/activate
Activate Masterplan

**Parameters:** plan_id (path): integer

**Response 200:** unspecified

### Goals

#### GET /apps/goals
List Goals

**Response 200:** unspecified

#### POST /apps/goals
Create Goal Route

**Body:** description: string | null, goal_type: string, name: string (required), priority: number, status: string, success_metric: map[unspecified]

**Response 201:** unspecified

#### GET /apps/goals/state
List Goal State

**Response 200:** unspecified

### Health

#### GET /health
Check Health

**Response 200:** unspecified

#### GET /health/
Check Health (Legacy Alias)

**Response 200:** unspecified

#### GET /health/deep
Check Deep Health

**Response 200:** unspecified

#### GET /health/detail
Check Detailed Health

**Response 200:** unspecified

#### GET /health/details
Check Detailed Health (Legacy Alias)

**Response 200:** unspecified

#### GET /ready
Check Readiness

**Response 200:** map[unspecified]

### Health Dashboard

#### GET /apps/dashboard/health
Get Health Logs

**Parameters:** limit (query): integer

**Response 200:** unspecified

### Identity Layer

#### GET /apps/identity/
Get Identity

**Response 200:** unspecified

#### PUT /apps/identity/
Update Identity

**Body:** avoided_tools: array[string] | null, communication_notes: string | null, decision_notes: string | null, detail_preference: string | null, learning_notes: string | null, learning_style: string | null, preferred_languages: array[string] | null, preferred_tools: array[string] | null, risk_tolerance: string | null, speed_vs_quality: string | null, tone: string | null

**Response 200:** unspecified

#### GET /apps/identity/boot
Boot Identity

**Response 200:** unspecified

#### GET /apps/identity/context
Get Identity Context

**Response 200:** unspecified

#### GET /apps/identity/evolution
Get Identity Evolution

**Response 200:** unspecified

#### GET /apps/identity/inference
Get Identity Inference — inspect the evidence behind each inferred identity dimension:
the currently committed value, what the accumulated evidence points to, and its
confidence, support, and full distribution (the probabilistic inference, made
transparent).

**Response 200:** unspecified

### Infinity Score

#### GET /apps/scores/feedback
Get Score Feedback

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### POST /apps/scores/feedback
Record Score Feedback

**Body:** feedback_text: string | null, feedback_value: integer (required), loop_adjustment_id: string | null, source_id: string | null, source_type: enum(arm, agent, manual) (required)

**Response 200:** unspecified

#### GET /apps/scores/me
Get My Score

**Response 200:** unspecified

#### GET /apps/scores/me/history
Get Score History

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### POST /apps/scores/me/recalculate
Recalculate My Score

**Response 200:** unspecified

### Lead Generation

#### GET /apps/leadgen/
List All Leads

**Response 200:** unspecified

#### POST /apps/leadgen/
Generate B2B Leads

**Parameters:** query (query): string

**Response 200:** unspecified

#### GET /apps/leadgen/search
Preview Lead Search

**Parameters:** query (query): string

**Response 200:** unspecified

#### POST /apps/leadgen/execute
Execute Lead Actions — the Search Execution Layer. Act on scored leads by drafting
(never sending) outreach for those that clear a safety gate (score threshold, data
quality, dedup vs already-actioned, max-per-run). Dry run unless `apply=true`; every
action is tracked and revertible. No channel contacts a lead in this cut.

**Parameters:** apply (query): boolean (default false), channel (query): string (draft | email | handoff; default draft)

**Response 200:** unspecified

#### POST /apps/leadgen/execute/revert
Revert Lead Action — mark an action reverted so its lead is eligible for action again.

**Body:** action_id: integer (required)

**Response 200:** unspecified

#### GET /apps/leadgen/actions
List Lead Actions — this user's lead actions (drafts, decisions, status, revert state).

**Parameters:** limit (query): integer

**Response 200:** unspecified

### Legacy Compatibility

#### GET /apps/analyze_ripple/{drop_point_id}
Analyze Ripple

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### POST /apps/build_playbook/{strategy_id}
Build Playbook View

**Parameters:** strategy_id (path): string

**Response 200:** unspecified

#### GET /apps/causal_chain/{drop_point_id}
Causal Chain View

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/causal_graph
Causal Graph View

**Response 200:** unspecified

#### GET /apps/dashboard
Proofboard Dashboard

**Response 200:** unspecified

#### GET /apps/emerging_drops
Emerging Drops View

**Response 200:** unspecified

#### POST /apps/evaluate/{drop_point_id}
Evaluate Drop Point

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/generate_content/{playbook_id}
Generate Content View

**Parameters:** playbook_id (path): string

**Response 200:** unspecified

#### POST /apps/generate_content_for_drop/{drop_point_id}
Generate Content For Drop View

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/generate_variations/{playbook_id}
Generate Variations View

**Parameters:** playbook_id (path): string

**Response 200:** unspecified

#### GET /apps/influence_chain/{drop_point_id}
Influence Chain View

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/influence_graph
Influence Graph View

**Response 200:** unspecified

#### GET /apps/learning_stats
Learning Stats View

**Response 200:** unspecified

#### GET /apps/narrative/{drop_point_id}
Narrative View

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/narrative_summary
Narrative Summary View

**Response 200:** unspecified

#### GET /apps/playbook/{playbook_id}
Playbook View

**Parameters:** playbook_id (path): string

**Response 200:** unspecified

#### GET /apps/playbook_match/{drop_point_id}
Playbook Match View

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/playbooks
Playbooks View

**Response 200:** unspecified

#### GET /apps/predict/{drop_point_id}
Predict Drop Point View

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/prediction_summary
Prediction Summary View

**Response 200:** unspecified

#### GET /apps/recommend/{drop_point_id}
Recommend Drop Point

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/recommendations_summary
Recommendations Summary View

**Response 200:** unspecified

#### GET /apps/ripple_deltas/{drop_point_id}
Ripple Deltas

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/strategies
Strategies View

**Response 200:** unspecified

#### GET /apps/strategy/{strategy_id}
Strategy View

**Parameters:** strategy_id (path): string

**Response 200:** unspecified

#### GET /apps/strategy_match/{drop_point_id}
Strategy Match View

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/top_drop_points
Top Drop Points

**Response 200:** unspecified

### MasterPlans

#### GET /apps/masterplans/
List Masterplans

**Response 200:** unspecified

#### POST /apps/masterplans/lock
Lock From Genesis

**Body:** map[unspecified]

**Response 200:** unspecified

#### GET /apps/masterplans/{plan_id}
Get Masterplan

**Parameters:** plan_id (path): integer

**Response 200:** unspecified

#### POST /apps/masterplans/{plan_id}/activate
Activate Masterplan

**Parameters:** plan_id (path): integer

**Response 200:** unspecified

#### POST /apps/masterplans/{plan_id}/activate-cascade
Activate Cascade

**Parameters:** plan_id (path): integer

**Response 200:** unspecified

#### PUT /apps/masterplans/{plan_id}/anchor
Set Masterplan Anchor

**Parameters:** plan_id (path): integer

**Body:** anchor_date: string | null, goal_description: string | null, goal_unit: string | null, goal_value: number | null

**Response 200:** unspecified

#### POST /apps/masterplans/{plan_id}/lock
Lock Plan

**Parameters:** plan_id (path): integer

**Response 200:** unspecified

#### GET /apps/masterplans/{plan_id}/projection
Get Masterplan Projection

**Parameters:** plan_id (path): integer

**Response 200:** unspecified

### Memory

#### GET /apps/memory/agents
List Agents

**Response 200:** unspecified

#### GET /apps/memory/agents/{namespace}/recall
Recall From Agent Endpoint

**Parameters:** namespace (path): string, query (query): string | null, limit (query): integer | null

**Response 200:** unspecified

#### POST /apps/memory/execute
Execute With Memory

**Body:** auto_feedback: boolean | null, input: map[unspecified] (required), recall_before: boolean | null, remember_after: boolean | null, session_tags: array[string] | null, workflow: string (required)

**Response 200:** unspecified

#### POST /apps/memory/execute/complete
Complete Memory Loop

**Body:** context: map[unspecified] | null, outcome: enum(success, failure, neutral) (required), outcome_content: string (required), recalled_node_ids: array[string] | null, session_tags: array[string] | null, workflow: string (required)

**Response 200:** unspecified

#### POST /apps/memory/federated/recall
Federated Recall

**Body:** agent_namespaces: array[string] | null, limit: integer | null, query: string | null, tags: array[string] | null

**Response 200:** unspecified

#### POST /apps/memory/links
Create Link

**Body:** link_type: string | null, source_id: string (required), target_id: string (required), weight: number | null

**Response 201:** unspecified

#### GET /apps/memory/metrics
Get Memory Metrics

**Response 200:** unspecified

#### GET /apps/memory/metrics/dashboard
Get Memory Metrics Dashboard

**Response 200:** unspecified

#### GET /apps/memory/metrics/detail
Get Memory Metrics Detail

**Response 200:** unspecified

#### GET /apps/memory/nodes
Search Nodes By Tags

**Parameters:** tags (query): string, mode (query): string, limit (query): integer

**Response 200:** unspecified

#### POST /apps/memory/nodes
Create Node

**Body:** content: string (required), extra: map[unspecified] | null, node_type: enum(decision, outcome, insight, relationship) | null, source: string | null, tags: array[string] | null

**Response 201:** unspecified

#### POST /apps/memory/nodes/expand
Expand Nodes

**Body:** include_linked: boolean | null, include_similar: boolean | null, limit_per_node: integer | null, node_ids: array[string] (required)

**Response 200:** unspecified

#### POST /apps/memory/nodes/search
Search Similar Nodes

**Body:** limit: integer | null, min_similarity: number | null, node_type: enum(decision, outcome, insight, relationship) | null, query: string (required)

**Response 200:** unspecified

#### GET /apps/memory/nodes/{node_id}
Get Node

**Parameters:** node_id (path): string

**Response 200:** unspecified

#### PUT /apps/memory/nodes/{node_id}
Update Node

**Parameters:** node_id (path): string

**Body:** content: string | null, node_type: enum(decision, outcome, insight, relationship) | null, source: string | null, tags: array[string] | null

**Response 200:** unspecified

#### POST /apps/memory/nodes/{node_id}/feedback
Record Node Feedback

**Parameters:** node_id (path): string

**Body:** context: string | null, outcome: enum(success, failure, neutral) (required)

**Response 200:** unspecified

#### GET /apps/memory/nodes/{node_id}/history
Get Node History

**Parameters:** node_id (path): string, limit (query): integer | null

**Response 200:** unspecified

#### GET /apps/memory/nodes/{node_id}/links
Get Linked Nodes

**Parameters:** node_id (path): string, direction (query): string

**Response 200:** unspecified

#### GET /apps/memory/nodes/{node_id}/performance
Get Node Performance

**Parameters:** node_id (path): string

**Response 200:** unspecified

#### POST /apps/memory/nodes/{node_id}/share
Share Memory Node

**Parameters:** node_id (path): string

**Response 200:** unspecified

#### GET /apps/memory/nodes/{node_id}/traverse
Traverse From Node

**Parameters:** node_id (path): string, max_depth (query): integer | null, link_type (query): string | null, min_strength (query): number | null

**Response 200:** unspecified

#### POST /apps/memory/nodus/execute
Execute Nodus Task

**Body:** allowed_operations: array[string] | null, capability_token: map[unspecified] | null, context: map[unspecified] | null, execution_id: string | null, operation_code: string | null, operation_name: string | null, session_tags: array[string] | null, task_code: string | null, task_name: string | null

**Response 200:** unspecified

#### POST /apps/memory/recall
Recall Memories

**Body:** limit: integer | null, node_type: enum(decision, outcome, insight, relationship) | null, query: string | null, tags: array[string] | null

**Response 200:** unspecified

#### POST /apps/memory/recall/v3
Recall V3

**Body:** expand_results: boolean | null, limit: integer | null, node_type: enum(decision, outcome, insight, relationship) | null, query: string | null, tags: array[string] | null

**Response 200:** unspecified

#### POST /apps/memory/suggest
Get Suggestions

**Body:** context: string | null, limit: integer | null, query: string | null, tags: array[string] | null

**Response 200:** unspecified

#### GET /apps/memory/traces
List Traces

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### POST /apps/memory/traces
Create Trace

**Body:** description: string | null, extra: map[unspecified] | null, source: string | null, title: string | null

**Response 201:** unspecified

#### GET /apps/memory/traces/{trace_id}
Get Trace

**Parameters:** trace_id (path): string

**Response 200:** unspecified

#### POST /apps/memory/traces/{trace_id}/append
Append Trace Node

**Parameters:** trace_id (path): string

**Body:** node_id: string (required), position: integer | null

**Response 201:** unspecified

#### GET /apps/memory/traces/{trace_id}/nodes
Get Trace Nodes

**Parameters:** trace_id (path): string, limit (query): integer, include_nodes (query): boolean

**Response 200:** unspecified

### Network Bridge

#### GET /apps/network_bridge/authors
List Authors

**Parameters:** platform (query): string | null, limit (query): integer

**Response 200:** unspecified

#### POST /apps/network_bridge/connect
Connect External Author

**Body:** author_name: string (required), connection_type: string, notes: string | null, platform: string (required)

**Response 200:** map[unspecified]

#### POST /apps/network_bridge/user_event
Log User Event

**Body:** action: string, name: string (required), platform: string, tagline: string (required)

**Response 200:** unspecified

### Observability

#### GET /platform/observability/dashboard
Get Observability Dashboard

**Parameters:** window_hours (query): integer, request_limit (query): integer, event_limit (query): integer, agent_limit (query): integer, health_limit (query): integer

**Response 200:** unspecified

#### GET /platform/observability/execution_graph/{trace_id}
Get Execution Graph

**Parameters:** trace_id (path): string

**Response 200:** unspecified

#### GET /platform/observability/llm/status
Get Llm Status

**Response 200:** unspecified

#### POST /platform/observability/queue/dlq/drain
Drain Queue Dlq

**Body:** max_items: integer, requeue: boolean

**Response 200:** unspecified

#### GET /platform/observability/queue/metrics
Get Queue Metrics

**Response 200:** unspecified

#### GET /platform/observability/requests
Get Request Metrics

**Parameters:** limit (query): integer, error_limit (query): integer, window_hours (query): integer

**Response 200:** unspecified

#### GET /platform/observability/scheduler/status
Get Scheduler Status

**Response 200:** unspecified

### Platform

#### GET /platform/flows
List Flows

**Response 200:** unspecified

#### POST /platform/flows
Create Flow

**Body:** edges: map[array[string]], end: array[string] (required), name: string (required), nodes: array[string] (required), overwrite: boolean, start: string (required)

**Response 201:** unspecified

#### DELETE /platform/flows/{name}
Delete Flow

**Parameters:** name (path): string

**Response 204:** unspecified

#### GET /platform/flows/{name}
Get Flow

**Parameters:** name (path): string

**Response 200:** unspecified

#### POST /platform/flows/{name}/run
Run Flow Endpoint

**Parameters:** name (path): string

**Body:** state: map[unspecified]

**Response 200:** unspecified

#### GET /platform/keys
List Keys

**Response 200:** unspecified

#### POST /platform/keys
Create Key

**Body:** expires_at: string | null, name: string (required), scopes: array[string] (required)

**Response 201:** unspecified

#### DELETE /platform/keys/{key_id}
Revoke Key

**Parameters:** key_id (path): string

**Response 204:** unspecified

#### GET /platform/keys/{key_id}
Get Key

**Parameters:** key_id (path): string

**Response 200:** unspecified

#### GET /platform/memory
List Memory Path

**Parameters:** path (query): string, limit (query): integer, query (query): string | null, tags (query): string | null

**Response 200:** unspecified

#### GET /platform/memory/trace
Memory Trace

**Parameters:** path (query): string, depth (query): integer

**Response 200:** unspecified

#### GET /platform/memory/tree
Memory Tree

**Parameters:** path (query): string, limit (query): integer

**Response 200:** unspecified

#### GET /platform/nodes
List Nodes

**Response 200:** unspecified

#### POST /platform/nodes/register
Register Node

**Body:** handler: string (required), name: string (required), overwrite: boolean, secret: string | null, timeout_seconds: integer, type: string (required)

**Response 201:** unspecified

#### DELETE /platform/nodes/{name}
Delete Node

**Parameters:** name (path): string

**Response 204:** unspecified

#### GET /platform/nodes/{name}
Get Node

**Parameters:** name (path): string

**Response 200:** unspecified

#### POST /platform/nodus/flow
Compile And Run Nodus Flow

**Body:** flow_name: string (required), input: map[unspecified], register: boolean, run: boolean, script: string (required)

**Response 200:** unspecified

#### POST /platform/nodus/run
Run Nodus Script

**Body:** error_policy: string, input: map[unspecified], script: string | null, script_name: string | null

**Response 200:** unspecified

#### GET /platform/nodus/schedule
List Nodus Schedules

**Response 200:** unspecified

#### POST /platform/nodus/schedule
Create Nodus Schedule

**Body:** cron: string (required), error_policy: string, input: map[unspecified], job_name: string | null, max_retries: integer, script: string | null, script_name: string | null

**Response 201:** unspecified

#### DELETE /platform/nodus/schedule/{job_id}
Delete Nodus Schedule

**Parameters:** job_id (path): string

**Response 204:** unspecified

#### GET /platform/nodus/scripts
List Nodus Scripts

**Response 200:** unspecified

#### GET /platform/nodus/trace/{trace_id}
Get Nodus Trace

**Parameters:** trace_id (path): string, limit (query): integer

**Response 200:** unspecified

#### POST /platform/nodus/upload
Upload Nodus Script

**Body:** content: string (required), description: string | null, name: string (required), overwrite: boolean

**Response 201:** unspecified

#### POST /platform/syscall
Dispatch Syscall

**Body:** name: string (required), payload: map[unspecified]

**Response 200:** unspecified

#### GET /platform/syscalls
List Syscalls

**Parameters:** version (query): string | null

**Response 200:** unspecified

#### GET /platform/tenants/{tenant_id}/usage
Get Tenant Usage

**Parameters:** tenant_id (path): string

**Response 200:** unspecified

#### GET /platform/webhooks
List Webhook Subscriptions

**Response 200:** unspecified

#### POST /platform/webhooks
Create Webhook

**Body:** callback_url: string (required), event_type: string (required), secret: string | null

**Response 201:** unspecified

#### DELETE /platform/webhooks/{subscription_id}
Delete Webhook Subscription

**Parameters:** subscription_id (path): string

**Response 204:** unspecified

#### GET /platform/webhooks/{subscription_id}
Get Webhook Subscription

**Parameters:** subscription_id (path): string

**Response 200:** unspecified

### Research

#### GET /apps/research/
List Results

**Response 200:** unspecified

#### POST /apps/research/
Create Result

**Body:** query: string (required), summary: string (required)

**Response 200:** unspecified

#### POST /apps/research/query
Run Research Query

**Body:** query: string (required), summary: string (required)

**Response 200:** unspecified

### RippleTrace

#### GET /apps/rippletrace/causal/chain/{drop_point_id}
Get Causal Chain View

**Parameters:** drop_point_id (path): string, depth (query): integer

**Response 200:** unspecified

#### GET /apps/rippletrace/causal/graph
Get Causal Graph

**Response 200:** unspecified

#### GET /apps/rippletrace/influence/graph
Get Influence Graph

**Response 200:** unspecified

#### POST /apps/rippletrace/detect
Detect Ripples — search the web for echoes of this user's drop points that are due for a
check, recording each new external reference as a ping. Results on the drop point's own
host, the drop point itself, and pages published before it are rejected rather than
recorded. Returns 503 when `PERPLEXITY_API_KEY` is unset.

**Parameters:** limit (query): integer (default 5, max 10)

**Response 200:** unspecified

#### POST /apps/rippletrace/drop_points/{drop_point_id}/detect
Detect Ripples For Drop Point

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### POST /apps/rippletrace/drop_point
Create Drop Point

**Body:** core_themes: array[string] (required), date_dropped: string | null, id: string (required), intent: string (required), platform: string (required), tagged_entities: array[string] (required), title: string (required), url: string | null

**Response 200:** unspecified

#### GET /apps/rippletrace/drop_points
All Drop Points

**Response 200:** unspecified

#### POST /apps/rippletrace/event
Log Ripple Event

**Body:** drop_point_id: string | null, notes: string | null, ping_type: string (required), source_platform: string | null, summary: string | null, url: string | null

**Response 200:** unspecified

#### GET /apps/rippletrace/event/{event_id}/downstream
Get Event Downstream

**Parameters:** event_id (path): string

**Response 200:** unspecified

#### GET /apps/rippletrace/event/{event_id}/upstream
Get Event Upstream

**Parameters:** event_id (path): string

**Response 200:** unspecified

#### POST /apps/rippletrace/ingest
Ingest Content Url

Ingest a published URL. A feed (RSS/Atom) is registered as a recurring content source and its entries become drop points; a page becomes a single drop point and reports any feed it advertises under `suggested_feeds`.

**Body:** url: string (required)

**Response 200:** unspecified

#### POST /apps/rippletrace/learning/adjust
Adjust Learning Thresholds

**Response 200:** unspecified

#### POST /apps/rippletrace/learning/evaluate/{drop_point_id}
Evaluate Learning Outcome

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/rippletrace/learning/stats
Get Learning Stats

**Response 200:** unspecified

#### GET /apps/rippletrace/narrative/summary
Get Narrative Summary

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### GET /apps/rippletrace/narrative/{drop_point_id}
Get Narrative

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### POST /apps/rippletrace/ping
Create Ping

**Body:** connection_summary: string | null, date_detected: string | null, drop_point_id: string (required), external_url: string | null, id: string (required), ping_type: string (required), reaction_notes: string | null, source_platform: string (required), strength: number | null

**Response 200:** unspecified

#### GET /apps/rippletrace/pings
All Pings

**Response 200:** unspecified

#### GET /apps/rippletrace/playbooks
List Playbooks View

**Response 200:** unspecified

#### GET /apps/rippletrace/playbooks/match/{drop_point_id}
Match Playbooks View

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/rippletrace/playbooks/{playbook_id}
Get Playbook View

**Parameters:** playbook_id (path): string

**Response 200:** unspecified

#### GET /apps/rippletrace/predictions/summary
Get Predictions Summary

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### GET /apps/rippletrace/predictions/{drop_point_id}
Get Drop Point Prediction

**Parameters:** drop_point_id (path): string, record_learning (query): boolean

**Response 200:** unspecified

#### GET /apps/rippletrace/recent
Recent Ripples

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### GET /apps/rippletrace/recommendations/summary
Get Recommendations Summary

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### GET /apps/rippletrace/recommendations/system
Get System Recommendations

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### GET /apps/rippletrace/recommendations/{drop_point_id}
Get Drop Point Recommendation

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/rippletrace/ripples/{drop_point_id}
Get Ripples

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/rippletrace/sources
List Content Sources

**Response 200:** unspecified

#### PATCH /apps/rippletrace/sources/{source_id}
Update Content Source

**Parameters:** source_id (path): string

**Body:** active: boolean (required)

**Response 200:** unspecified

#### DELETE /apps/rippletrace/sources/{source_id}
Delete Content Source

**Parameters:** source_id (path): string

**Response 200:** unspecified

#### POST /apps/rippletrace/sources/{source_id}/poll
Poll Content Source

**Parameters:** source_id (path): string

**Response 200:** unspecified

#### GET /apps/rippletrace/strategies
List Strategies View

**Response 200:** unspecified

#### GET /apps/rippletrace/strategies/build
Build Strategies View

**Response 200:** unspecified

#### GET /apps/rippletrace/strategies/match/{drop_point_id}
Match Strategies View

**Parameters:** drop_point_id (path): string

**Response 200:** unspecified

#### GET /apps/rippletrace/strategies/{strategy_id}
Get Strategy View

**Parameters:** strategy_id (path): string

**Response 200:** unspecified

#### GET /apps/rippletrace/{trace_id}
Get Trace Graph

**Parameters:** trace_id (path): string

**Response 200:** unspecified

### SEO

#### POST /apps/seo/analyze
Analyze Seo

**Body:** text: string (required), top_n: integer | null

**Response 200:** unspecified

#### POST /apps/seo/analyze_seo/
Analyze Seo Compat

**Body:** content: string (required)

**Response 200:** unspecified

#### POST /apps/seo/generate_meta/
Generate Meta Compat

**Body:** content: string (required)

**Response 200:** unspecified

#### POST /apps/seo/meta
Generate Meta

**Body:** limit: integer | null, text: string (required)

**Response 200:** unspecified

#### POST /apps/seo/suggest
Suggest Improvements

**Body:** text: string (required), top_n: integer | null

**Response 200:** unspecified

#### POST /apps/seo/suggest_improvements/
Suggest Improvements Compat

**Body:** content: string (required)

**Response 200:** unspecified

### Search History

#### GET /apps/search/history
List Search History

**Parameters:** limit (query): integer, search_type (query): string | null

**Response 200:** unspecified

#### DELETE /apps/search/history/{history_id}
Delete Search History Detail

**Parameters:** history_id (path): string

**Response 200:** unspecified

#### GET /apps/search/history/{history_id}
Get Search History Detail

**Parameters:** history_id (path): string

**Response 200:** unspecified

### Search Feedback

#### POST /apps/search/feedback
Record Search Feedback

Record implicit (click / dwell / convert / dismiss) or explicit (thumbs_up / thumbs_down) feedback on a search result. Idempotent per (user, query, result_ref, signal); an explicit vote clears the opposing thumbs.

**Body:** query: string (required), result_ref: string (required), signal: string (required), history_id: string | null

**Response 200:** unspecified

#### GET /apps/search/feedback/weights
Get Search Feedback Weights

Aggregated per-result outcome weight for a query (implicit + explicit blended).

**Parameters:** query (query): string (required)

**Response 200:** unspecified

### Social Layer

#### GET /apps/social/analytics
Get Social Analytics

**Response 200:** unspecified

#### GET /apps/social/feed
Get Feed

**Parameters:** limit (query): integer, trust_filter (query): string | null

**Response 200:** unspecified

#### POST /apps/social/post
Create Post

**Body:** ai_context: map[unspecified] | null, author_id: string (required), author_username: string (required), boosts: integer, clicks: integer, comments_count: integer, content: string (required), conversion_signal: number, created_at: string, engagement_score: number, id: string, impressions: integer, likes: integer, media_url: string | null, tags: array[string], trust_tier_required: string

**Response 200:** unspecified

#### GET /apps/social/posts/{post_id}/comments
List Post Comments

**Parameters:** post_id (path): string, limit (query): integer

**Response 200:** unspecified

#### POST /apps/social/posts/{post_id}/comments
Create Post Comment

**Parameters:** post_id (path): string

**Body:** author_username: string | null, content: string (required), parent_comment_id: string | null

**Response 200:** unspecified

#### POST /apps/social/posts/{post_id}/interact
Record Post Interaction

**Parameters:** post_id (path): string

**Body:** action: string (required), amount: integer

**Response 200:** unspecified

#### POST /apps/social/profile
Upsert Profile

**Body:** bio: string | null, id: string, joined_at: string, metrics_snapshot: map[number], tagline: string | null, tags: array[string], updated_at: string, username: string (required)

**Response 200:** unspecified

#### GET /apps/social/profile/{username}
Get Profile

**Parameters:** username (path): string

**Response 200:** unspecified

### Tasks

#### POST /apps/tasks/complete
Complete Task

**Body:** name: string (required)

**Response 200:** unspecified

#### POST /apps/tasks/create
Create Task

**Body:** automation_config: map[unspecified] | null, automation_type: string | null, category: string | null, dependencies: array[object], dependency_type: string | null, due_date: string | null, masterplan_id: integer | null, name: string | null, parent_task_id: integer | null, priority: string | null, recurrence: string | null, reminder_time: string | null, scheduled_time: string | null, title: string | null

**Response 200:** unspecified

#### GET /apps/tasks/list
List Tasks

**Response 200:** unspecified

#### POST /apps/tasks/pause
Pause Task

**Body:** name: string (required)

**Response 200:** unspecified

#### POST /apps/tasks/recurrence/check
Trigger Recurrence

**Response 200:** unspecified

#### POST /apps/tasks/start
Start Task

**Body:** name: string (required)

**Response 200:** unspecified

### analytics

#### GET /apps/analytics/kpi-weights
Get Kpi Weights

**Response 200:** unspecified

#### POST /apps/analytics/kpi-weights/adapt
Adapt Kpi Weights Endpoint

**Response 200:** unspecified

#### POST /apps/analytics/linkedin/manual
Ingest Linkedin Manual

**Body:** audience_quality_score: number, comments: number, follows: number, impressions: number (required), likes: number, link_clicks: number, masterplan_id: integer (required), members_reached: number (required), new_followers: number, period_end: string (required), period_start: string (required), period_type: string (required), profile_views: number, scope_id: string | null, scope_type: string (required), search_appearances: number, shares: number, watch_time_minutes: number

**Response 200:** unspecified

#### GET /apps/analytics/masterplan/{masterplan_id}
Get Masterplan Analytics

**Parameters:** masterplan_id (path): integer, period_type (query): string | null, platform (query): string | null, scope_type (query): string | null

**Response 200:** unspecified

#### GET /apps/analytics/masterplan/{masterplan_id}/summary
Get Masterplan Summary

**Parameters:** masterplan_id (path): integer, group_by (query): string | null

**Response 200:** unspecified

#### GET /apps/analytics/policy-thresholds
Get Policy Thresholds

**Response 200:** unspecified

#### POST /apps/analytics/policy-thresholds/adapt
Adapt Policy Thresholds Endpoint

**Response 200:** unspecified

#### GET /apps/analytics/goal-attainment
Get Goal Attainment — resolves the active MasterPlan's declared goal (`goal_value` +
`goal_unit`) against real domain signals. Phase 0: read-only and **not wired into scoring**
(`masterplan_progress` is unchanged). `supported: false` is a normal answer carrying a
`reason` — undeclared goal, unsupported unit, or a degraded domain — and means the existing
formula applies. Only the `tasks` unit resolves today; `supported_units` reports the live set.

**Response 200:** unspecified

#### GET /apps/analytics/three-axis
Get Three Axis Snapshot — observability snapshot of the Volume / Worth / Trajectory axes
alongside the (unchanged) `master_score` (three-axis score model, Phase A; measurement only,
does not drive scoring).

**Response 200:** unspecified

#### GET /apps/analytics/three-axis/shadow
Get Three Axis Shadow Report — recent shadow-ledger records (the axes logged next to
`master_score` on each score event) + a mean-per-axis summary (the divergence signal, Phase B).
Records accrue only while `AINDY_INFINITY_THREE_AXIS_SHADOW` is on.

**Parameters:** limit (query): integer

**Response 200:** unspecified

#### GET /apps/analytics/three-axis/advisory
Get Three Axis Advisory Preview — read-only "advisory vs. behavioral" comparison from the
user's current KPIs (three-axis score model, Phase C). Shows what the bounded Worth+Trajectory
blend would make `master_score`. The blend only *moves* the persisted score while
`AINDY_INFINITY_THREE_AXIS_ADVISORY` is on (default off); this preview works either way.

**Response 200:** unspecified

#### POST /apps/analytics/worth/declare
Declare Worth — declare what a task / masterplan / project is worth (the Worth axis's prior).
Upserts per (user, target_type, target_id).

**Body:** target_type: string (required), declared_value: number (required), target_id: string | null, label: string | null, kind: string, note: string | null

**Response 200:** unspecified

#### GET /apps/analytics/worth/declarations
List Worth Declarations — this user's declared-worth entries.

**Parameters:** limit (query): integer

**Response 200:** unspecified

### auth

#### POST /auth/login
Login

**Body:** email: string (required), password: string (required)

**Response 200:** access_token: string (required), token_type: string

#### POST /auth/register
Register

**Body:** email: string (required), password: string (required), username: string | null

**Response 201:** access_token: string (required), token_type: string

### root

#### GET /
Home

**Response 200:** unspecified

## Syscall Reference

### agent

#### sys.v1.agent.execute
Execute an approved AgentRun via the deterministic runtime.

**Status:** stable
**Capabilities:** agent.execute
**Input:** run_id: string (required)
**Output:** run_result: dict (required)

### event

#### sys.v1.event.emit
Emit a SystemEvent on the A.I.N.D.Y. event bus.

**Status:** stable
**Capabilities:** event.emit
**Input:** event_type: string (required), payload: dict
**Output:** unspecified

### flow

#### sys.v1.flow.execute_intent
Top-level intent execution with learned strategy selection.

**Status:** stable
**Capabilities:** flow.execute
**Input:** intent_data: dict (required)
**Output:** intent_result: dict (required)

#### sys.v1.flow.run
Execute a registered flow by name.

**Status:** stable
**Capabilities:** flow.run
**Input:** flow_name: string (required), initial_state: dict
**Output:** unspecified

### job

#### sys.v1.job.submit
Submit a named async job to the automation pipeline.

**Status:** stable
**Capabilities:** job.submit
**Input:** max_attempts: int, payload: dict, source: string, task_name: string (required)
**Output:** log_id: string (required), source: string, task_name: string

### masterplan

#### sys.v1.masterplan.assert_owned
Assert that the given user owns the given MasterPlan.

**Status:** experimental
**Capabilities:** masterplan.read
**Input:** masterplan_id: string (required), user_id: string (required)
**Output:** masterplan_id: string, owned: bool (required)

### memory

#### sys.v1.memory.list
List nodes at a MAS path prefix.

**Status:** experimental
**Capabilities:** memory.list
**Input:** limit: int, path: string (required)
**Output:** count: int (required), nodes: list (required)

#### sys.v1.memory.read
Recall memory nodes for the calling user.

**Status:** stable
**Capabilities:** memory.read
**Input:** limit: int, node_type: string, path: string, query: string, tags: list
**Output:** count: int (required), nodes: list (required)

#### sys.v1.memory.search
Semantic search over user memory nodes.

**Status:** stable
**Capabilities:** memory.search
**Input:** limit: int, path: string, query: string (required)
**Output:** count: int (required), nodes: list (required)

#### sys.v1.memory.trace
Follow the causal chain from a node at a path.

**Status:** experimental
**Capabilities:** memory.trace
**Input:** depth: int, path: string (required)
**Output:** chain: list (required), depth: int (required)

#### sys.v1.memory.tree
Return a hierarchical tree of nodes under a path.

**Status:** experimental
**Capabilities:** memory.tree
**Input:** limit: int, path: string (required)
**Output:** node_count: int (required), tree: dict (required)

#### sys.v1.memory.write
Persist a new memory node.

**Status:** stable
**Capabilities:** memory.write
**Input:** content: string (required), node_type: string, path: string, tags: list
**Output:** node: dict (required), path: string

#### sys.v2.memory.read
Enhanced memory recall with structured field filters (v2).

**Status:** experimental
**Capabilities:** memory.read
**Input:** filters: dict, limit: int, node_type: string, path: string, query: string, tags: list
**Output:** count: int (required), nodes: list (required), version: string

### nodus

#### sys.v1.nodus.execute
Execute a Nodus script via flow-backed orchestration.

**Status:** stable
**Capabilities:** nodus.execute
**Input:** error_policy: string, input_payload: dict, node_max_retries: int, script: string (required), trace_id: string, workflow_type: string
**Output:** nodus_result: dict (required)

### task

#### sys.v1.task.get
Get a task by ID for the current user.

**Status:** experimental
**Capabilities:** task.read
**Input:** task_id: integer (required), user_id: string
**Output:** task: dict (required)

#### sys.v1.task.get_user_tasks
Return the minimal task snapshot analytics needs for scoring.

**Status:** experimental
**Capabilities:** task.read
**Input:** user_id: string
**Output:** tasks: array[unspecified] (required)

#### sys.v1.task.queue_automation
Update task automation settings and queue task automation.

**Status:** experimental
**Capabilities:** task.write
**Input:** automation_config: dict, automation_type: string, reason: string, task_id: integer (required), user_id: string
**Output:** automation_task_trigger_result: dict (required)
