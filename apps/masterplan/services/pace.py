"""Pace — the plan's ETA drift, read against its posture, and what the system proposes about it.

`BUILD_PLAN` carried *"Risk posture & ETA drift — still sensed, not actuated"*: `posture` was set
at plan lock and only ever displayed, `days_ahead_behind` was recalculated daily by `eta_service`
and only ever stored. Nothing consumed either. This module is the consumer, and it actuates the
only way this repo lets a system actuate a plan: **it proposes, and the human confirms — or
declines** (`phase_advance.py` is the template; `STRATEGY_LAYER_SPEC` §6 Q8 the rule).

Two ideas, and the seam between them:

- **Posture is the declared appetite.** Aggressive / Accelerated / Stable / Reduced are what the
  plan said about itself at lock. Here that declaration becomes a *tolerance*: how far the
  projected completion may drift from `target_date` before drift is worth a conversation. An
  Aggressive plan that is a week behind has something to talk about; a Reduced plan a month
  behind does not.
- **Drift is what the ETA machinery already measures.** `days_ahead_behind` (positive = ahead)
  with an `eta_confidence`. A projection with low or insufficient confidence proposes nothing —
  a proposal built on noise is noise with a button on it — but the evidence is still returned so
  the panel can say "pace unknown" instead of nothing.

What the human can confirm (owner's call, 2026-09-16): **`retarget`** — move `target_date` to
the projected completion, a *refine* (it changes *when*, not *what*; `MASTERPLAN_REFINE_VS_REVISE_
SPEC` §2), and the ETA is recomputed at once so the plan agrees with itself — or **dismiss**,
which records the drift the proposal was built on and stays quiet until drift moves by more than
the tolerance again. Re-posturing is *named* in the evidence when the pace implies a different
appetite, but not offered as a button: changing the plan's declared appetite is revise-class and
`/revise` does not exist yet.

Nothing here re-sequences tasks or writes anything without a confirmation. That is the design,
not a gap.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.masterplan.masterplan import MasterPlan

logger = logging.getLogger(__name__)

# ── posture → tolerance ──────────────────────────────────────────────────────────────────────────
#
# (share of the remaining horizon, floor in days). The share keeps a five-year Stable plan from
# nagging over a fortnight; the floor keeps a plan in its last month from being nagged daily.
TOLERANCE_BY_POSTURE: dict[str, tuple[float, int]] = {
    "Aggressive": (0.05, 7),
    "Accelerated": (0.10, 14),
    "Stable": (0.20, 30),
    "Reduced": (0.35, 45),
}
_DEFAULT_TOLERANCE = TOLERANCE_BY_POSTURE["Stable"]

# The ordering used to name the appetite a pace implies (see `_implied_posture`).
_POSTURE_ORDER = ["Reduced", "Stable", "Accelerated", "Aggressive"]

CONFIDENT = {"high", "medium"}

DIRECTION_BEHIND = "behind"
DIRECTION_AHEAD = "ahead"

DECISION_RETARGET = "retarget"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def pace_tolerance_days(posture: str | None, remaining_days: int) -> int:
    """How many days of drift this posture tolerates before the system speaks."""
    share, floor = TOLERANCE_BY_POSTURE.get(str(posture or ""), _DEFAULT_TOLERANCE)
    return max(int(floor), int(round(max(remaining_days, 0) * share)))


def _implied_posture(posture: str | None, direction: str) -> str | None:
    """The neighbouring appetite the pace points at — named, not applied."""
    try:
        i = _POSTURE_ORDER.index(str(posture))
    except ValueError:
        return None
    j = i - 1 if direction == DIRECTION_BEHIND else i + 1
    if 0 <= j < len(_POSTURE_ORDER):
        return _POSTURE_ORDER[j]
    return None


# ── evidence ─────────────────────────────────────────────────────────────────────────────────────

def pace_evidence(plan: MasterPlan, *, now: datetime | None = None) -> dict[str, Any]:
    """Everything the proposal is built from, in one dict. Reads only."""
    moment = now or _now()
    target = _as_aware(plan.target_date)
    remaining_days = int((target - moment).days) if target is not None else 0
    drift = plan.days_ahead_behind
    confidence = plan.eta_confidence or "insufficient_data"
    tolerance = pace_tolerance_days(plan.posture, remaining_days)

    direction = None
    if drift is not None and drift < 0:
        direction = DIRECTION_BEHIND
    elif drift is not None and drift > 0:
        direction = DIRECTION_AHEAD

    exceeds = drift is not None and abs(int(drift)) > tolerance
    return {
        "posture": plan.posture,
        "tolerance_days": tolerance,
        "days_ahead_behind": drift,
        "direction": direction,
        "exceeds_tolerance": bool(exceeds),
        "eta_confidence": confidence,
        "confident": confidence in CONFIDENT,
        "target_date": _iso(target),
        "projected_completion_date": _iso(plan.projected_completion_date),
        "remaining_days": remaining_days,
        "velocity": plan.current_velocity,
        "eta_last_calculated": _iso(plan.eta_last_calculated),
        "implied_posture": _implied_posture(plan.posture, direction) if direction else None,
    }


# ── propose ──────────────────────────────────────────────────────────────────────────────────────

def propose_pace_review(
    db: Session, *, masterplan_id: int, user_id: Any, now: datetime | None = None
) -> dict[str, Any]:
    """What the system has to say about the plan's pace. Writes nothing.

    `proposed` is the only key a caller has to read. When true, `direction` says which way the
    drift runs and `options` lists what confirming can do, each with its consequence computed.
    """
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        return {"proposed": False, "reason": "plan_not_found"}

    evidence = pace_evidence(plan, now=now)
    payload: dict[str, Any] = {
        "proposed": False,
        "direction": evidence["direction"],
        "evidence": evidence,
        "options": [],
        "dismissed": None,
    }

    if evidence["days_ahead_behind"] is None or evidence["eta_confidence"] == "insufficient_data":
        payload["reason"] = "no_projection"
        return payload
    if not evidence["confident"]:
        payload["reason"] = "low_confidence"
        return payload
    if not evidence["exceeds_tolerance"]:
        payload["reason"] = "within_tolerance"
        return payload

    payload["reason"] = f"{evidence['direction']}_beyond_tolerance"

    # ★ The human already looked at this drift and said "noted". Re-proposing on the same
    # number is nagging. When the drift moves by more than the tolerance from what was
    # dismissed, it is a different question and gets asked again.
    if _dismissal_stands(plan, evidence):
        payload["dismissed"] = {
            "at": _iso(plan.pace_dismissed_at),
            "days_ahead_behind": plan.pace_dismissed_days,
        }
        return payload

    payload["options"] = _options(plan, evidence)
    payload["proposed"] = True
    return payload


def _options(plan: MasterPlan, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    if plan.projected_completion_date is not None:
        options.append(
            {
                "decision": DECISION_RETARGET,
                "kind": "refine",
                "label": "Move the target date to the projected completion",
                "consequence": {
                    "target_date_from": evidence["target_date"],
                    "target_date_to": _iso(plan.projected_completion_date),
                    "days": evidence["days_ahead_behind"],
                },
            }
        )
    if evidence.get("implied_posture"):
        options.append(
            {
                "decision": None,  # named, not confirmable: revise-class, and /revise is not built
                "kind": "revise",
                "label": f"The pace reads more like {evidence['implied_posture']} than {plan.posture}",
                "consequence": None,
            }
        )
    return options


def _dismissal_stands(plan: MasterPlan, evidence: dict[str, Any]) -> bool:
    if plan.pace_dismissed_at is None or plan.pace_dismissed_days is None:
        return False
    moved = abs(int(evidence["days_ahead_behind"]) - int(plan.pace_dismissed_days))
    return moved <= int(evidence["tolerance_days"])


# ── decline ──────────────────────────────────────────────────────────────────────────────────────

def dismiss_pace_review(db: Session, *, masterplan_id: int, user_id: Any) -> dict[str, Any]:
    """"Noted." Records the drift the proposal was built on; it returns when drift moves by more
    than the tolerance. Refuses when nothing is proposed — there has to be something to decline."""
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        raise ValueError(f"MasterPlan {masterplan_id} not found")
    evidence = pace_evidence(plan)
    if not (evidence["confident"] and evidence["exceeds_tolerance"]):
        raise ValueError("nothing proposes a pace review; there is nothing to decline")

    plan.pace_dismissed_at = _now()
    plan.pace_dismissed_days = int(evidence["days_ahead_behind"])
    db.commit()
    db.refresh(plan)
    return {
        "dismissed": {"at": _iso(plan.pace_dismissed_at), "days_ahead_behind": plan.pace_dismissed_days},
        "returns_when": f"drift moves by more than {evidence['tolerance_days']} days from {plan.pace_dismissed_days}",
    }


# ── confirm ──────────────────────────────────────────────────────────────────────────────────────

def confirm_pace_review(
    db: Session, *, masterplan_id: int, user_id: Any, decision: str
) -> dict[str, Any]:
    """The human's half. `retarget` moves `target_date` to the projected completion (a refine),
    clears any dismissal, and recomputes the ETA so the plan agrees with itself at once."""
    plan = db.query(MasterPlan).filter(MasterPlan.id == int(masterplan_id)).first()
    if plan is None:
        raise ValueError(f"MasterPlan {masterplan_id} not found")
    proposal = propose_pace_review(db, masterplan_id=plan.id, user_id=user_id)
    if not proposal["proposed"]:
        raise ValueError(f"nothing is proposed about the pace ({proposal.get('reason')}); nothing to confirm")
    if decision != DECISION_RETARGET:
        raise ValueError(f"unknown decision {decision!r}; the confirmable decision is {DECISION_RETARGET!r}")
    if plan.projected_completion_date is None:
        raise ValueError("no projected completion date to retarget to")

    before = _as_aware(plan.target_date)
    projected = plan.projected_completion_date
    new_target = datetime(projected.year, projected.month, projected.day, tzinfo=timezone.utc)
    plan.target_date = new_target.replace(tzinfo=None) if before is not None and before.tzinfo is None else new_target
    plan.pace_dismissed_at = None
    plan.pace_dismissed_days = None
    db.commit()
    db.refresh(plan)

    # Recompute now rather than waiting for the daily job: `days_ahead_behind` is measured
    # against the target that just moved, and a panel that still shows the old drift after the
    # human accepted it would look like the confirmation did nothing.
    eta: dict[str, Any] | None = None
    try:
        from apps.masterplan.services.eta_service import calculate_eta

        eta = calculate_eta(db, plan.id, str(user_id or plan.user_id))
    except Exception as exc:  # the retarget stands either way; the daily job will catch up
        logger.warning("[pace] ETA recompute after retarget skipped: %s", exc)

    return {
        "decision": DECISION_RETARGET,
        "kind": "refine",
        "target_date_from": _iso(before),
        "target_date_to": _iso(_as_aware(plan.target_date)),
        "eta": eta,
        "proposal": propose_pace_review(db, masterplan_id=plan.id, user_id=user_id),
    }
