# MasterPlan — Redesign Brief

**Status:** diagnosis complete, no decision taken. Written 2026-08-01.
**Origin:** walk-log item 18 follow-on. Owner asked for a scope look at the MasterPlan domain;
the investigation was widened after the original build docs were consulted.

**Sources:** live probing of the running stack (every claim below was reproduced, not inferred),
plus the two original build documents:

- `Masterplan Module_Plans .docx` — the physics engine spec
- `Masterplan_Genesis_Module.docx` — the Genesis layer spec

---

## 1. The one-line diagnosis

**The system computes far more than it shows.** MasterPlan is not underbuilt — its engine room is
the most complete in the repo. It is *unsurfaced*, and one specific abstraction it was told to
build (in 2024, in writing) got built and wired to the wrong consumer.

This is the same shape as `/kpi` (#168) and `/analytics` (#172): a working engine behind a
keyhole surface. Third instance. See `dead-twin-surfaces` in the session memory.

---

## 2. What actually works — verified live, end to end

A full Genesis run was executed against the running stack for the first time. It produced
**plan 4**, the first MasterPlan this system has ever created.

| Stage | Result |
|---|---|
| Genesis conversation | ✅ 5 turns, GPT-4o, with memory + ARM + identity context injected |
| State extraction | ✅ `vision_summary`, `time_horizon`, `inferred_domains: ["consulting"]`, confidence |
| Synthesis | ✅ 11-field draft, specific and coherent |
| Audit | ✅ third LLM call, draft integrity validation |
| Lock | ✅ plan created, `posture: Accelerated`, `version_label: V1` |
| **Phases → tasks** | ✅ **3 tasks created with correct dependency chaining** (1 pending, 2 blocked) |
| Projection / ETA | ✅ velocity, critical depth, blocked/ready counts, ETA confidence |
| WCU | ✅ computed from completed tasks |

The AI is doing real work, and the cascade from conversation → plan → executable, dependency-aware
tasks genuinely functions. **This is not a hollow domain.**

---

## 3. What the screen gets

| Layer | Fields available | Fields surfaced |
|---|---|---|
| AI draft (`structure_json`) | 11 — vision, domains, phases, criteria, risks, assets, mechanism | 0 |
| Projection engine | ~12 — velocity, ETA, critical path, blocked/ready | 0 on the plan list |
| Derived tasks | 3, dependency-chained | 0 |
| **`GET /apps/masterplans/`** | **6 scalars** — id, status, posture, is_active, locked_at, created_at | **all** |
| `GET /apps/masterplans/{id}` | would carry `structure_json` | **HTTP 500** |

The dashboard is thin because the only working endpoint returns six scalars. Everything a user
would want is already computed and persisted; it has no path to the browser.

---

## 4. The abstraction that was built and mis-wired

The Genesis build doc records the owner identifying this exact problem:

> *"1 — it's entirely too tailored to me specifically. 2 — I haven't really set up anywhere people
> can either talk to it or get it to help them create a masterplan"*

It prescribed a **three-path order: B → then A → then C.**

- **B — Structural fix.** *"Right now you have hardcoded domains like: Books, Studio, Platform,
  Revenue. You need to abstract:"*
  ```
  Domain { name, category, threshold_type (count/boolean/value/composite), target_value }
  ```
  *"That turns A.I.N.D.Y. from Shawn's life arc into a framework engine."*
- **A — Quick fix.** A guided creation assistant (Layer 1), plus **Layer 2: an editable config
  view** to refine thresholds and toggle domains.
- **C — Experience fix.** UI flow redesign.

### What shipped

**A shipped.** Genesis works.

**B shipped too — as `Goal` + `GoalState`** — and matches the prescription closely:

| Doc prescribed | Shipped as |
|---|---|
| `name` | `Goal.name` |
| `category` | `Goal.goal_type` |
| `threshold_type` + `target_value` | `Goal.success_metric` (JSONB) |
| domain weight | `Goal.priority` |
| progress tracking | `GoalState.progress`, `success_signal`, `recent_actions` |

`GoalState.progress` is **auto-fed by execution events** (`update_goals_from_execution`) — exactly
the live-progress feed MasterPlan's own columns never got.

**But `Goal` has zero connection to `MasterPlan`.** No reference in `goals.py`, `goal_state.py`,
or `goal_service.py`. It was wired to the **agent/autonomy layer** — ranking, drift detection,
alignment scoring — never to plan physics. It currently holds **0 rows**, so the machinery is live
but unexercised.

**Layer 2 was never built at all.** There is no surface where a user can change what their plan is
measured against — which is the literal mechanism behind "too tailored to me".

---

## 5. The consequence: the phase gate cannot fire

`evaluate_phase` advances a plan when six conditions hold. **Five of the six compare a progress
column that nothing in the codebase ever writes.**

| Progress column | Default | Threshold | Default | Writer |
|---|---|---|---|---|
| `gross_revenue` | 0 | `revenue_target` | 100000 | none |
| `books_published` | 0 | `books_required` | 3 | none |
| `platform_live` | False | `platform_required` | True | none |
| `studio_ready` | False | `studio_required` | True | none |
| `active_playbooks` | 0 | `playbooks_required` | 2 | none |
| `total_wcu` | 0 | `wcu_target` | 3000 | ✅ `wcu_service` |

One permanently-False term in an AND-chain makes the whole chain permanently False. **No plan, for
any user, can ever advance on merit** — only by elapsed time. The repo's own test documents this:
it must zero every requirement to make the gate pass, and its sibling comments *"the other default
thresholds (revenue 100k, books 3, platform, studio) unmet, it holds at 1."*

The Plans doc explains why the progress half was never fed: it defines **no update route**, renders
a progress panel, and says plainly — **"This is just the read view."** The write half was never
designed.

### The live demonstration

Plan 4 — a **freelance consulting** plan — was created with:

```
duration_years: 3        ← from the AI ✅
posture: Accelerated     ← from ambition_score ✅
wcu_target:     3000     ← publishing default ❌
books_required:    3     ← publishing default ❌
```

The AI inferred `core_domains: [{name: "consulting"}]` and wrote three specific criteria —
*"Secure 3 clients with 3k/month retainers within the first year"* — and the resulting plan
requires publishing three books. **The AI's output sits inert in `structure_json` while the physics
engine reads the owner's defaults.**

---

## 6. Where the AI's output goes

Of 11 synthesis fields, 4 are consumed:

| Field | Consumer |
|---|---|
| `time_horizon_years` | → `duration_years`, `target_date` ✅ |
| `ambition_score` | → `posture.py` classification ✅ |
| `vision_statement` | → memory capture ✅ |
| `phases` | → executable tasks w/ dependencies ✅ |
| **`core_domains`** | **nothing** |
| **`success_criteria`** | **nothing** |
| `primary_mechanism` | nothing |
| `risk_factors` | nothing |
| `key_assets` | nothing |

The two dropped fields that matter are `core_domains` and `success_criteria` — *the Domain
abstraction, generated fresh on every synthesis, with no consumer.*

**Gap:** `core_domains` is shaped `{name, intent}` — descriptive, not measurable. The doc's
`Domain` needed `threshold_type` + `target_value`. That is a **prompt change**, not an architecture
change; the AI is already doing the hard part.

---

## 7. Genesis as a conversational surface

It is a **funnel, not a partner** — by construction:

- Hard **2–4 line** reply cap in the system prompt.
- Every turn **must** return `state_update` JSON — each message is processed as signal extraction.
- Only **six slots** exist; anything that doesn't fit is discarded.
- **No conversation transcript.** Each call sends only the system prompt and
  `{current_state} + {new message}`.

**The inversion:** it has long-term memory (writes a memory node per turn, recalls semantically)
but **no short-term memory** — it may surface something from weeks ago but cannot recall what you
said two messages back.

It also **never signals readiness.** In the live run, `synthesis_ready` stayed `False` through four
substantive turns and only flipped when the user typed *"I'm ready to lock this in."* A user
answering its questions in good faith will loop forever. **This alone explains the owner's report
that Genesis "never got around to creating the actual plan."**

There is no surface anywhere for open strategic conversation — `/assistant`'s other mode is
`POST /apps/agent/run {goal}`, one-shot execution. Both AI entry points are funnels into a specific
artifact.

---

## 8. Defects found (independent of any redesign decision)

| # | Defect | Severity |
|---|---|---|
| 1 | `GET /apps/masterplans/{id}` → **500** — `Completion finalization failed: Required system event 'execution.completed' failed`. Runtime pipeline, not masterplan logic. | **blocks the detail view entirely** |
| 2 | `POST /genesis/lock` requires `draft` in the body, but the service prefers `session.draft_json`. Route rejects requests its own service could serve. | high |
| 3 | That 400 is raised **before pipeline entry**, tripping `RouteExecutionViolation` → rewritten as opaque **500**. Real reason never reaches the caller. | high — makes #2 undiagnosable |
| 4 | `evaluate_phase` is **triplicated byte-identical** (`projection_service.py:39`, `services/__init__.py:39`, `__init__.py:39`); only one is imported. | low |
| 5 | `apps/masterplan/schemas/masterplan.py::MasterPlanInput` — second, entirely unreferenced copy. | low |
| 6 | No import/upload path. Genesis conversation is the only way in; anyone with an existing plan must re-derive it by talking to the AI. | design gap |

Fixed this session (#172): `/apps/compute/create_masterplan` 500'd unconditionally and the compute
routes serialized to `{}`.

---

## 9. Options

Not decisions — framing. Ordered by cost.

### Option 1 — Surface what already exists
Fix defect #1, widen the list/detail payloads, render `structure_json` (vision, domains, phases,
criteria) and the projection data already computed. **No model changes.** Turns a 6-scalar screen
into a real plan view. Highest ratio of visible change to risk.

### Option 2 — Connect the AI's output to the physics
Extend the synthesis prompt to emit measurable domains (`threshold_type`, `target_value`), have the
factory persist them, and rewrite `evaluate_phase` to read them instead of books/studio/playbooks.
**This is the doc's Option B, ~80% pre-built.** Retires the hardcoded block by replacement.

### Option 3 — Build Layer 2
The editable config view the doc specified and nobody built: after synthesis, show the structured
breakdown and let the user refine targets and toggle domains. **The actual cure for "too tailored
to me"** — without it, a user can never change what their plan measures.

### Option 4 — Reconsider Genesis as a surface
Pass conversation history (cheap), and decide whether readiness should be system-proposed rather
than user-declared. Separately: whether an open strategic-conversation surface should exist at all,
or whether every AI entry point should remain a funnel.

### Option 5 — Import / upload
No route exists. Independent of the above and unblocks anyone who already has a plan.

---

## 10. Open questions for the owner

1. Do `books` / `studio` / `playbooks` / `platform` still describe real goals, or are they
   vestigial? Determines whether Option 2 is replacement or deletion.
2. Should phase progression mean **work volume** (WCU), **declared goals** (anchor / Goal), or
   **schedule**? Today it is effectively schedule-only.
3. Is Genesis meant to be a reflective partner or an efficient funnel? The build doc's language
   (*"Let's discover your destiny architecture"*) implies partner; the implementation is a funnel.
4. Should `Goal`/`GoalState` become plan physics, or stay an autonomy-layer concern? It is
   currently unexercised (0 rows), so it may warrant its own scope look first.

---

## 11. Test artifacts left in place

- **Genesis session 1** — locked, carries a real 11-field draft.
- **Plan 4** — first plan in the system, active, `posture: Accelerated`.
- **Tasks 9/10/11** — derived from the AI's phases, dependency-chained.

Left deliberately so `/masterplan` renders something real. Safe to delete; nothing depends on them.
