---
title: "Cognitive Operations — what kind of thinking are we doing"
last_verified: "2026-08-06"
api_version: "1.0"
status: current
owner: "app-team"
---

# Cognitive Operations — what kind of thinking are we doing

**Status:** spec, not started. Written 2026-08-06.

---

## 1. The question

> *All AIs can plan. What makes Genesis — and the agent — different?*

Any model will produce a plan. Ask one to sequence five tasks and you get a numbered list that
is forgotten when the context closes. The plan is **prose**: articulate, unowned, and incapable
of being wrong later because nothing recorded what it promised.

The difference here is not the operation. It is what the operation **produces**.

> "Sequence these" should not return a list. It should return a **typed graph with a computed
> critical path**, persisted, attached to a plan, feeding ETA and WCU, and measurable afterwards
> against what actually happened.

A plan that can be wrong later is a plan that means something when it is right. That is the same
claim `SELF_TRUST_CALIBRATION_SPEC.md` makes from the other direction, and the same one
`The Masterplan_V4` makes as a thesis: *"proving that individuals and small teams can rival
institutions through clarity, velocity, and intentional design."* The value is in the plan
becoming physics.

---

## 2. The vocabulary already exists — 210 decisions and counting

This is not a new mechanism. The system already names operations, infers which one applies from
live state, records the choice, and trains a model per operation.

Measured 2026-08-06, `loop_adjustments.decision_type`:

| Operation | Recorded |
|---|---|
| `review_plan` | 153 |
| `create_new_task` | 25 |
| `continue_highest_priority_task` | 22 |
| `reprioritize_tasks` | 10 |

Four verbs, **210 decisions**. `recommend_next_action` picks one from the user's state; the
choice is written to `loop_adjustments`; `infinity_expectation_predictions` carries
`decision_type` and scores predicted against actual **per operation**.

**So the operating model is already: the system names the operation, not the user.** What is
missing is vocabulary, not machinery.

---

## 3. Inferred, not selected — the load-bearing design decision

The obvious reading of "modes" is a menu: the user picks *decomposition*, or *prioritisation*,
or *critique*. **Do not build that.**

A twenty-four-item mode picker is a beautiful surface everyone bypasses to type at the box, and
it puts the burden of naming the operation on the person least able to name it — someone who
has forty unordered tasks precisely because they do not yet know that what they need is
dependency analysis.

The system is better placed to know. It can see the plan, the task graph, the unresolved
dependencies, the score history and the throughput. So:

> **The system names the operation you are already in, and offers the machinery for it.**

This is the anti-chatbot move one layer up. A chat surface must ask "what would you like to talk
about?" because it has no state. This one can say *"you have 40 tasks and 11 unresolved
dependencies — want me to sequence them?"* — and it can say it because the graph is already
computed.

Two mechanisms for this exist and are unwired to the product face:

- **`suggest_tools_for_kpi`** — derives suggestions from the live KPI snapshot. Consumed only by
  the operator console (`SURFACE_IDENTITY_BRIEF.md` §1).
- **`reasoning.evaluate`** — returns the autonomous next-action recommendation, already
  producing the four decision types above.

**Selection stays available as an override, not as the primary interaction.** Someone arriving
with "critique this strategy" should be served; they should just never have to hunt for the verb.

---

## 4. The operation inventory — most of it is already built

Audited 2026-08-06. The operations named in the product discussion, against what exists:

| Operation | Machinery | State |
|---|---|---|
| Decomposition | Genesis phases → tasks with dependency chaining | ✅ built |
| Dependency analysis | `_normalize_dependencies`, `_validate_dependencies`, `_dependencies_complete` | ✅ built |
| Sequencing | `build_task_graph` → `topological_order` | ✅ built |
| Critical path | `critical_weight`, `critical_duration`, `critical_path`, `ready`, `blocked` | ✅ built |
| Prioritisation | `_reprioritize_tasks` (Infinity loop), `reprioritize_tasks` decision | ✅ built + named |
| Synthesis | `synthesize_genesis` — the 11-field draft | ✅ built |
| Critique / validation | `genesis.audit` — a third LLM pass over the draft | ✅ built |
| Strategy | `determine_posture` from `ambition_score`; rippletrace strategy engine | ✅ built |
| Iteration | ARM autotune, search feedback, freelance pricing — the learning loops | ✅ built |
| Scenario analysis | `sys.v1.agent.simulate` registered | ⚠️ registered, unverified |
| Review | `review_plan` — 153 decisions | ✅ built + named |
| Retrospective | — | ❌ nothing found |
| Gap analysis | Domain Engine attainment (declared vs actual) | ⚠️ scoped, not built |
| Formalization | Nodus — fuzzy intent to executable | ✅ built, different surface |
| Exploration / brainstorming | Genesis conversation | ✅ built |
| Tradeoff, constraint, risk, resource allocation | — | ❌ nothing found |

**So roughly two-thirds exist as engines.** They are scattered across domains and none of them
is reachable by name. The gap is a vocabulary and a surface, not a build.

---

## 5. What defines an operation

For the vocabulary to expand without becoming a menu, each operation needs five things. The four
existing decision types already have all five, which is why they work.

| | |
|---|---|
| **Name** | a `decision_type` string — the system's word for it |
| **Trigger** | the state condition that makes it the right operation now |
| **Inputs** | what it reads (task graph, plan, scores, memory) |
| **Typed output** | a durable artifact, not prose — see §6 |
| **Expectation** | a per-`decision_type` model, so calibration is per operation |

That last one matters more than it looks. Because `infinity_expectation_predictions` keys on
`decision_type`, **calibration is already per-operation**. The system can learn that you are
well-calibrated at decomposition and badly calibrated at estimation — which is a far more useful
statement than one global self-trust number, and it falls out of the existing schema.

---

## 6. Typed output is the whole differentiator

The rule that separates this from a chat surface:

> **Every operation produces an artifact the system can hold, measure and be wrong about.**

| Operation | Prose answer | Typed output |
|---|---|---|
| Sequence | a numbered list | task graph edges + `topological_order`, persisted |
| Prioritise | "do A first" | ordered task set with a recorded rationale |
| Decompose | bullet points | tasks with dependencies, attached to a plan |
| Critique | paragraphs | audit findings against the draft, versioned |
| Gap analysis | "you're behind on revenue" | per-domain attainment against `target_value` |
| Retrospective | a summary | recorded outcomes, feeding calibration |

If an operation cannot produce something durable, it is a conversation, and that is fine — but
it should not be called an operation.

---

## 7. What is genuinely missing

1. **Nothing is reachable by name.** No surface says "sequence these" or exposes the operation
   the system has already chosen.
2. **Suggestions go to the wrong screen.** `suggest_tools_for_kpi` is consumed only by the
   operator console.
3. **The vocabulary is four verbs.** Expanding it is the actual work: each new operation needs
   the five properties in §5.
4. **Some operations have no engine** — retrospective, tradeoff, constraint and risk analysis
   found nothing. These are builds, not wiring.
5. **Typed output is inconsistent.** Genesis synthesis and the task graph produce structure;
   other paths produce text.

---

## 8. Rollout

1. **Surface what is already chosen.** Put `reasoning.evaluate`'s recommendation and
   `suggest_tools_for_kpi`'s output on the Collaborator face. Zero new operations; the system
   starts naming the operation you are in. This is a wiring change.
2. **Name the built-but-unreachable ones.** Sequencing, dependency analysis and critical path
   already compute — give them decision types, triggers and a way to be offered.
3. **Add expectation models per new operation**, so calibration stays per-operation as the
   vocabulary grows.
4. **Build the missing engines** — retrospective first, because it feeds calibration and the
   learning loops already have the outcome data.

Phase 1 is the highest-value step in this document and needs no new operations at all.

---

## 9. What this does not do

- Does not build a mode picker. §3 is the reason.
- Does not replace the conversation. Conversation stays the interaction mechanism; it stops
  being the product definition.
- Does not add operations without typed output. An operation that returns prose is a chat turn.
- Does not decide how many operations is too many. See §10.

---

## 10. Open questions

- **How many verbs before the vocabulary is noise?** Four works. Twenty-four is a taxonomy, and
  taxonomies are easier to write than to infer between. The constraint is the trigger: if two
  operations cannot be distinguished from state, they are one operation.
- **What happens when the system is wrong about the operation?** Offering "sequence these" to
  someone who wanted to explore is worse than asking. Needs a cheap decline that teaches.
- **Does the user ever pick?** Selection as override (§3) is assumed here, not designed.
- **Does an operation need to be reversible?** `reprioritize_tasks` changes state. If the system
  proposes and executes, the undo path matters — `sys.v1.agent.undo` exists and is unexamined.
