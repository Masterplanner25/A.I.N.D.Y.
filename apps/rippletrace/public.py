"""Public interface for the rippletrace app. Other apps must only import from this file."""

from apps.rippletrace.flow_strategy import update_strategy_score
from apps.rippletrace.models import (
    ContentSourceDB,
    DropPointDB,
    PingDB,
    PlaybookDB,
    RippleEdge,
    StrategyDB,
)
from apps.rippletrace.services.rippletrace_service import (
    build_trace_graph,
    generate_trace_insights,
    get_upstream_causes,
    link_events,
)
from apps.rippletrace.services.rippletrace_services import (
    add_drop_point,
    add_ping,
    get_all_drop_points,
    get_all_pings,
    get_recent_ripples,
    get_ripples,
    log_ripple_event,
)

def own_piece_links(db, *, user_id, text, title=None, exclude_url=None, missing_limit=8):
    """The owner's pieces a draft links to, relevant ones it does not, and its other links
    (ARTICLE_ANSWERS_SPEC §3). Imported lazily: the archive it reads is not needed at boot."""
    from apps.rippletrace.services.own_links import own_piece_links as _own_piece_links

    return _own_piece_links(
        db, user_id=user_id, text=text, title=title, exclude_url=exclude_url, missing_limit=missing_limit
    )


__all__ = [
    "ContentSourceDB",
    "DropPointDB",
    "PingDB",
    "PlaybookDB",
    "RippleEdge",
    "StrategyDB",
    "add_drop_point",
    "add_ping",
    "build_trace_graph",
    "generate_trace_insights",
    "get_all_drop_points",
    "get_all_pings",
    "get_recent_ripples",
    "get_ripples",
    "get_upstream_causes",
    "link_events",
    "log_ripple_event",
    "own_piece_links",
    "update_strategy_score",
]
