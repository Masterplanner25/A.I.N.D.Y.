---
title: "Goals layer"
last_verified: "2026-11-09"
api_version: "1.0"
status: draft
owner: "app-team"
---

# Goals layer: what the person is working toward, above any one plan

**Status:** scoped 2026-11-09; §8 decided the same day (all six as recommended). Not built.

**Origin.** The 2026-11-01 audit found Goals to be a dead twin (finding 6), and the owner decided on 2026-11-08 (D2) to
**wire it up as a separate user-level layer**, the model `STRATEGY_LAYER_SPEC` §6 Q1 and Q6 preserved. The owner asked
first for a look at what the masterplan section does today (§1), and for this spec before any code, because the Goals
code paths already act as soon as one goal exists (§3).

---

## 1. Where Goals sits today (read 2026-11-08)

The masterplan domain's live pieces:

- **The plan** (`master_plans`, 1 row): Genesis output, and a scalar **anchor**.
- **The strategy layer:**
  - three objectives (`plan_objectives`), seeded from the Genesis draft's `core_domains`;
  - five phases;
  - four strategies, each owned by an objective and scheduled into a phase.
  - Hours roll up from task to strategy to objective (`phase_advance.objective_rollup`, `objective_attainment`). Phase
    advance is a proposal the person confirms.
- **Works** (9), the Resolution Check, drafts, ETA, pace, the market.
- **The goal-attainment shadow** (`goal_attainment_shadow_records`, 64 rows): it resolves the plan's anchor and its
  objectives, and is recorded only (`AINDY_MASTERPLAN_GOAL_ATTAINMENT` is off).

**Goals is the one piece with no data, ever.**
- `goals` and `goal_states` have never held a row.
- Nothing in the client calls its 3 routes, and the client has never had a Goals UI (the git history has none).

The owner's plan, as Goals would see it:

| | |
|---|---|
| Anchor | **1,000,000 USD, "Financial Freedom", by 2030-12-31** |
| Success criteria (Genesis draft, never stored as rows) | "Establishment of a widely adopted ethical AI framework"; "Successful deployment of enabling platforms"; "Formation of strategic partnerships"; "Positive feedback from users and stakeholders"; "Sustainable funding models in place" |
| Objectives | 1 Ethical AI Framework · 2 Partnership Development · 3 Platform Enablement |

Three of the five criteria line up with the three objectives. Two ("positive feedback", "sustainable funding") have no
objective. All five are qualitative; only the anchor has a number.

**Already settled in the specs:**
- **Objective and goal are "the same statement at different grain"** (`STRATEGY_LAYER_SPEC` §6 Q1, 2026-09-07):
  - objectives belong to one plan;
  - goals belong to the person and outlive plan versions;
  - strategies are never linked to goals.
- **Seed goals from the success criteria, with the anchor as one of them** (§6 Q6). It was "not yet", for two reasons:
  1. there was no UI;
  2. a qualitative criterion would read as permanently unresolved.

## 2. What a Goal is

A **goal** is something the person is working toward, stated by them or seeded from their plan. It belongs to the
person, not to a plan version, so a new plan does not erase it.

The existing table keeps its columns (`apps/masterplan/goals.py`): `name`, `description`, `goal_type`, `priority`,
`status` (`active` | `completed` | `dropped`) and `success_metric` (JSONB). New, all nullable and additive:

| Column | Meaning |
|---|---|
| `source` | `anchor` \| `success_criterion` \| `stated`: where the goal came from |
| `masterplan_id` | the plan it was seeded from (provenance only; the goal outlives it) |
| `measure` | `anchor` \| `objectives` \| `declared` (§4) |
| `target_value`, `unit`, `target_date` | for a goal with a number (the anchor) |

**A new link table, `goal_objectives`** (`goal_id`, `objective_id`): the objectives that serve a goal.
- The link is a pointer from the person's layer into a plan.
- When the plan changes, the links to its objectives are re-proposed, and never silently moved.
- Strategies stay unlinked (Q1).

## 3. What already reads goals, and will act the moment one exists

These run today and get an empty list. Wiring Goals up changes their behaviour; it is not only a screen.

| Reader | What it does with goals | Where |
|---|---|---|
| The loop's next action | weights the decision by goal; at `ranked_priority` ≥ 0.70 it can replace the next action with `review_plan`, "Realign work toward goal: X" | `apps/analytics/services/reasoning/decision_engine.py:194-264` |
| The planner | sees that recommendation as "Suggested focus"; it has no goal block of its own | `apps/agent/agents/runtime_extensions.py:120-149` |
| The autonomy gate | goal alignment is 0.20 of a trigger's priority; the scheduled jobs pass their own alignment, so only the rank call runs there | `apps/agent/agents/triggers.py:104-119` |
| Agent ranking | up to +0.15 for an agent aligned with a top goal | `apps/masterplan/agents/ranking.py:36-50` |
| Goal completion | progress ≥ 0.999 marks the goal `completed` and runs a full Infinity loop | `goal_service.py:117-131`, `apps/analytics/bootstrap.py:89` |
| Progress today | every execution event nudges the top 5 goals by **keyword overlap** with the run's text | `goal_service.py:153-214`, wired at `apps/masterplan/bootstrap.py:389-401` |

The last row is the measurement the strategy layer deliberately chose not to repeat (`strategy_layer.py:68-71`). It is
the main thing this spec replaces (§4).

## 4. How a goal's progress is measured

The measure follows from the goal's kind. Keyword overlap goes.

- **`anchor`** (a number, a unit and a date):
  - Resolved the way the attainment shadow already resolves the plan's anchor
    (`apps/analytics/services/integration/goal_attainment.py:178-260`).
  - **Where nothing measures the unit, the goal says so.** For example, USD revenue is zero by the 2026-07-16 decision
    that freelance revenue is observability-only. In that case progress is *no measurement yet*, never 0%. Nothing is
    manufactured (audit D4).
- **`objectives`** (linked to objectives):
  - Progress is the attainment of the linked objectives (`objective_attainment`, hours attributed task → strategy →
    objective), averaged.
  - It moves when work the person did is attributed, not when a run's text shares words with the goal.
- **`declared`** (qualitative, nothing linked):
  - **No progress number.** The goal shows as declared, with its recent related work listed, and the person marks it
    done.
  - This answers Q6's blocker: a qualitative criterion is not "permanently unresolved", it is unmeasured by design and
    says so.

`goal_states.progress` keeps its meaning (0–1) for the first two, and is null for `declared`. `success_signal` and
`recent_actions` are kept, from the same sources.

## 5. Seeding, and the person's say

- **At plan lock**, Genesis proposes goals; it does not write them silently:
  - the anchor becomes one goal (`source=anchor`, `measure=anchor`);
  - each success criterion becomes one (`source=success_criterion`), with the objectives that obviously serve it
    proposed as links (`measure=objectives`), or no links (`measure=declared`).
  - The person confirms, edits or drops each, like phase advance and Work proposals.
- **The existing plan** gets the same proposal once, on first visit after this ships: its anchor and five criteria, with
  three criteria proposed against the three objectives that match them (§1).
- **Stated goals:** the person can add a goal of their own (`source=stated`).
- **A new plan version** does not touch existing goals. It proposes links from them to the new plan's objectives.

## 6. What the person sees

A **Goals** panel on the MasterPlan page, above Phases:
- each goal with its source, its measure and its progress, or *declared* / *no measurement yet*;
- the objectives it links to;
- its priority and status, which the person can edit;
- proposals to confirm.

No score is shown on it.

The planner gets **one line per active goal** in its context, beside the plan block, so goals reach it directly rather
than only through the loop's recommendation.

## 7. What it does not do

- **It does not feed the Infinity score.** Goal progress stays information for the person, the loop and the planner
  until it has been measured for a while, as the Resolution Check's decision 5 and `ARTICLE_ANSWERS_SPEC` decision 4 did.
  The attainment shadow and its flag are unchanged.
- **It does not link strategies to goals** (Q1).
- **It does not invent progress** for a goal nothing measures.

## 8. Decisions: the owner's, **all six taken 2026-11-09, as recommended**

1. **Seeding: DECIDED, proposed.** At plan lock and once for the existing plan, each goal is proposed with suggested
   objective links; the person confirms, edits or drops each.
   - Not chosen: written directly.
2. **Qualitative goals: DECIDED, declared.** No progress number; recent related work is listed; the person marks one done.
   - Not chosen: a proxy measure each, which risks a number that means nothing.
3. **Keyword-overlap progress: DECIDED, retired.** Progress comes only from the anchor resolver and objective attainment.
   - Not chosen: keeping it as a related-work list.
4. **The loop's `review_plan` override: DECIDED, measured goals only.** It stays at `ranked_priority` ≥ 0.70, for goals
   with a measure (`anchor` or `objectives`), so a declared goal cannot steer the loop on priority alone.
   - Not chosen: keeping it for any goal; removing it.
5. **A planner block: DECIDED, yes.** One line per active goal, with its measure and progress, beside the plan block.
   - Not chosen: the loop's recommendation only.
6. **Score effect: DECIDED, none yet.** Goal progress stays information until it has been measured for a while; the
   question comes back in phase D.
   - Not chosen: blending it in now.

## 9. Phases

| Phase | What | Schema |
|---|---|---|
| **A** ✅ **built 2026-11-09** | Measures (§4): progress from the anchor resolver and objective attainment; keyword overlap retired (per decision 3); the readers in §3 unchanged. As built:
  - `goal_service.measure_goal` / `refresh_goal_states`;
  - the anchor goes through the `analytics.resolve_goal_attainment` job (masterplan imports no analytics);
  - `update_goals_from_execution` recomputes from the measures;
  - a goal's `measured` flag gates the loop's `review_plan` override (decision 4);
  - migration `gl1layer0001` (`goal_states.progress` nullable) | columns on `goals`, the `goal_objectives` table |
| **B** | Seeding and proposals (§5): at lock and once for the existing plan; confirm, edit, drop; stated goals | none beyond A |
| **C** | The Goals panel (§6) and the planner line | none |
| **D** | Watch the readers act on real goals for a while (§3); then the score question (decision 6) | none |

Each phase is one PR. A reaches nothing until B writes the first goal, so A ships behind no flag and changes no
behaviour on its own.
