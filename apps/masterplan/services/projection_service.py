from datetime import datetime, timedelta, timezone
import numpy as np

# 🔥 Add a scaling constant at the top
COMPRESSION_DIVISOR = 100  # Start here, calibrate later

def project_completion(masterplan, twr_values):
    if not twr_values:
        return None

    twr_array = np.array(twr_values)

    conservative = np.percentile(twr_array, 30)
    aggressive = np.percentile(twr_array, 70)
    optimal = np.max(twr_array)

    today = datetime.now(timezone.utc)
    remaining_days = (masterplan.target_date - today).days

    def projected_eta(rate):
        if rate <= 0:
            return masterplan.target_date

        # 🔥 Normalize TWR before using it as compression factor
        effective_rate = rate / COMPRESSION_DIVISOR

        if effective_rate <= 0:
            return masterplan.target_date

        adjusted_days = remaining_days / effective_rate
        return today + timedelta(days=adjusted_days)

    return {
        "conservative_eta": projected_eta(conservative),
        "aggressive_eta": projected_eta(aggressive),
        "optimal_eta": projected_eta(optimal)
    }

def _as_naive_utc(value):
    """Fold a timestamp to naive UTC so it can be compared with the plan's columns.

    ``MasterPlan.start_date`` is a naive ``DateTime`` column, so ``phase_end`` is naive
    while ``datetime.now(timezone.utc)`` is aware. Comparing them raised
    ``TypeError: can't compare offset-naive and offset-aware datetimes`` — and because
    the threshold branch below never returned early, that comparison was on the *normal*
    path. ``wcu_service`` catches the exception and logs a warning, so the phase silently
    never advanced and no error ever surfaced.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _requirement_met(actual, required) -> bool:
    """A numeric requirement gates only when one has been set.

    Requirements default to non-zero (revenue_target 100000, books_required 3,
    playbooks_required 2) while the matching progress columns default to 0 and have no
    writer anywhere in the repo — five of the six terms were therefore permanently
    False, so `thresholds_met` could never be true for any plan. Treating an unset
    requirement as "not applicable" makes the gate satisfiable without inventing five
    writers, and keeps it honest for the dimensions that *are* fed: `total_wcu` is
    written by wcu_service, so a plan that sets a WCU target is now genuinely gated on it.
    """
    if not required:  # 0 / None — nothing declared, so nothing to satisfy
        return True
    return (actual or 0) >= required


def _flag_met(required: bool, achieved: bool) -> bool:
    """A boolean requirement gates only when it is explicitly required."""
    return (not required) or bool(achieved)


def evaluate_phase(plan):
    phase_end = _as_naive_utc(plan.start_date + timedelta(days=plan.duration_years * 365))
    now = _as_naive_utc(datetime.now(timezone.utc))

    thresholds_met = (
        _requirement_met(plan.total_wcu, plan.wcu_target)
        and _requirement_met(plan.gross_revenue, plan.revenue_target)
        and _requirement_met(plan.books_published, plan.books_required)
        and _flag_met(plan.platform_required, plan.platform_live)
        and _flag_met(plan.studio_required, plan.studio_ready)
        and _requirement_met(plan.active_playbooks, plan.playbooks_required)
    )

    if thresholds_met:
        return 2

    if phase_end is not None and now >= phase_end:
        return 2

    return 1
