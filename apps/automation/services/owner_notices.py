"""Owner notices — one email when something fails that the owner would otherwise only find in a log.

Found by `AUDIT_2026-11-01` §3: three of its findings were invisible until someone read a log or a
table. This closes two of them (`TECH_DEBT.md`):

- **`NODUS-FALLBACK-SILENT-1`.** Every scheduled `.nd` run from 10-22 to 11-01 fell back to Python,
  one WARNING line each. A fallback now writes a durable `nodus.fallback` event
  (`apps/_shared/nodus.py::record_nodus_fallback`), because it happens in a scheduled job's fresh
  callback process, whose metrics die with it. Three in a day for one workflow sends one notice.
- **`LLM-OUTAGE-SILENT-1`.** On 11-01 OpenAI answered 429 `credit_balance_exhausted` for about 90
  minutes and nothing told the owner. The circuit breakers are per process and do not keep the
  provider's error code, so this probes the provider itself: one embedding of "ok", the call that
  failed then. A code that needs a person (credits, key) sends a notice at once; any other failure
  sends one on the second probe in a row. A passing probe after a notice sends "recovered".

**State lives in `system_events`, not a table of ours.** The job runs in a fresh process every tick,
so "already told the owner" is an `owner_notice.sent` event, read back on the next tick. A send that
fails is still recorded, like the release handoff's: one notice per episode, not one a tick.

Recipients: `AINDY_NOTICE_TO`, else every admin's address. Off unless `AINDY_OWNER_NOTICES` is set
(on in compose).
"""
from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_FLAG = "AINDY_OWNER_NOTICES"
_TRUTHY = {"1", "true", "yes", "on"}
TICK_INTERVAL_MINUTES = 15

NODUS_FALLBACK_EVENT = "nodus.fallback"
PROBE_FAILED_EVENT = "provider.probe_failed"
NOTICE_SENT_EVENT = "owner_notice.sent"
EVENT_TYPES = (NODUS_FALLBACK_EVENT, PROBE_FAILED_EVENT, NOTICE_SENT_EVENT)

#: Fallbacks of one workflow within `NODUS_WINDOW` that make a notice. One can be a cold worker over
#: its budget; three in a day is a pattern.
NODUS_FALLBACK_MIN = 3
NODUS_WINDOW = timedelta(hours=24)

#: Provider error codes no retry fixes. OpenAI sends both quota codes for an empty balance.
PERSON_CODES = frozenset({
    "insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
    "invalid_api_key", "account_deactivated",
})


def notices_enabled() -> bool:
    return os.environ.get(_FLAG, "").strip().lower() in _TRUTHY


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _emit(db: Session, event_type: str, payload: dict[str, Any]) -> None:
    from AINDY.core.execution_signal_helper import queue_system_event

    queue_system_event(db=db, event_type=event_type, source="automation", payload=payload)


def _events_since(db: Session, event_type: str, since: datetime) -> list[dict[str, Any]]:
    from AINDY.db.models.system_event import SystemEvent

    rows = (db.query(SystemEvent)
            .filter(SystemEvent.type == event_type, SystemEvent.timestamp >= since)
            .order_by(SystemEvent.timestamp.asc())
            .all())
    return [dict(row.payload or {}) for row in rows]


def last_notice(db: Session, key: str) -> dict[str, Any] | None:
    """The newest notice sent for ``key``, or None. Scans a month, which bounds the read."""
    for payload in reversed(_events_since(db, NOTICE_SENT_EVENT, _now() - timedelta(days=30))):
        if payload.get("key") == key:
            return payload
    return None


# ── Sending ────────────────────────────────────────────────────────────────────────────────


def recipients(db: Session) -> list[tuple[str, str | None]]:
    """``(address, user id)`` pairs. The id rides along for the email channel's connector route."""
    override = (os.getenv("AINDY_NOTICE_TO") or "").strip()
    if override:
        return [(override, None)]
    from AINDY.db.models.user import User

    return [(u.email, str(u.id)) for u in db.query(User).filter(User.is_admin.is_(True)).all() if u.email]


def send_notice(db: Session, key: str, phase: str, subject: str, body: str,
                send: Callable[..., dict] | None = None) -> dict[str, Any]:
    """Mail ``subject``/``body`` to the recipients and record it under ``key``. ``phase`` is ``open``
    (something is wrong) or ``closed`` (it recovered)."""
    if send is None:
        from AINDY.platform_layer.email_channel import send_email as send
    to = recipients(db)
    errors: list[str] = []
    for address, user_id in to:
        try:
            result = send(to=address, subject=subject, body=body, db=db, user_id=user_id)
        except Exception as exc:  # a notice must never break the tick
            result = {"success": False, "error": str(exc)}
        if not result.get("success"):
            errors.append(f"{address}: {result.get('error')}")
    entry = {"key": key, "phase": phase, "subject": subject, "at": _now().isoformat(),
             "success": bool(to) and not errors, "error": "; ".join(errors) or (None if to else "no recipient")}
    _emit(db, NOTICE_SENT_EVENT, entry)
    if not entry["success"]:
        logger.warning("[notices] %s notice not delivered: %s", key, entry["error"])
    return entry


# ── Nodus fallbacks ────────────────────────────────────────────────────────────────────────


def check_nodus_fallbacks(db: Session, send: Callable[..., dict] | None = None) -> list[str]:
    """One notice per workflow with `NODUS_FALLBACK_MIN` fallbacks in the window, at most one a
    window. Returns the workflows noticed."""
    now = _now()
    by_workflow: dict[str, list[dict[str, Any]]] = {}
    for payload in _events_since(db, NODUS_FALLBACK_EVENT, now - NODUS_WINDOW):
        by_workflow.setdefault(str(payload.get("workflow") or "?"), []).append(payload)
    noticed: list[str] = []
    for workflow, events in sorted(by_workflow.items()):
        if len(events) < NODUS_FALLBACK_MIN:
            continue
        key = f"nodus:{workflow}"
        previous = last_notice(db, key)
        if previous and _parse(previous.get("at")) > now - NODUS_WINDOW:
            continue
        reasons = Counter(str(e.get("reason") or "unknown")[:200] for e in events)
        lines = "\n".join(f"  {count} x {reason}" for reason, count in reasons.most_common(5))
        send_notice(db, key, "open",
                    f"A.I.N.D.Y.: {workflow} fell back to Python {len(events)} times in a day",
                    f"The Nodus workflow {workflow} did not complete on the VM {len(events)} times in the "
                    f"last 24 hours, so each run used its Python path. No work was lost.\n\n"
                    f"Reasons:\n{lines}\n\nLast at {events[-1].get('at')}. This notice repeats at most "
                    "once a day while it continues.", send=send)
        noticed.append(workflow)
    return noticed


# ── LLM provider ───────────────────────────────────────────────────────────────────────────


def classify(exc: BaseException) -> tuple[str, int | None, str]:
    """``(code, http status, message)`` for a provider error. The code is the provider's when it
    sent one (`insufficient_quota`), else the exception's class name."""
    status = getattr(exc, "status_code", None)
    code = getattr(exc, "code", None)
    body = getattr(exc, "body", None)
    if not code and isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        code = inner.get("code") or inner.get("type")
    return str(code or type(exc).__name__), status, str(exc)[:300]


def needs_person(code: str, status: int | None) -> bool:
    return code in PERSON_CODES or status in (401, 403)


def probe_openai() -> None:
    """One embedding of "ok", no retries. Raises the SDK's error on failure."""
    from openai import OpenAI

    from AINDY.memory.embedding_service import EMBEDDING_MODEL
    from apps._shared.provider_keys import provider_key

    # The SERVER's key, on purpose (FR-59): this probe watches the operator's own balance.
    key = provider_key(None, "openai", system=True).value
    OpenAI(api_key=key, timeout=20.0, max_retries=0).embeddings.create(
        model=EMBEDDING_MODEL, input="ok")


def check_provider(db: Session, provider: str, probe: Callable[[], None],
                   send: Callable[..., dict] | None = None) -> str:
    """Probe once and notice a change. Returns ``ok``, ``failing``, ``noticed`` or ``recovered``."""
    key = f"provider:{provider}"
    previous = last_notice(db, key)
    is_open = bool(previous) and previous.get("phase") == "open"
    try:
        probe()
    except Exception as exc:
        code, status, message = classify(exc)
        now = _now()
        _emit(db, PROBE_FAILED_EVENT, {"provider": provider, "code": code, "status": status,
                                       "message": message, "at": now.isoformat()})
        if is_open:
            return "failing"
        recent = [e for e in _events_since(db, PROBE_FAILED_EVENT,
                                           now - timedelta(minutes=2 * TICK_INTERVAL_MINUTES + 5))
                  if e.get("provider") == provider]
        if not needs_person(code, status) and len(recent) < 2:
            return "failing"
        action = ("It needs you: no retry fixes this code." if needs_person(code, status)
                  else "It has failed on two probes in a row.")
        send_notice(db, key, "open", f"A.I.N.D.Y.: {provider} is failing ({code})",
                    f"A probe of {provider} failed at {now.isoformat()}: HTTP {status}, code {code}.\n\n"
                    f"{message}\n\n{action} Drafts, share drafts and memory embeddings wait or fall back "
                    "while it lasts. You will get one more email when it recovers.", send=send)
        return "noticed"
    if is_open:
        send_notice(db, key, "closed", f"A.I.N.D.Y.: {provider} has recovered",
                    f"A probe of {provider} passed at {_now().isoformat()}. Work that waited resumes on "
                    "its own schedule; a share-drafts piece marked failed has to be queued again.", send=send)
        return "recovered"
    return "ok"


def _parse(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── The job ────────────────────────────────────────────────────────────────────────────────


def owner_notices_tick() -> dict[str, Any]:
    """Scheduled job body: its own session, every `TICK_INTERVAL_MINUTES`."""
    if not notices_enabled():
        return {"skipped": True, "reason": "disabled"}
    from AINDY.db.database import SessionLocal

    db = SessionLocal()
    summary: dict[str, Any] = {"skipped": False}
    try:
        summary["nodus"] = check_nodus_fallbacks(db)
        if os.environ.get("OPENAI_API_KEY"):
            summary["openai"] = check_provider(db, "openai", probe_openai)
        db.commit()
    except Exception as exc:
        logger.warning("[notices] tick failed: %s", exc)
        db.rollback()
        summary["error"] = str(exc)
    finally:
        db.close()
    return summary
