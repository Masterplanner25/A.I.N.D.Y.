"""Objectives, phases and strategies — the layer flattened into `tasks`.

`STRATEGY_LAYER_SPEC.md`. The owner's three-layer model:

> MasterPlan + goals → strategies (temporary, executable, failable, learnable, refinable) → tasks

The layer already existed; it was just stored as tasks. On the live plan, "tasks" 12–16 are the
five Genesis phases wearing task rows — never actionable, never completable, and permanently
`pending`. §3 of the spec is that ambiguity; this module is the shape that removes it.

★ **Two axes, not one chain.** Genesis already emits both, separately:

```
MasterPlan
  ├── Objective   "what must become true"   ← core_domains (3)
  │     └── Strategy   "how we're trying"   ← temporary, failable
  │           └── Task
  └── Phase       "when"                    ← phases (5 x 12mo)
          ↑
          └─ a Strategy is SCHEDULED INTO a phase; it is OWNED by an objective
```

A strategy carries two references with different meanings. `objective_id` is **ownership** —
changing it changes what the strategy is for, and is rare. `phase_id` is **scheduling** —
changing it is ordinary replanning, and is exactly a *refine* under
`MASTERPLAN_REFINE_VS_REVISE_SPEC`. That distinction is what makes the owner's *"some things
move phases"* a cheap operation rather than a plan rewrite.

Nothing reads these tables yet. §8 is explicit that it must not until the six live rows have
moved, or the plan would briefly have five phases in one table and five phases-as-tasks in
another — which is the condition the spec is complaining about, added to rather than removed.
"""

import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from AINDY.db.database import Base

# ── Strategy vocabulary ───────────────────────────────────────────────────────────────
#
# ★ `abandoned` and `displaced` must not be collapsed, and this is the load-bearing
# distinction of the whole layer. "We tried publishing and it did not move the objective" and
# "we never published because we did the partnership instead" are different pieces of
# evidence, and a success rate computed over a set that mixes them is meaningless.
STRATEGY_PROPOSED = "proposed"
STRATEGY_ACTIVE = "active"
STRATEGY_CONCLUDED = "concluded"
STRATEGY_ABANDONED = "abandoned"      # tried it, it did not work        — a RESULT
STRATEGY_DISPLACED = "displaced"      # never tried; did something else  — a CHOICE
VALID_STRATEGY_STATUSES = {
    STRATEGY_PROPOSED,
    STRATEGY_ACTIVE,
    STRATEGY_CONCLUDED,
    STRATEGY_ABANDONED,
    STRATEGY_DISPLACED,
}

# ★ Judged, never measured. A declared target would be a second measurement surface competing
# with `goal_states`, and it is the one most likely to be filled in mechanically — the same
# failure the worth-declaration spec is built around. A strategy's measurable side is
# INHERITED: WCU rolls up through it to the objective (§5b).
OUTCOME_WORKED = "worked"
OUTCOME_DID_NOT_WORK = "did_not_work"
OUTCOME_INCONCLUSIVE = "inconclusive"
VALID_STRATEGY_OUTCOMES = {OUTCOME_WORKED, OUTCOME_DID_NOT_WORK, OUTCOME_INCONCLUSIVE}

# Where a strategy came from. `emergent` exists because the most informative thing that can
# happen — you did something the plan never anticipated, and it worked — currently leaves no
# trace anywhere (§5).
ORIGIN_PLANNED = "planned"
ORIGIN_EMERGENT = "emergent"
VALID_STRATEGY_ORIGINS = {ORIGIN_PLANNED, ORIGIN_EMERGENT}

PHASE_PENDING = "pending"
PHASE_ACTIVE = "active"
PHASE_COMPLETE = "complete"
VALID_PHASE_STATUSES = {PHASE_PENDING, PHASE_ACTIVE, PHASE_COMPLETE}


class PlanObjective(Base):
    """What must become true. Genesis-authored, plan-scoped.

    Seeded from `structure_json["core_domains"]`, which are objectives in everything but name —
    *"Ethical AI Framework — to establish guidelines and standards for ethical AI development"* —
    and are currently rendered only as read-only text in `GenesisDraftPreview.jsx`.

    Distinct from `goals`, deliberately (§6 Q1). A goal is user-scoped and outlives plan
    versions; an objective belongs to one plan and is what attribution rolls up to. They are the
    same statement at different grain, and collapsing them was the collision Q1 resolved.
    """

    __tablename__ = "plan_objectives"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    masterplan_id = Column(Integer, ForeignKey("master_plans.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    name = Column(String(300), nullable=False)
    intent = Column(Text, nullable=True)
    ordinal = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<PlanObjective(name={self.name!r})>"


class PlanPhase(Base):
    """When. A time-boxed segment of the arc, a tier above strategies.

    Owner, 2026-09-05: *"Execution of a strategy may change what phase you're in or what's
    required of a phase, but overall it should be above a strategy."*

    ★ `depends_on_phase_id` is not decoration. The five live phases carry a hard dependency
    chain 12→13→14→15→16 as tasks, and it feeds `eta_service._scope_plan_from_graph` →
    `critical_depth`, which sets a **sequential floor** on the plan's ETA. Drop the chain and
    `critical_depth` collapses to 1, the floor vanishes, and the plan projects as though all
    five phases could run at once. The order is load-bearing, so it is carried as an explicit
    edge rather than inferred from `ordinal` alone (§8).
    """

    __tablename__ = "plan_phases"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    masterplan_id = Column(Integer, ForeignKey("master_plans.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    ordinal = Column(Integer, nullable=False, default=0)
    duration_months = Column(Integer, nullable=True)

    status = Column(String(16), nullable=False, default=PHASE_PENDING, index=True)
    depends_on_phase_id = Column(String, ForeignKey("plan_phases.id"), nullable=True, index=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<PlanPhase(ordinal={self.ordinal}, name={self.name!r})>"


class PlanStrategy(Base):
    """How we are trying. Temporary, executable, failable, learnable, refinable.

    ★ "Failable" is the load-bearing word (§4). A task that is not done is *incomplete*; a
    strategy that did not work is *finished, with a result*. Without a layer that can fail, an
    approach that stopped working looks exactly like an approach nobody got round to.
    """

    __tablename__ = "plan_strategies"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    masterplan_id = Column(Integer, ForeignKey("master_plans.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)

    # Ownership. Changing it changes what the strategy is FOR, and is rare. Nullable because an
    # emergent strategy may have no home objective yet — and that case is the single most
    # informative signal the layer produces: it is what a *revise* is derived from (§5).
    objective_id = Column(
        String, ForeignKey("plan_objectives.id"), nullable=True, index=True
    )
    # Scheduling. Changing it is ordinary replanning — a refine, not a rewrite.
    phase_id = Column(String, ForeignKey("plan_phases.id"), nullable=True, index=True)

    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)

    origin = Column(String(16), nullable=False, default=ORIGIN_PLANNED, index=True)
    status = Column(String(32), nullable=False, default=STRATEGY_PROPOSED, index=True)

    # Set when the strategy concludes. NULL for a displaced one, permanently and on purpose:
    # it was never tried, so there is nothing to judge, and inventing a verdict for it is what
    # would make the success rate meaningless.
    outcome = Column(String(16), nullable=True, index=True)
    outcome_note = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    concluded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<PlanStrategy(name={self.name!r}, status={self.status}, origin={self.origin})>"
