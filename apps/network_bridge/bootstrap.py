"""Network bridge domain bootstrap."""
from __future__ import annotations

BOOTSTRAP_DEPENDS_ON: list[str] = ["authorship", "rippletrace"]
APP_DEPENDS_ON: list[str] = ["authorship"]


def register() -> None:
    _register_router()
    _register_response_adapters()
    _register_health_check()
    _register_event_handlers()


def _register_event_handlers() -> None:
    """Attach the sign-in hook this domain was built for.

    ``POST /network_bridge/user_event`` says it is "called from the Node server whenever
    a new user joins" — an external caller that no longer exists, which is why the
    endpoint sat unused and ``authors`` stayed at zero. The domain's whole purpose is to
    record a person entering the system; it just had no trigger.

    The runtime emits ``auth.login.completed`` from its own login route as a required
    system event, and ``emit_system_event`` dispatches to in-process handlers. So the
    trigger exists — it fires at *actual* sign-in rather than somewhere inside the app,
    which is the distinction that was missing.

    **Import from ``event_service``, not ``registry``.** Both modules export a
    ``register_event_handler`` and they feed different buses: the registry one is
    dispatched only by explicit ``registry.emit_event`` calls at specific runtime points
    (flow completion, async jobs), while this one is dispatched by *every*
    ``emit_system_event``. ``auth.login.completed`` arrives on the latter, so registering
    with the registry version silently never fires. ``apps/tasks`` aliases it
    ``register_internal_event_handler`` for exactly this reason.
    """
    from AINDY.platform_layer.event_service import (
        register_event_handler as register_internal_event_handler,
    )
    from apps.network_bridge.services.network_bridge_services import handle_sign_in

    register_internal_event_handler("auth.login.completed", handle_sign_in)


def _register_router() -> None:
    from AINDY.platform_layer.registry import register_router
    from apps.network_bridge.routes.network_bridge_router import router as network_bridge_router
    register_router(network_bridge_router)


def _register_response_adapters() -> None:
    from AINDY.platform_layer.registry import register_response_adapter
    from AINDY.platform_layer.response_adapters import raw_json_adapter
    register_response_adapter("network_bridge", raw_json_adapter)


def _register_health_check() -> None:
    from AINDY.platform_layer.registry import register_health_check

    register_health_check("network_bridge", lambda: {"status": "ok"})
