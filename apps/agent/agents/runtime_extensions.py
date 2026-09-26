"""Application-owned agent plugin implementations.

The runtime interacts with this module only through explicit runtime-owned
plugin contracts and registries. It never imports this module directly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


PLANNER_SYSTEM_PROMPT = """You are A.I.N.D.Y.'s strategic agent planner.

Given a user goal, produce a structured execution plan using only the available tools.

Risk rules:
- overall_risk = the highest risk_level of any step
- If ANY step is high risk, overall_risk must be "high"

Return ONLY valid JSON with exactly this structure:
{
  "executive_summary": "2-3 sentence summary of what the agent will do",
  "steps": [
    {
      "tool": "<tool_name>",
      "args": {<tool-specific args>},
      "risk_level": "low|medium|high",
      "description": "one sentence explaining this step"
    }
  ],
  "overall_risk": "low|medium|high"
}

Rules:
- Use only tools listed above
- Keep plans concise (3-7 steps maximum)
- Be specific in args - use realistic values based on the goal
- overall_risk must match the highest step risk_level
- Every step's args are written now, before any step runs: a step cannot read an earlier
  step's result. So never plan memory.write to save a "summary" or "findings" of earlier steps;
  it would save your guess, not the results. The system saves each run's real findings to memory
  when the run completes. memory.write is for content you can write now, e.g. from findings
  already given in the goal
- Return ONLY the JSON object, no markdown, no extra text
"""


def _build_kpi_context_block(user_id, db) -> str:
    try:
        from AINDY.platform_layer.registry import get_job

        get_user_kpi_snapshot = get_job("analytics.kpi_snapshot")
        if get_user_kpi_snapshot is None:
            return ""
        snapshot = get_user_kpi_snapshot(user_id=user_id, db=db)
        if not snapshot:
            return ""

        lines = [
            "",
            "## User Performance Context (Infinity Score)",
            f"Overall score: {snapshot['master_score']:.1f}/100 (confidence: {snapshot['confidence']})",
            f"- Execution speed:      {snapshot['execution_speed']:.1f}",
            f"- Decision efficiency:  {snapshot['decision_efficiency']:.1f}",
            f"- AI productivity:      {snapshot['ai_productivity_boost']:.1f}",
            f"- Focus quality:        {snapshot['focus_quality']:.1f}",
            f"- Masterplan progress:  {snapshot['masterplan_progress']:.1f}",
            "",
            "Scoring guidance:",
            # Owner, 2026-09-25: the first real goal ended in three task.create steps and the
            # run's own recalc took -8.64 — decision efficiency 68 -> 50, masterplan progress
            # 88 -> 70. Both are completed / (completed + pending + in_progress), so a created
            # task lowers them until it is done. The planner was never told.
            "- Pending tasks lower the score: decision efficiency and masterplan progress are "
            "completed tasks / all open and completed tasks, so every task created lowers both "
            "until it is completed",
        ]

        if snapshot["focus_quality"] < 40:
            lines.append("- Focus quality is low - prefer memory.recall and research.query over intensive tasks")
        if snapshot["execution_speed"] < 40:
            lines.append("- Execution speed is low - bias toward task.create to rebuild momentum")
        if snapshot["ai_productivity_boost"] < 40:
            lines.append("- ARM usage is low - consider arm.analyze to improve code quality")
        if snapshot["master_score"] >= 70:
            lines.append("- High overall score - medium-risk tools are appropriate given strong performance")

        return "\n".join(lines)
    except Exception:
        return ""


def _build_reasoning_context_block(user_id, db) -> str:
    """Append the autonomous-reasoning recommendation so plan generation is
    informed by reasoning outputs (ARM/Reasoning Phase 3). Decoupled via the job
    registry — no cross-app import. Best-effort."""
    try:
        from AINDY.platform_layer.registry import get_job

        recommend = get_job("analytics.reasoning_recommendation")
        if recommend is None:
            return ""
        recommendation = recommend(user_id=user_id, db=db)
        if not recommendation:
            return ""

        lines = [
            "",
            "## Reasoning Recommendation (Autonomous Reasoning)",
            f"Recommended next action: {recommendation.get('decision_type')}"
            f" (because: {recommendation.get('reason')})",
        ]
        title = recommendation.get("next_action_title")
        if title:
            lines.append(f"- {title}")
        suggested_goal = recommendation.get("suggested_goal")
        if suggested_goal:
            lines.append(f"- Suggested focus: {suggested_goal}")
        lines.append("Prefer plans aligned with this recommendation when the goal allows.")
        return "\n".join(lines)
    except Exception:
        return ""


def _build_date_line() -> str:
    """Today's date. The planner had no clock: on 2026-09-26 it gave five tasks due dates in June
    2025 (run `abf834d4`), fifteen months in the past."""
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    return f"\n\nToday's date: {today} (UTC). Any due_date must be on or after it.\n"


def _build_plan_context_block(user_id, db) -> str:
    """The user's active MasterPlan with its real IDs, so a plan can attach work to it.

    On 2026-09-26 the planner invented `strategy_id: "aindy-runtime-gtm"` for five `task.create`
    steps (run `abf834d4`): it planned a recall to find the ID, but a step cannot read an earlier
    step's result (FR-46) and no tool lists strategies. The IDs have to be here, before the plan is
    written. Read through the `masterplan.planning_context` job — no cross-app import.
    """
    try:
        from AINDY.platform_layer.registry import get_job

        planning_context = get_job("masterplan.planning_context")
        if planning_context is None:
            return ""
        plan = planning_context(user_id=user_id, db=db)
        if not plan:
            return ""

        lines = [
            "",
            "## User's MasterPlan (use these exact IDs; never invent one)",
            f"masterplan_id: {plan['masterplan_id']}",
        ]
        phase = plan.get("current_phase")
        if phase:
            lines.append(f"Current phase: {phase['name']} (phase_id: {phase['id']})")
        strategies = plan.get("strategies") or []
        if strategies:
            lines.append(
                "Open strategies. To attach a task to one, pass BOTH masterplan_id and "
                "strategy_id to task.create:"
            )
            for s in strategies:
                serves = f", serves {s['objective']}" if s.get("objective") else ""
                lines.append(
                    f"- {s['name']} (strategy_id: {s['id']}{serves}; "
                    f"{s['tasks_completed']}/{s['tasks_total']} tasks done)"
                )
        else:
            lines.append("No open strategies: create tasks with masterplan_id only.")
        return "\n".join(lines) + "\n"
    except Exception as exc:
        logger.warning("[planner_context] plan context skipped: %s", exc)
        return ""


def build_planner_context(context: dict) -> dict:
    """The planner's system prompt: base prompt + the user's Infinity context.

    The runtime routes this provider through the extension boundary
    (`registry.get_planner_context` -> `_sanitized_extension_input`), which strips `db` at the
    root BY DESIGN and redacts every non-primitive. So the context never carries a session, and
    this function opens its own — the same rule `handle_agent_run_completed` already lives by.

    AGENT-PLANNER-CONTEXT-BOUNDARY-1 (2026-09-17): until this fix the provider read `db` from
    the context (always None) and `user_id` as handed (a `uuid.UUID` upstream, so
    `{"_redacted_type": "UUID"}` here), and every block below took its `except: return ""`
    path — every plan since the boundary landed (2026-05-20) was made from the base prompt plus
    the tool catalog, blind to the score it exists to steer by. Runtime 2.22.0 (FR-39, #729)
    passes `user_id` as a string and documents `db` as absent by design, so the tenant arrives
    and the blocks build against our own session. A missing tenant is still logged rather than
    swallowed: that would be a runtime regression, and it should not be silent again.
    """
    run_type = context.get("run_type") or "default"
    user_id = _hook_user_id(context.get("user_id"))
    if not user_id:
        logger.warning(
            "[planner_context] no usable user_id in the hook context (got %r) — planning without "
            "the Infinity context; FR-39 shipped in runtime 2.22.0, so this is a regression",
            context.get("user_id"),
        )
        return {"system_prompt": PLANNER_SYSTEM_PROMPT, "context_block": ""}

    # An in-process caller may hand us a real session; the boundary never does.
    db = context.get("db")
    owns_session = db is None or isinstance(db, dict)
    if owns_session:
        from AINDY.db.database import SessionLocal

        db = SessionLocal()
    try:
        kpi_context = (
            _build_date_line()
            + _build_plan_context_block(user_id, db)
            + _build_kpi_context_block(user_id, db)
            + _build_reasoning_context_block(user_id, db)
        )
        prompt = PLANNER_SYSTEM_PROMPT + kpi_context
        try:
            from AINDY.memory.memory_helpers import enrich_context, format_memories_for_prompt

            memory_context = enrich_context({
                "db": db,
                "user_id": user_id,
                "node_name": "agent_planning",
                "agent_type": run_type,
            })
            prompt += format_memories_for_prompt(memory_context.get("memory_context") or [])
        except Exception as exc:
            logger.debug("agent planner memory context skipped: %s", exc)
        return {"system_prompt": prompt, "context_block": kpi_context}
    finally:
        if owns_session:
            db.close()


def get_tools_for_run(_context: dict) -> list[dict]:
    from AINDY.agents.tool_registry import TOOL_REGISTRY
    from AINDY.platform_layer.registry import load_plugins

    load_plugins()

    return [
        {
            "name": name,
            "risk": metadata.get("risk"),
            "description": metadata.get("description"),
            "capability": metadata.get("capability"),
            "required_capability": metadata.get("required_capability"),
            "category": metadata.get("category"),
            "egress_scope": metadata.get("egress_scope"),
            # FR-33 (runtime 2.20.0): the catalog renderer reads this key first and falls back
            # to the registry by name; carrying it keeps the provider's dicts self-describing.
            "args_schema": metadata.get("args_schema"),
        }
        for name, metadata in TOOL_REGISTRY.items()
    ]


# The Infinity loop emits 4 decision verbs. The runtime's Next-Action ledger
# (AINDY.core.next_action) records one canonical verb coerced from a completion
# hook's *return*. Map ours -> the runtime's, keyed on the loop's own dispatch
# intent (build_execution_intent: `review_plan` is manual/human-gated, the other
# three are loop-dispatched work), so NEXT_ACTION_CHOSEN reflects the app's real
# decision instead of the runtime default. Record-first: the runtime records the
# verb but takes no autonomous action.
_INFINITY_DECISION_TO_NEXT_ACTION = {
    "continue_highest_priority_task": "trigger_execution",
    "reprioritize_tasks": "trigger_execution",
    "create_new_task": "trigger_execution",
    "review_plan": "ask_user",
}

_NEXT_ACTION_ARG_KEYS = ("type", "title", "task_id", "task_name", "suggested_goal")


def _next_action_for_runtime(orchestration):
    """Coerce the Infinity orchestrator decision into a runtime NextAction.

    Returned to the runtime's completion-hook caller, which coerces it and records
    NEXT_ACTION_CHOSEN. This is separate from `run.result["next_action"]` (the rich
    dict the app's own consumers read) — it only shapes the runtime ledger entry.
    Returns None for a missing/unmapped decision, so the runtime keeps its default.
    """
    next_action = (orchestration or {}).get("next_action")
    if not isinstance(next_action, dict):
        return None
    decision_type = str(next_action.get("type") or "")
    verb = _INFINITY_DECISION_TO_NEXT_ACTION.get(decision_type)
    if verb is None:
        return None

    from AINDY.core.next_action import make_next_action

    return make_next_action(
        verb,
        reason=f"infinity:{decision_type}",
        args={k: next_action[k] for k in _NEXT_ACTION_ARG_KEYS if next_action.get(k) is not None},
        source="infinity_orchestrator",
    )


def _hook_user_id(value) -> str | None:
    """A usable tenant id, or None — a boundary-redacted `{"_redacted_type": ...}` is not one."""
    if value is None or isinstance(value, dict):
        return None
    text = str(value).strip()
    return text or None


def _save_run_findings(db, run, user_id: str) -> str | None:
    """Save what the run actually found as one memory node; return its id, or None.

    Owner, 2026-09-26: three runs in a row planned a `memory.write` "summary" of research that had
    not run yet (FR-46), and recall ranked those placeholders first. The planner is now told not
    to; this does what it was trying to do, from the steps' real results. Best-effort: a failure
    here must never stop the Infinity loop below it.
    """
    from AINDY.agents.tool_syscalls import invoke_tool_syscall
    from AINDY.db.models import AgentStep

    from apps.agent.services.run_findings import build_findings_digest, goal_ask

    rows = (
        db.query(AgentStep)
        .filter(AgentStep.run_id == run.id)
        .order_by(AgentStep.step_index.asc())
        .all()
    )
    digest = build_findings_digest(
        {"tool_name": r.tool_name, "status": r.status, "result": r.result} for r in rows
    )
    if not digest:
        return None
    ask = goal_ask(getattr(run, "goal", "")).strip()
    data = invoke_tool_syscall(
        "sys.v1.memory.write",
        {
            "content": f"Findings from an agent run: {ask}\n\n{digest}",
            "tags": ["agent_findings", f"agent_run:{run.id}"],
            "node_type": "insight",
            "source": "agent_findings",
        },
        user_id=user_id,
        capability="memory.write",
    )
    node = data.get("node") if isinstance(data, dict) else None
    return str(node.get("id")) if isinstance(node, dict) and node.get("id") else None


def handle_agent_run_completed(context: dict):
    """Enforce the Infinity loop after an agent run completes.

    The runtime routes completion hooks through the extension boundary, which
    strips the db/session and redacts the `run` ORM object — only primitive ids
    cross (INFINITY-COMPLETION-HOOK-BOUNDARY-1). So we take `run_id` from the
    context and re-fetch the run with our own session; aindy-runtime >=1.6.1
    supplies `run_id` and runs this hook in-process (it is not subprocess-isolated).

    Returns a runtime-coercible NextAction so the runtime records the app's real
    decision as NEXT_ACTION_CHOSEN; `None` means the runtime keeps its default.
    """
    run_id = context.get("run_id")
    if not run_id:
        return None

    from AINDY.db.database import SessionLocal
    from AINDY.db.models import AgentRun
    from AINDY.platform_layer.registry import get_job

    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if run is None:
            return None
        # AGENT-COMPLETION-HOOK-USERID-1 (2026-09-16): the tenant comes from the RE-FETCHED
        # RUN, not from the context. The runtime hands the hook `user_id` as a `uuid.UUID`
        # (`execution.py`: `"user_id": user_db_id`), and the same extension-boundary sanitizer
        # that strips `db` and redacts the ORM `run` redacts every non-primitive — so the
        # hook received `{"_redacted_type": "UUID"}`, passed it to the Infinity job, and
        # `require_user_id` raised "user_id is required". Every completed agent run to date
        # (8 of 8) ended here; none carries `loop_enforced`. `run.user_id` is on the row we
        # already re-fetch by the one primitive that does survive the boundary. The context
        # value is kept only as a fallback for a caller that passes a real string.
        user_id = _hook_user_id(getattr(run, "user_id", None)) or _hook_user_id(context.get("user_id"))
        if not user_id:
            return None

        result_payload = run.result if isinstance(run.result, dict) else {}
        if result_payload.get("loop_enforced"):
            return None

        # The run's real findings, once (the id on run.result is the "already saved" marker).
        if "findings_node_id" not in result_payload:
            try:
                result_payload = {
                    **result_payload,
                    "findings_node_id": _save_run_findings(db, run, user_id),
                }
            except Exception as exc:  # noqa: BLE001 — never block the Infinity loop
                logger.warning("[agent_findings] save skipped for run %s: %s", run_id, exc)

        execute_infinity_orchestrator = get_job("analytics.infinity_execute")
        if execute_infinity_orchestrator is None:
            raise RuntimeError("No registered infinity orchestration job")
        orchestration = execute_infinity_orchestrator(
            user_id=user_id,
            trigger_event="agent_completed",
            db=db,
        )
        run.result = {
            **result_payload,
            "loop_enforced": True,
            "next_action": orchestration["next_action"],
        }
        db.commit()
        # Return a runtime-coercible NextAction (not run.result): the runtime records
        # it as NEXT_ACTION_CHOSEN, so the ledger reflects the app's real decision.
        return _next_action_for_runtime(orchestration)
    except Exception as exc:
        db.rollback()
        logger.warning(
            "[AgentRuntimeExtensions] Agent completion orchestrator failed for %s: %s",
            run_id,
            exc,
        )
        return None
    finally:
        db.close()


def stub_planner_backend(request) -> dict:
    """Canned plan for smoke testing — activates via AINDY_AGENT_PLANNER_BACKEND=stub.

    Emits a runtime-default tool (`memory.recall`), so it exercises the plan ->
    park -> resume -> execute path without needing the app manifest. See
    `stub_app_tool_planner_backend` for the app-manifest-tool variant.
    """
    objective = getattr(request, "objective", "") or ""
    return {
        "executive_summary": "Stub plan for smoke testing. No LLM required.",
        "steps": [
            {
                "tool": "memory.recall",
                "args": {"query": objective[:80] or "smoke test"},
                "risk_level": "high",
                "description": "Stub step: recall memories (smoke test only).",
            }
        ],
        "overall_risk": "high",
    }


def stub_app_tool_planner_backend(request) -> dict:
    """Canned plan whose single step is an APP-MANIFEST-only tool (`task.create`) —
    activates via AINDY_AGENT_PLANNER_BACKEND=stub_app_tool. Deterministic; no LLM,
    key, or network.

    `task.create` has no runtime default (unlike `memory.recall`), so a run that
    executes it end-to-end proves the app plugin manifest resolved AND executed inside
    the `nodus_worker` subprocess — the §5 gate. `risk_level="high"` so
    AINDY_AGENT_WAIT_BEFORE_HIGH_RISK parks the run before the step, mirroring the
    stub/`memory.recall` park->resume path exactly with an app tool swapped in. The
    syscall behind the tool (`sys.v1.task.create`) requires a `name`/`task_name`.
    """
    objective = getattr(request, "objective", "") or ""
    return {
        "executive_summary": "Stub plan exercising an app-manifest tool (task.create). No LLM required.",
        "steps": [
            {
                "tool": "task.create",
                "args": {"name": objective[:60] or "nodus-vm app-tool smoke"},
                "risk_level": "high",
                "description": "Stub step: create a task (app-manifest tool; smoke test only).",
            }
        ],
        "overall_risk": "high",
    }


def register() -> None:
    from AINDY.platform_layer.registry import (
        register_agent_completion_hook,
        register_agent_planner_backend,
        register_planner_context_provider,
        register_run_tool_provider,
    )

    from apps.agent.agents.planner_anthropic import claude_planner_backend

    register_planner_context_provider("default", build_planner_context)
    register_run_tool_provider("default", get_tools_for_run)
    register_agent_completion_hook("default", handle_agent_run_completed)
    register_agent_planner_backend("stub", stub_planner_backend)
    # Deterministic app-manifest-tool planner (task.create) for the §5 nodus_vm Gate 1 —
    # proves app-tool execution in the subprocess with no LLM/key/network.
    register_agent_planner_backend("stub_app_tool", stub_app_tool_planner_backend)
    # App-owned LLM planner: select via AINDY_AGENT_PLANNER_BACKEND=anthropic_chat.
    # The runtime ships disabled/runtime_local/openai_chat_compat; this adds Claude
    # without touching the runtime package.
    register_agent_planner_backend("anthropic_chat", claude_planner_backend)
