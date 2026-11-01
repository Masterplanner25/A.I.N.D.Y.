"""Reasoning apply — Python vs Nodus-native routing (FR-5 adoption).

The reasoning "apply" step computes the user's recommendation. It runs in-process
(`recommend_next_action`) by default; behind `AINDY_REASONING_NODUS_NATIVE` (default off)
it instead executes the native `reasoning_apply_v1.nd` on the Nodus VM via
`run_nodus_workflow`, which reaches the reasoning logic through the
`sys.v1.analytics.reasoning_recommendation` syscall (unblocked by aindy-runtime 1.9.0 /
FR-5). Both paths return the same `{"data": recommendation}` envelope, so the flow node
and every downstream consumer are unchanged. Nodus failures fall back to the Python path
so the loop never breaks. Behavior-neutral substrate swap; soak-then-flip.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_FLAG = "AINDY_REASONING_NODUS_NATIVE"
_TRUTHY = {"1", "true", "yes", "on"}
_WORKFLOW = "reasoning_apply_v1"


def nodus_reasoning_enabled() -> bool:
    """Whether reasoning-apply routes through the Nodus VM (opt-in, default off)."""
    return os.environ.get(_FLAG, "").strip().lower() in _TRUTHY


def run_reasoning_apply(db: Any, user_id: Any) -> dict[str, Any]:
    """Return the reasoning recommendation as ``{"data": recommendation}``.

    Routes through the Nodus VM when enabled, else the in-process Python path. Any Nodus
    error (or an empty/failed VM result) falls back to Python so the reasoning loop never
    breaks on the opt-in path.
    """
    if nodus_reasoning_enabled():
        reason: object = "the VM run did not report success"
        try:
            recommendation = _apply_via_nodus(db, user_id)
            if recommendation is not None:
                return {"data": recommendation, "_via": "nodus"}
            logger.warning("[reasoning] nodus apply returned no result; falling back to python")
        except Exception as exc:  # pragma: no cover - defensive; loop must not break
            reason = exc
            logger.warning("[reasoning] nodus apply failed, falling back to python: %s", exc)
        from apps._shared.nodus import record_nodus_fallback

        record_nodus_fallback(db, workflow=_WORKFLOW, user_id=user_id, reason=reason)
    return {"data": _apply_via_python(db, user_id)}


def _apply_via_python(db: Any, user_id: Any) -> dict[str, Any]:
    from apps.analytics.services.reasoning import recommend_next_action

    return recommend_next_action(str(user_id), db) or {}


def _apply_via_nodus(db: Any, user_id: Any) -> dict[str, Any] | None:
    from apps._shared.nodus import run_domain_nodus_workflow

    out = run_domain_nodus_workflow(
        "analytics",
        _WORKFLOW,
        db=db,
        user_id=str(user_id),
        input_payload={"args": {"user_id": str(user_id)}},
    )
    return _extract_recommendation(out)


def _extract_recommendation(out: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pull the recommendation out of the Nodus return envelope.

    The VM surfaces ``set_state`` at ``data.nodus_output_state``; the reasoning step stores
    the syscall envelope under ``reasoning_apply_result``. The recommendation is that
    envelope's ``data``. Returns None when the VM run did not complete successfully so the
    caller can fall back to Python.
    """
    data = (out or {}).get("data") or {}
    if str(data.get("nodus_status") or "").lower() != "success":
        return None
    envelope = (data.get("nodus_output_state") or {}).get("reasoning_apply_result") or {}
    if str(envelope.get("status") or "").lower() != "success":
        return None
    recommendation = dict(envelope.get("data") or {})
    # The syscall tags availability; the Python path's shape omits it — normalize.
    recommendation.pop("available", None)
    return recommendation
