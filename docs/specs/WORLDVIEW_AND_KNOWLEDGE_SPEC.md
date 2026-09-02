---
title: "Worldview and Knowledge — what the partner knows, and how it knows it"
last_verified: "2026-08-23"
api_version: "1.0"
status: draft
owner: "app-team"
---

# Worldview and Knowledge

**Origin:** an owner conversation. §2 is audited fact; the rest is proposal.

**Framing constraint, stated first because it changes the design.** A.I.N.D.Y. is a *persistent
execution partner*, not an assistant. The prevailing "what your assistant knows" architecture
collapses everything into chat history, profile facts, preferences and connected documents. That is
one slice, and it is the wrong shape for a partner that acts. **Nothing in this spec should import
assistant vocabulary.**

The distinction that opens it:

- **Memory** answers *"what do I know about you?"*
- **Worldview** answers *"how have you come to understand the world?"*
- **Key positions** answer *"what have you figured out recently?"*

---

## 1. Five layers, deliberately not merged

| Layer | Holds | Example |
|---|---|---|
| **Personal context** | facts and preferences | "works this way", "uses these tools" |
| **Worldview** | durable positions, principles, heuristics, distinctions | *capability ≠ product*; *commitment creates responsibility* |
| **Key positions** | recent conclusions, some of which become worldview | *approval alone is not governance* |
| **Knowledge / work** | what has been researched, built, written, reasoned through | the MasterPlan, the specs, the CLI review corpus |
| **Active state** | current priorities, unresolved decisions, open questions | what `SESSION_HANDOFF.md` carries today |

Collapsing these is what produces "Shawn likes X, Shawn is working on Z" — true, and almost
useless to a partner that has to act.

---

## 2. What exists today — audited 2026-08-23

### 2.1 The evidence machinery is already built, and has never been used

`apps/identity` implements exactly the mechanism this needs, applied to *traits*:

| `IdentitySignal` column | role |
|---|---|
| `dimension` / `value` | the claim |
| `weight` | evidence strength of one observation |
| `event_type` | **provenance** (`arm_analysis_complete`, `masterplan_locked`, …) |
| `created_at` | recency, for decay |

`identity_inference_service` re-derives each dimension as a recency-decayed weighted vote:
`CONFIDENCE_THRESHOLD = 0.6`, `MIN_SUPPORT = 2.0`, `SWITCH_MARGIN = 0.15` (hysteresis so one
off-pattern event cannot churn the profile), 30-day half-life.

**That is provenance, confidence, support, decay and hysteresis — the exact properties a worldview
layer requires — already written, tested and shipped.**

**`identity_signals` currently holds 0 rows across 0 dimensions.** The machinery has never been
fed. This is the repo's most common defect shape (`RECURRING_DEFECT_PATTERNS.md` §5: built to spec,
one wire short of a surface).

**So worldview is not greenfield. It is the same evidence model over a different subject** —
positions instead of traits — and the honest first question is whether to generalise
`IdentitySignal` or copy its shape.

### 2.2 The word "insight" is already taken, by telemetry

`memory_nodes` holds **1,773 rows**:

| node_type | count | what it actually is |
|---|---|---|
| `insight` | **1,760** | `execution.started from genesis`, `Latency spike detected at 18472.16ms` |
| `outcome` | 12 | |
| `decision` | 2 | `Masterplan locked: V1 (posture: Accelerated…)` |

**99% of what this system calls an "insight" is runtime telemetry.** Reusing the word for the
user's positions would collide head-on, and `insight` also appears 60 times in `apps/` meaning
ARM code-analysis output and rippletrace trace insights. This spec uses **position** instead, and
any implementation must pick a distinct node type.

`worldview`, `belief` and `conviction` appear **0 times** in `apps/`.

### 2.3 Documents are already not knowledge — demonstrated today

MasterPlan V4 was imported on 2026-08-23 (Genesis session 7): **23,124 characters stored verbatim
as one transcript turn.** The system now holds the document. It does not hold:

> the objectives · the systems involved · which decisions are already made · which assumptions
> underpin them · which questions are unresolved · which component superseded an earlier approach ·
> which conversation caused that change

Genesis extracted `vision_summary` and `time_horizon` at confidence 0.6, and returned
`mechanism_summary: null`, `assets_summary: null`, `inferred_domains: []`, `inferred_phases: []`.

**That gap is this spec's clearest worked example**, and it is live rather than hypothetical.

---

## 3. States, because a worldview that cannot change becomes a caricature

A position is never simply true. It has a lifecycle:

`emerging → established → evolving → challenged → abandoned`

**Abandoned positions are retained, not deleted.** "You used to hold this and stopped" is
information about how someone thinks, and deleting it is how a model of a person turns into a
flattering fossil. Same reasoning as the refine spec's retained strategies, and as
`score_history` being append-only.

### Provenance is the feature, not the metadata

The useful surface is not *"you believe capability ≠ product"*. It is:

```
Capability ≠ Product
  first emerged   February 2026
  reinforced      17 conversations
  last developed  August 2026
  related         agents · tool access · authority · execution architecture
  trajectory      observation → architectural principle → product-design principle
```

…and then the ability to open the conversations where it developed.

### Inferred is not the same as known

Once a system represents positions rather than messages, **a wrong inference is far more
consequential than a wrong fact**. Three requirements follow, and they are not optional:

1. every position carries **provenance** — what evidence produced it;
2. every position carries **confidence**, and the surface shows it;
3. the person can **correct** it, and the correction outweighs inference.

`identity_inference_service` already models 1 and 2. It does not model 3.

---

## 4. Open decisions

1. **Generalise or copy?** Make `IdentitySignal` subject-agnostic, or add a parallel
   `PositionSignal`. Generalising risks entangling two things that may need to diverge; copying
   duplicates a tested mechanism.
2. **What produces a position?** Identity signals come from domain events. Positions plausibly come
   from conversation — which means an extraction step, which means a model deciding what someone
   believes. That is precisely where wrong inference is most costly, and it argues for
   proposed-then-confirmed rather than silent recording.
3. **Does this feed the algorithm?** Under this repo's sorting rule — *does it feed the score, the
   loop, or neither?* — worldview is most plausibly **loop**, not score. Nothing here should move a
   KPI, and saying so early prevents it being wired in by accident.
4. **Where does knowledge/work live?** MasterPlan, specs and research already exist as artifacts
   across domains. Whether "knowledge" is a new store or a projection over existing domains is
   unresolved, and the answer determines whether this is one surface or a view.
5. **First-class surface or part of Memory?** The owner's instinct is first-class. Worth noting
   `apps/memory`'s recall already returns telemetry rather than meaning, so building on it without
   fixing that inherits the problem.

---

## 5. Relationship to the refine spec

`MASTERPLAN_REFINE_VS_REVISE_SPEC` and this one are siblings, and it is the same idea applied twice:

- **Refine** — the *plan's* model evolves through execution.
- **Worldview** — the *person's* model evolves through work.

Both keep history rather than overwriting state, both distinguish "this changed" from "this was
replaced", and both are the Observe → Refine loop pointed at a different subject. The system
already applies that loop to a score. These apply it to the plan and to the thinking behind it.
