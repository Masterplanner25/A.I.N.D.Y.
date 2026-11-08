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

def article_answers(text, *, title=None, user_id=None, db=None):
    """What questions an article answers, and which it raises (ARTICLE_ANSWERS_SPEC §2). Imported
    lazily: it is a model call, not needed at boot."""
    from apps.rippletrace.services.article_answers import article_answers as _article_answers

    return _article_answers(text, title=title, user_id=user_id, db=db)


def extract_links(text):
    """The links a text makes, as RippleTrace stores them (`services/links.py`)."""
    from apps.rippletrace.services.links import extract_links as _extract_links

    return _extract_links(text)


def passage_in(passage, article_folded):
    """Whether a quoted passage appears in an article already folded by `fold_text`."""
    from apps.rippletrace.services.article_answers import passage_in as _passage_in

    return _passage_in(passage, article_folded)


def fold_text(text):
    """Case, whitespace, quote styles and markdown aside, for matching a quote against an article."""
    from apps.rippletrace.services.article_answers import _fold

    return _fold(text)


def series_pieces(db, user_id, *, title=None, series=None, exclude_title=None):
    """The draft's confirmed series and its published pieces' text, for the structure view
    (ARTICLE_ANSWERS_SPEC §5). Only the caller's pieces; no model call."""
    from apps.rippletrace.services.series_text import series_pieces as _series_pieces

    return _series_pieces(db, user_id, title=title, series=series, exclude_title=exclude_title)


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
    "article_answers",
    "build_trace_graph",
    "extract_links",
    "fold_text",
    "generate_trace_insights",
    "get_all_drop_points",
    "get_all_pings",
    "get_recent_ripples",
    "get_ripples",
    "get_upstream_causes",
    "link_events",
    "log_ripple_event",
    "own_piece_links",
    "passage_in",
    "series_pieces",
    "update_strategy_score",
]
