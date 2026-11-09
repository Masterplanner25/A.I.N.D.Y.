"""Decision engine — map a StateSnapshot to a normalized ReasoningResult.

This is the decision logic previously inlined as `infinity_loop._decide` plus its
weighting refiners (memory, system-state, goals, social), extracted verbatim so
behavior is preserved. The threshold/feedback branch order is unchanged; each
branch is refined by the same sequence of weighting passes.

Strategy-accuracy weighting is intentionally *not* here: it depends on a DB
lookup of prior adjustments and stays in the loop, applied after this engine
produces a base decision.
"""

from __future__ import annotations

from typing import Any

from AINDY.platform_layer.registry import get_job

from apps.analytics.services.reasoning.types import ReasoningResult, StateSnapshot


def _build_focus_suggestions(score_snapshot: dict) -> list[dict]:
    focus = float(score_snapshot.get("focus_quality", 50.0) or 50.0)
    return [
        {
            "tool": "memory.recall",
            "reason": f"Focus quality is low ({focus:.0f}/100) - recall relevant context before switching tasks.",
            "suggested_goal": "Recall recent context and notes before resuming the current workstream",
        },
        {
            "tool": "research.query",
            "reason": f"Focus quality is low ({focus:.0f}/100) - external context gathering can reduce restart friction.",
            "suggested_goal": "Research the current topic to rebuild momentum with a quick context refresh",
        },
    ]


def _build_ai_suggestions(score_snapshot: dict) -> list[dict]:
    ai_boost = float(score_snapshot.get("ai_productivity_boost", 50.0) or 50.0)
    return [
        {
            "tool": "arm.analyze",
            "reason": f"AI productivity boost is low ({ai_boost:.0f}/100) - use ARM to identify the highest-leverage next improvements.",
            "suggested_goal": "Analyze the current code or plan with ARM to identify the next highest-leverage improvement",
        }
    ]


def _summarize_memory_signals(memory_signals: list[dict] | None) -> dict:
    signals = memory_signals or []
    failures = [signal for signal in signals if signal.get("type") == "failure"]
    successes = [signal for signal in signals if signal.get("type") == "success"]
    patterns = [signal for signal in signals if signal.get("type") == "pattern"]
    failure_weight = round(sum(float(signal.get("weighted_score", 0.0) or 0.0) for signal in failures), 4)
    success_weight = round(sum(float(signal.get("weighted_score", 0.0) or 0.0) for signal in successes), 4)
    pattern_weight = round(sum(float(signal.get("weighted_score", 0.0) or 0.0) for signal in patterns), 4)
    return {
        "failures": failures[:3],
        "successes": successes[:3],
        "patterns": patterns[:3],
        "failure_weight": failure_weight,
        "success_weight": success_weight,
        "pattern_weight": pattern_weight,
    }


def _apply_memory_weighting(
    decision_type: str,
    payload: dict,
    memory_signals: list[dict] | None = None,
) -> tuple[str, dict]:
    summary = _summarize_memory_signals(memory_signals)
    adjusted_payload = {
        **payload,
        "memory_signals": memory_signals or [],
        "memory_summary": summary,
    }

    failure_weight = summary["failure_weight"]
    success_weight = summary["success_weight"]
    pattern_weight = summary["pattern_weight"]

    if failure_weight >= max(0.75, success_weight):
        adjusted_payload["memory_adjustment"] = {
            "reason": "high_impact_failures_detected",
            "top_failures": summary["failures"],
        }
        adjusted_payload["next_action"] = {
            "type": "review_plan",
            "title": "Review current plan against recent failure patterns",
            "suggested_goal": "Avoid repeating recent high-impact failures and choose an adjusted path",
        }
        return "review_plan", adjusted_payload

    if decision_type == "continue_highest_priority_task" and success_weight > failure_weight:
        top_success = summary["successes"][0] if summary["successes"] else None
        adjusted_payload["memory_adjustment"] = {
            "reason": "successful_trajectory_detected",
            "top_success": top_success,
        }
        adjusted_payload["next_action"] = {
            **(adjusted_payload.get("next_action") or {}),
            "memory_weighted_adjustment": "boost_successful_pattern",
            "successful_pattern": top_success,
        }
        return decision_type, adjusted_payload

    if pattern_weight >= 0.9 and decision_type == "reprioritize_tasks":
        top_pattern = summary["patterns"][0] if summary["patterns"] else None
        adjusted_payload["memory_adjustment"] = {
            "reason": "high_impact_pattern_detected",
            "top_pattern": top_pattern,
        }
        adjusted_payload["next_action"] = {
            "type": "review_plan",
            "title": "Review task plan around a recurring high-impact pattern",
            "suggested_goal": "Adjust the current path using the strongest recurring memory pattern",
            "pattern": top_pattern,
        }
        return "review_plan", adjusted_payload

    adjusted_payload["memory_adjustment"] = {
        "reason": "memory_signals_applied",
        "failure_weight": failure_weight,
        "success_weight": success_weight,
        "pattern_weight": pattern_weight,
    }
    return decision_type, adjusted_payload


def _apply_system_state_weighting(
    decision_type: str,
    payload: dict,
    system_state: dict | None = None,
) -> tuple[str, dict]:
    state = system_state or {}
    health_status = str(state.get("health_status") or "healthy").lower()
    failure_rate = float(state.get("failure_rate", 0.0) or 0.0)
    system_load = float(state.get("system_load", 0.0) or 0.0)

    adjusted_payload = {
        **payload,
        "system_state": state,
    }

    if health_status == "critical":
        adjusted_payload["system_adjustment"] = {
            "reason": "critical_system_health",
            "failure_rate": failure_rate,
            "system_load": system_load,
        }
        adjusted_payload["next_action"] = {
            "type": "review_plan",
            "title": "Review current plan under critical system conditions",
            "suggested_goal": "Choose a safe, low-risk action until failures and load stabilize",
            "safe_mode": True,
        }
        return "review_plan", adjusted_payload

    if failure_rate >= 0.20 and decision_type == "continue_highest_priority_task":
        adjusted_payload["system_adjustment"] = {
            "reason": "elevated_failure_rate",
            "failure_rate": failure_rate,
        }
        adjusted_payload["next_action"] = {
            "type": "review_plan",
            "title": "Review the current path due to elevated failure rate",
            "suggested_goal": "Avoid repeating risky execution paths until failure rate improves",
        }
        return "review_plan", adjusted_payload

    if system_load >= 0.75:
        adjusted_payload["system_adjustment"] = {
            "reason": "high_system_load",
            "system_load": system_load,
        }
        next_action = dict(adjusted_payload.get("next_action") or {})
        next_action["load_adjustment"] = "reduce_heavy_execution"
        next_action["prefer_lightweight_actions"] = True
        if not next_action.get("title"):
            next_action["title"] = "Reduce heavy execution while system load is elevated"
        adjusted_payload["next_action"] = next_action
        return decision_type, adjusted_payload

    adjusted_payload["system_adjustment"] = {
        "reason": "system_state_applied",
        "health_status": health_status,
        "failure_rate": failure_rate,
        "system_load": system_load,
    }
    return decision_type, adjusted_payload


def _apply_goal_weighting(
    decision_type: str,
    payload: dict,
    goals: list[dict] | None = None,
) -> tuple[str, dict]:
    ranked_goals = goals or []
    if not ranked_goals:
        adjusted_payload = {**payload, "goal_summary": {"goal_count": 0, "goal_alignment": 0.0}}
        return decision_type, adjusted_payload
    calculate_goal_alignment = get_job("goals.calculate_alignment")
    if not callable(calculate_goal_alignment):
        adjusted_payload = {**payload, "goal_summary": {"goal_count": len(ranked_goals), "goal_alignment": 0.0}}
        return decision_type, adjusted_payload

    top_goal = ranked_goals[0]
    next_action = dict(payload.get("next_action") or {})
    alignment_text = " ".join(
        filter(
            None,
            [
                str(next_action.get("title") or ""),
                str(next_action.get("suggested_goal") or ""),
                str(next_action.get("task_name") or ""),
                str(payload.get("reason") or ""),
            ],
        )
    )
    goal_alignment = calculate_goal_alignment(ranked_goals, alignment_text)
    adjusted_payload = {
        **payload,
        "goal_summary": {
            "goal_count": len(ranked_goals),
            "goal_alignment": goal_alignment,
            "top_goal": {
                "id": top_goal.get("id"),
                "name": top_goal.get("name"),
                "ranked_priority": top_goal.get("ranked_priority"),
                "progress": top_goal.get("progress"),
            },
        },
    }

    if goal_alignment >= 0.25:
        next_action["goal_alignment"] = {
            "status": "aligned",
            "score": goal_alignment,
            "goal_id": top_goal.get("id"),
            "goal_name": top_goal.get("name"),
        }
        adjusted_payload["next_action"] = next_action
        return decision_type, adjusted_payload

    # Only a goal with a measure and a reading may override the next action (GOALS_LAYER_SPEC decision 4, 2026-11-09):
    # a declared goal could otherwise steer the loop on priority alone. A goal without the key is treated as measured,
    # the behaviour before the goals layer.
    if float(top_goal.get("ranked_priority") or 0.0) >= 0.70 and top_goal.get("measured", True):
        adjusted_payload["goal_adjustment"] = {
            "reason": "low_goal_alignment",
            "goal_id": top_goal.get("id"),
            "goal_name": top_goal.get("name"),
            "goal_alignment": goal_alignment,
        }
        adjusted_payload["next_action"] = {
            "type": "review_plan",
            "title": f"Realign work toward goal: {top_goal.get('name')}",
            "suggested_goal": top_goal.get("description") or top_goal.get("name"),
            "goal_id": top_goal.get("id"),
            "goal_alignment": {"status": "low_alignment", "score": goal_alignment},
        }
        return "review_plan", adjusted_payload

    next_action["goal_alignment"] = {"status": "weak_alignment", "score": goal_alignment}
    adjusted_payload["next_action"] = next_action
    return decision_type, adjusted_payload


def _apply_social_weighting(
    decision_type: str,
    payload: dict,
    social_signals: list[dict] | None = None,
) -> tuple[str, dict]:
    signals = list(social_signals or [])
    adjusted_payload = {**payload, "social_signals": signals}
    if not signals:
        return decision_type, adjusted_payload

    top_success = next((signal for signal in signals if signal.get("type") == "success"), None)
    top_failure = next((signal for signal in signals if signal.get("type") == "failure"), None)
    pattern = next((signal for signal in signals if signal.get("type") == "pattern"), None)

    if top_failure and float(top_failure.get("engagement_score", 0.0) or 0.0) <= 2.0:
        adjusted_payload["social_adjustment"] = {
            "reason": "low_social_performance",
            "signal": top_failure,
        }
        adjusted_payload["next_action"] = {
            "type": "review_plan",
            "title": "Review content strategy due to low social performance",
            "suggested_goal": "Adjust content direction before publishing more low-performing updates",
            "social_signal": top_failure,
        }
        return "review_plan", adjusted_payload

    if top_success:
        next_action = dict(adjusted_payload.get("next_action") or {})
        next_action["social_strategy"] = {
            "status": "boost_success_pattern",
            "content_hint": top_success.get("content"),
            "engagement_score": top_success.get("engagement_score"),
            "pattern": pattern,
        }
        adjusted_payload["next_action"] = next_action
        adjusted_payload["social_adjustment"] = {
            "reason": "high_social_performance",
            "signal": top_success,
            "pattern": pattern,
        }
    return decision_type, adjusted_payload


def _refine(decision_type: str, payload: dict, snapshot: StateSnapshot) -> tuple[str, dict]:
    """Run the shared weighting passes in their canonical order."""
    decision_type, payload = _apply_memory_weighting(decision_type, payload, snapshot.memory_signals)
    decision_type, payload = _apply_system_state_weighting(decision_type, payload, snapshot.system_state)
    decision_type, payload = _apply_goal_weighting(decision_type, payload, snapshot.goals)
    return _apply_social_weighting(decision_type, payload, snapshot.social_signals)


def decide(snapshot: StateSnapshot) -> ReasoningResult:
    """Map a normalized :class:`StateSnapshot` to a :class:`ReasoningResult`."""
    decision_type, payload = _decide_core(snapshot)
    return ReasoningResult(decision_type=decision_type, payload=payload)


def _decide_core(snapshot: StateSnapshot) -> tuple[str, dict]:
    score_snapshot = snapshot.score_snapshot
    feedback_context = snapshot.feedback_context or {}

    if feedback_context.get("negative", 0) > feedback_context.get("positive", 0):
        suggestions = _build_focus_suggestions(score_snapshot or {})
        payload = {
            "reason": "recent_negative_feedback",
            "suggestions": suggestions,
            "feedback_context": feedback_context,
            "suggested_goal": suggestions[0]["suggested_goal"],
            "next_action": {
                "type": "review_plan",
                "title": "Review current plan and recent feedback",
                "suggested_goal": suggestions[0]["suggested_goal"],
            },
        }
        return _refine("review_plan", payload, snapshot)

    if not score_snapshot:
        suggestions = _build_focus_suggestions({})
        payload = {
            "reason": "insufficient_data",
            "suggestions": suggestions,
            "suggested_goal": suggestions[0]["suggested_goal"],
            "next_action": {
                "type": "review_plan",
                "title": "Review current plan due to insufficient score data",
                "suggested_goal": suggestions[0]["suggested_goal"],
            },
        }
        return _refine("review_plan", payload, snapshot)

    try:
        execution_speed = float(score_snapshot.get("execution_speed", 50.0) or 50.0)
        decision_efficiency = float(score_snapshot.get("decision_efficiency", 50.0) or 50.0)
        focus_quality = float(score_snapshot.get("focus_quality", 50.0) or 50.0)
        ai_boost = float(score_snapshot.get("ai_productivity_boost", 50.0) or 50.0)
    except (TypeError, ValueError):
        suggestions = _build_focus_suggestions({})
        payload = {
            "reason": "invalid_snapshot",
            "suggestions": suggestions,
            "suggested_goal": suggestions[0]["suggested_goal"],
            "next_action": {
                "type": "review_plan",
                "title": "Review current plan due to invalid score snapshot",
                "suggested_goal": suggestions[0]["suggested_goal"],
            },
        }
        return _refine("review_plan", payload, snapshot)

    _low = snapshot.kpi_low or {}
    _exec_low = float(_low.get("execution_speed", 40.0))
    _dec_low = float(_low.get("decision_efficiency", 40.0))
    _focus_low = float(_low.get("focus_quality", 40.0))
    _ai_low = float(_low.get("ai_productivity_boost", 40.0))

    if execution_speed < _exec_low or decision_efficiency < _dec_low:
        payload = {
            "reason": "execution_or_decision_below_threshold",
            "thresholds": {
                "execution_speed": execution_speed,
                "decision_efficiency": decision_efficiency,
                "execution_speed_low": _exec_low,
                "decision_efficiency_low": _dec_low,
            },
            "next_action": {
                "type": "reprioritize_tasks",
                "title": "Reprioritize current tasks around execution bottlenecks",
            },
        }
        return _refine("reprioritize_tasks", payload, snapshot)
    if focus_quality < _focus_low:
        suggestions = _build_focus_suggestions(score_snapshot)
        payload = {
            "reason": "focus_below_threshold",
            "suggestions": suggestions,
            "suggested_goal": suggestions[0]["suggested_goal"],
            "next_action": {
                "type": "review_plan",
                "title": "Review plan and refresh context before continuing",
                "suggested_goal": suggestions[0]["suggested_goal"],
            },
        }
        return _refine("review_plan", payload, snapshot)
    if ai_boost < _ai_low:
        suggestions = _build_ai_suggestions(score_snapshot)
        payload = {
            "reason": "ai_productivity_below_threshold",
            "suggestions": suggestions,
            "suggested_goal": suggestions[0]["suggested_goal"],
            "next_action": {
                "type": "review_plan",
                "title": "Review plan and use ARM guidance before continuing",
                "suggested_goal": suggestions[0]["suggested_goal"],
            },
        }
        return _refine("review_plan", payload, snapshot)

    payload = {
        "reason": "kpis_stable",
        "next_action": {
            "type": "continue_highest_priority_task",
            "title": "Continue the highest-priority in-progress task",
        },
    }
    return _refine("continue_highest_priority_task", payload, snapshot)
