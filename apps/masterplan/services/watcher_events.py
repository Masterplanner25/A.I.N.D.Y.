from __future__ import annotations

from typing import Any

from apps.masterplan.services.eta_service import recalculate_all_etas


def handle_watcher_session_ended(event: dict[str, Any]) -> int:
    """React to watcher session completion by recalculating MasterPlan ETAs.

    The runtime's event dispatch passes no session: on the watcher's first real use (2026-11-09) every
    `session_ended` logged "'NoneType' object has no attribute 'query'" here. A usable session from the
    event is used; otherwise the handler opens and closes its own."""
    db = event.get("db")
    if db is not None and callable(getattr(db, "query", None)):
        return recalculate_all_etas(db=db)
    from AINDY.db.database import SessionLocal

    own = SessionLocal()
    try:
        return recalculate_all_etas(db=own)
    finally:
        own.close()


def register_masterplan_event_handlers() -> None:
    from AINDY.platform_layer.event_service import register_event_handler

    register_event_handler("watcher.session_ended", handle_watcher_session_ended)
