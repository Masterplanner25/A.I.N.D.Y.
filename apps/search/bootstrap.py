"""Search domain bootstrap."""
from __future__ import annotations

import logging

BOOTSTRAP_DEPENDS_ON: list[str] = ["analytics"]
APP_DEPENDS_ON: list[str] = ["analytics"]

logger = logging.getLogger(__name__)


def _warn_if_leadgen_fixtures_enabled() -> None:
    """Announce at boot when leadgen may return fabricated companies.

    `AINDY_LEADGEN_ALLOW_FIXTURES` lets `run_ai_search` substitute three hardcoded
    companies that do not exist. That is fine locally and must never be true in a real
    deployment: the fabricated leads are scored, persisted to `leadgen_results`, written
    to memory, and **recalled as prior context on later searches**.

    Boot is the right place for this rather than the call site. A per-call warning only
    reaches whoever is reading logs at that moment; a boot warning states the
    deployment's posture once, where it is read alongside the other configuration
    warnings — and an operator who sees it has time to act before any data is written.
    """
    import os

    raw = os.getenv("AINDY_LEADGEN_ALLOW_FIXTURES", "").strip()
    if raw.lower() in {"1", "true", "yes", "on"}:
        logger.warning(
            "[search] AINDY_LEADGEN_ALLOW_FIXTURES=%s - leadgen will return THREE "
            "FABRICATED COMPANIES when retrieval finds nothing, and they will be scored, "
            "persisted and remembered. Development only. Unset this in any real "
            "deployment. See scripts/audit_leadgen_fixtures.py to find rows already written.",
            raw,
        )


def register() -> None:
    _warn_if_leadgen_fixtures_enabled()
    _register_models()
    _register_routers()
    _register_route_prefixes()
    _register_response_adapters()
    _register_syscalls()
    _register_agent_tools()
    _register_agent_capabilities()
    _register_capture_rules()
    _register_flows()
    _register_flow_results()
    _register_flow_plans()
    _register_health_check()


def _register_models() -> None:
    from AINDY.db.database import Base
    from AINDY.db.model_registry import register_models
    from AINDY.platform_layer.registry import register_symbols
    import apps.search.models as search_models

    register_models(search_models.register_models)
    register_symbols(
        {
            name: value
            for name, value in vars(search_models).items()
            if isinstance(value, type) and getattr(value, "metadata", None) is Base.metadata
        }
    )


def _register_routers() -> None:
    from AINDY.platform_layer.registry import register_router
    from apps.search.routes.leadgen_router import router as leadgen_router
    from apps.search.routes.research_results_router import router as research_router
    from apps.search.routes.research_results_router import search_history_router
    from apps.search.routes.search_feedback_router import router as feedback_router
    from apps.search.routes.seo_routes import router as seo_router

    register_router(leadgen_router)
    register_router(research_router)
    register_router(search_history_router)
    register_router(seo_router)
    register_router(feedback_router)


def _register_route_prefixes() -> None:
    from AINDY.platform_layer.registry import register_route_prefix
    register_route_prefix("leadgen", "flow")


def _register_response_adapters() -> None:
    from AINDY.platform_layer.registry import register_response_adapter
    from AINDY.platform_layer.response_adapters import raw_json_adapter

    register_response_adapter("leadgen", raw_json_adapter)
    register_response_adapter("seo", raw_json_adapter)


def _register_health_check() -> None:
    from AINDY.platform_layer.registry import register_health_check

    register_health_check("search", lambda: {"status": "ok"})


def _register_syscalls() -> None:
    from apps.search.syscalls import register_search_syscall_handlers

    register_search_syscall_handlers()


def _register_agent_tools() -> None:
    from apps.search.agents.tools import register as register_search_tools
    register_search_tools()


def _register_agent_capabilities() -> None:
    from apps.search.agents.capabilities import register as register_search_capabilities
    register_search_capabilities()


def _register_capture_rules() -> None:
    from AINDY.platform_layer.registry import register_memory_policy
    from apps.search.memory_policy import register as register_search_memory_policy
    register_search_memory_policy(register_memory_policy)


def _register_flows() -> None:
    from AINDY.platform_layer.registry import register_flow, register_symbols
    from apps.search.flows import search_flows

    register_symbols(
        {
            name: value
            for name, value in vars(search_flows).items()
            if not name.startswith("__")
        }
    )
    register_flow(search_flows.register)


def _register_flow_results() -> None:
    from AINDY.platform_layer.registry import register_flow_result

    result_keys = {
        "unified_search": "search_result",
        "leadgen_search": "search_results",
        "leadgen_list": "leadgen_list_result",
        "leadgen_preview_search": "leadgen_preview_search_result",
        "research_create": "research_create_result",
        "research_list": "research_list_result",
        "research_query": "research_query_result",
        "search_history_list": "search_history_list_result",
        "search_history_get": "search_history_get_result",
        "search_history_delete": "search_history_delete_result",
    }
    for flow_name, result_key in result_keys.items():
        register_flow_result(flow_name, result_key=result_key)

    register_flow_result("leadgen_search", completion_event="leadgen_search")


def _register_flow_plans() -> None:
    from AINDY.platform_layer.registry import register_flow_plan

    register_flow_plan(
        "leadgen_search",
        {"steps": ["leadgen_validate", "leadgen_search", "leadgen_store"]},
    )
