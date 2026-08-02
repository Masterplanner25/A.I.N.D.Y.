import json
import logging
from AINDY.core.execution_signal_helper import queue_memory_capture
# Genesis memory capture is routed through a MemoryCaptureEngine-backed helper.
from AINDY.kernel.circuit_breaker import CircuitOpenError
from AINDY.platform_layer.external_call_service import perform_external_call
from AINDY.core.system_event_service import emit_error_event
from AINDY.platform_layer.openai_client import get_openai_client, chat_completion
from AINDY.config import settings

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"  # efficient + structured

# How many prior turns are replayed to the model. Enough to hold a real thread; bounded
# so a long session cannot grow the prompt without limit.
MAX_TRANSCRIPT_TURNS_SENT = 20
MAX_TRANSCRIPT_CHARS_SENT = 12000

GENESIS_SYSTEM_PROMPT = """
You are A.I.N.D.Y., a calm and reflective strategic partner helping a user define a long-term MasterPlan.

You are a partner in a conversation, not a form. The dialogue so far is provided; treat it as
shared history you both remember.

Tone:
- Calm and minimal. No hype language. No emojis.
- 2-4 lines for an ordinary turn. Up to 6 when you are proposing synthesis.

How to behave as a partner:
- Build on what has already been said. Never re-ask something the user has already answered —
  if you need to revisit it, say why.
- Probe the weakest part of the plan rather than the next empty field. A vague mechanism matters
  more than a missing asset list.
- Push back when something does not hold together: an unrealistic horizon, a mechanism with no
  route to revenue, two stated goals in tension. Name the tension plainly and ask about it.
- Reflect understanding back in your own words when the user says something substantial, so they
  can correct you early.
- Volunteer what is still thin. The user should never have to ask how far along they are.

On readiness — you decide this, the user should not have to declare it:
- Set "synthesis_ready": true once vision_summary, time_horizon and mechanism_summary are all
  present and coherent, and your confidence is at least 0.6.
- On the turn you first set it true, say so: state that there is enough to synthesize a plan,
  name anything still thin, and invite them to proceed or keep going.
- Do not wait to be asked, and do not require any particular phrase from the user.

State extraction:
- Update only fields the conversation supports. Use null for anything not yet established;
  never invent a value to fill a field.
- "confidence" is your own 0.0-1.0 judgement of how well you understand this person's plan.

You MUST return valid JSON in this exact format:

{
  "reply": "...",
  "state_update": {
    "vision_summary": null,
    "time_horizon": null,
    "mechanism_summary": null,
    "assets_summary": null,
    "inferred_domains": [],
    "inferred_phases": [],
    "confidence": 0.0
  },
  "synthesis_ready": false
}
"""


def build_transcript_window(
    transcript: list[dict] | None,
    *,
    max_turns: int = MAX_TRANSCRIPT_TURNS_SENT,
    max_chars: int = MAX_TRANSCRIPT_CHARS_SENT,
) -> list[dict]:
    """The most recent turns, as OpenAI chat messages, newest-preserving.

    Trimmed from the front, so the model keeps the part of the conversation nearest to
    what is being decided now. Malformed entries are skipped rather than raising — a
    corrupt transcript row must not make the session unusable.
    """
    if not transcript:
        return []

    window: list[dict] = []
    used = 0
    for entry in reversed(transcript):
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content:
            continue
        if len(window) >= max_turns or used + len(content) > max_chars:
            break
        window.append({"role": role, "content": content})
        used += len(content)
    window.reverse()
    return window


def call_genesis_llm(
    message: str,
    current_state: dict,
    user_id: str = None,
    db=None,
    transcript: list[dict] | None = None,
):
    import logging

    # Step 1: Recall relevant past strategic memories before responding
    prior_context = ""
    if user_id and db:
        try:
            from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
            from AINDY.runtime.memory import MemoryOrchestrator

            orchestrator = MemoryOrchestrator(MemoryNodeDAO)
            context = orchestrator.get_context(
                user_id=user_id,
                query=message,
                task_type="strategy",
                db=db,
                max_tokens=600,
                metadata={
                    "tags": ["genesis", "masterplan", "decision"],
                    "limit": 2,
                },
            )
            if context.items:
                prior_context = (
                    "\n\nRelevant past strategic context from this user:\n"
                    + "\n".join(f"- {m.content[:200]}" for m in context.items)
                )
        except Exception as e:
            logging.warning(f"Genesis memory recall failed: {e}")

    # Step 1b: Federated recall - ask ARM what it has learned
    arm_context = ""
    try:
        if user_id and db:
            from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
            fed_dao = MemoryNodeDAO(db)
            arm_memories = fed_dao.recall_from_agent(
                agent_namespace="arm",
                query=message,
                tags=["insight", "analysis"],
                limit=2,
                user_id=user_id,
                include_private=False,
            )
            if arm_memories:
                arm_context = (
                    "\n\nRelevant ARM analysis insights "
                    "(from code reasoning engine):\n"
                    + "\n".join(
                        f"- {m['content'][:150]}"
                        for m in arm_memories
                    )
                )
    except Exception as exc:
        # Plain logging, deliberately: the previous call here was to an
        # `emit_observability_event(logger=..., event=..., error=...)` that is neither
        # imported in this module nor a real signature (the helper takes event_type /
        # payload / source). Any failure in this optional lookup therefore raised
        # NameError from inside the handler and killed the whole Genesis turn — an
        # enrichment nobody needs taking down the conversation.
        logger.warning("Genesis ARM context lookup failed: %s", exc)

    # Step 2: Build prompt with injected memory + identity context
    identity_context = ""
    try:
        if user_id and db:
            from apps.identity.public import get_context_for_prompt as _get_identity_context

            identity_context = _get_identity_context(user_id, db)
    except Exception as exc:
        logger.warning("Genesis identity context lookup failed: %s", exc)

    # The extracted state is context, not dialogue, so it belongs in the system message.
    # Keeping it out of the user turn lets the conversation read as an actual conversation:
    # system → prior turns → the new message.
    system_content = (
        GENESIS_SYSTEM_PROMPT
        + prior_context
        + arm_context
        + identity_context
        + "\n\nStructured state extracted so far (update it incrementally):\n"
        + json.dumps(current_state)
    )

    history = build_transcript_window(transcript)
    chat_messages = (
        [{"role": "system", "content": system_content}]
        + history
        + [{"role": "user", "content": message}]
    )

    try:
        response = perform_external_call(
            service_name="openai",
            db=db,
            user_id=user_id,
            endpoint="chat.completions.create",
            model=MODEL,
            method="openai.chat",
            extra={"purpose": "genesis_message", "history_turns": len(history)},
            operation=lambda: chat_completion(
                get_openai_client(),
                model=MODEL,
                messages=chat_messages,
                temperature=0.4,
                # Without this the model occasionally answers in prose, the parse below
                # fails, and the fallback ships "I need a bit more clarity. Can you
                # elaborate?" — which reads as the partner being dense rather than as a
                # format error. The synthesis and audit calls already pin the format.
                response_format={"type": "json_object"},
                timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
            ),
        )
    except CircuitOpenError as exc:
        logger.warning("[Genesis] OpenAI circuit open — cannot generate response: %s", exc)
        raise

    content = response.choices[0].message.content

    try:
        llm_output = json.loads(content)
    except Exception:
        # Fail-safe fallback
        llm_output = {
            "reply": "I need a bit more clarity. Can you elaborate?",
            "state_update": {},
            "synthesis_ready": False,
        }

    # Step 3: Write memory node after successful LLM call
    if user_id and db:
        try:
            # MemoryCaptureEngine-backed queue_memory_capture persists the Genesis turn.
            state_signals = []
            if current_state.get("vision_summary"):
                state_signals.append(f"vision: {current_state['vision_summary'][:100]}")
            if current_state.get("mechanism_summary"):
                state_signals.append(f"mechanism: {current_state['mechanism_summary'][:100]}")

            memory_content = (
                f"Genesis conversation: user said '{message[:100]}'. "
                f"Current signals: {'; '.join(state_signals) or 'gathering'}. "
                f"Synthesis ready: {llm_output.get('synthesis_ready', False)}"
            )

            queue_memory_capture(
                db=db,
                user_id=user_id,
                agent_namespace="genesis",
                event_type="genesis_message",
                content=memory_content,
                source="genesis_conversation",
                tags=[
                    "genesis",
                    "conversation",
                    "insight",
                    "synthesis_ready" if llm_output.get("synthesis_ready") else "in_progress",
                ],
                node_type="insight",
                context={"significance": current_state.get("confidence", 0.5)},
            )
        except Exception as e:
            logging.warning(f"Genesis conversation memory write failed: {e}")

    return llm_output


SYNTHESIS_SYSTEM_PROMPT = """
You are A.I.N.D.Y., a strategic synthesis engine. Given a structured session state, produce a
complete, actionable MasterPlan draft.

You MUST return valid JSON in this exact format:

{
  "vision_statement": "...",
  "time_horizon_years": 5,
  "primary_mechanism": "...",
  "ambition_score": 0.7,
  "core_domains": [{"name": "...", "intent": "..."}],
  "phases": [{"name": "...", "description": "...", "duration_months": 12}],
  "key_assets": ["..."],
  "success_criteria": ["..."],
  "risk_factors": ["..."],
  "confidence_at_synthesis": 0.0,
  "synthesis_notes": "Brief meta-commentary on the synthesis process and confidence level"
}

Rules:
- ambition_score is a float 0.0–1.0 representing how ambitious/aggressive the plan is.
- time_horizon_years must be a number.
- synthesis_notes should summarize what the AI was confident about and what was inferred.
- Return ONLY the JSON object. No explanation text.
"""


def call_genesis_synthesis_llm(
    current_state: dict,
    user_id: str = None,
    db=None,
) -> dict:
    """Real GPT-4o synthesis call. Replaces the stub from initial implementation."""
    arm_insights = ""
    try:
        if user_id and db:
            from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
            fed_dao = MemoryNodeDAO(db)
            arm_memories = fed_dao.recall_from_agent(
                agent_namespace="arm",
                query=str(current_state),
                tags=["insight"],
                limit=3,
                user_id=user_id,
                include_private=False,
            )
            if arm_memories:
                arm_insights = (
                    "\n\nTechnical insights from ARM "
                    "(code analysis engine):\n"
                    + "\n".join(
                        f"- {m['content'][:200]}"
                        for m in arm_memories
                    )
                )
    except Exception as exc:
        logger.warning("Genesis synthesis ARM context lookup failed: %s", exc)

    system_prompt = SYNTHESIS_SYSTEM_PROMPT + arm_insights
    response = perform_external_call(
        service_name="openai",
        db=db,
        user_id=user_id,
        endpoint="chat.completions.create",
        model="gpt-4o",
        method="openai.chat",
        extra={"purpose": "genesis_synthesis"},
        operation=lambda: chat_completion(
            get_openai_client(),
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"""
Session State:
{json.dumps(current_state, indent=2)}

Synthesize this into a complete MasterPlan draft.
Return only valid JSON.
"""
                }
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
        ),
    )

    content = response.choices[0].message.content

    try:
        return json.loads(content)
    except Exception:
        # Fail-safe: return minimal valid structure
        return {
            "vision_statement": current_state.get("vision_summary", ""),
            "time_horizon_years": current_state.get("time_horizon", 5),
            "primary_mechanism": current_state.get("mechanism_summary", ""),
            "ambition_score": 0.5,
            "core_domains": [
                {"name": d, "intent": ""}
                for d in current_state.get("inferred_domains", [])
            ],
            "phases": [
                {"name": p, "description": "", "duration_months": 12}
                for p in current_state.get("inferred_phases", [])
            ],
            "key_assets": current_state.get("assets_summary", []) or [],
            "success_criteria": [],
            "risk_factors": [],
            "confidence_at_synthesis": current_state.get("confidence", 0.0)
        }


AUDIT_SYSTEM_PROMPT = """
You are the Strategic Integrity Validator of A.I.N.D.Y. — a senior strategic advisor reviewing a
MasterPlan draft before it is locked.

Your job: identify structural flaws, gaps, contradictions, or risks in the draft.

You MUST return valid JSON in this exact format:

{
  "audit_passed": true,
  "findings": [
    {
      "type": "mechanism_gap | contradiction | timeline_risk | asset_gap | confidence_concern",
      "severity": "critical | warning | advisory",
      "description": "...",
      "recommendation": "..."
    }
  ],
  "overall_confidence": 0.0,
  "audit_summary": "One sentence summary of audit result."
}

Rules:
- audit_passed is true only if there are zero critical findings.
- overall_confidence is a float 0.0–1.0.
- findings may be an empty list if the draft is clean.
- Return ONLY the JSON object. No explanation text.
"""


def validate_draft_integrity(draft: dict, user_id: str = None, db=None) -> dict:
    """
    GPT-4o strategic integrity audit for a synthesis draft.
    Returns audit result dict with findings, audit_passed, overall_confidence.
    Retries up to 3 times on JSON parse failure.
    """
    retry_limit = 3
    last_error = None

    for attempt in range(retry_limit):
        try:
            response = perform_external_call(
                service_name="openai",
                db=db,
                user_id=user_id,
                endpoint="chat.completions.create",
                model="gpt-4o",
                method="openai.chat",
                extra={"purpose": "genesis_draft_audit", "attempt": attempt + 1},
                operation=lambda: chat_completion(
                    get_openai_client(),
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"""
MasterPlan Draft:
{json.dumps(draft, indent=2)}

Audit this draft for structural integrity.
Return only valid JSON.
"""
                        }
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
                ),
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            last_error = e
            continue

    # Fail-safe after all retries exhausted
    return {
        "audit_passed": False,
        "findings": [
            {
                "type": "confidence_concern",
                "severity": "warning",
                "description": f"Audit service error after {retry_limit} attempts: {str(last_error)}",
                "recommendation": "Retry the audit or proceed with caution."
            }
        ],
        "overall_confidence": 0.0,
        "audit_summary": "Audit could not be completed due to a service error."
    }



