"""Perplexity Search API client — the one external eye rippletrace has.

Uses the dedicated Search endpoint (``POST https://api.perplexity.ai/search``), not
chat completions. Search returns structured ``{title, url, snippet, date}`` rows;
chat completions returns prose whose citations would have to be scraped back out. For
"who linked to this", the structured form is both cheaper and the only one that can be
turned into a ping without guessing.

Note for anyone comparing against ``apps/search/services/research_engine.py``: the old
call there had the right path but issued a ``GET`` with the query in the URL and no
Authorization header, which is why it never worked even before the key existed.

The key is read from the environment rather than ``AINDY.config.settings`` — settings
is runtime-owned, and an app needing a credential is not a reason to change the
runtime. Same pattern as ``apps/agent/agents/planner_anthropic.py``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

SEARCH_ENDPOINT = "https://api.perplexity.ai/search"
SEARCH_TIMEOUT_SECONDS = 20
DEFAULT_MAX_RESULTS = 10
API_KEY_ENV = "PERPLEXITY_API_KEY"


class MentionSearchUnavailable(Exception):
    """No key, or the provider could not be reached.

    Distinct from "searched and found nothing": callers must not record an empty
    result set as evidence of no mentions when the search never actually ran.
    """


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str = ""
    snippet: str = ""
    published: str | None = None


def api_key() -> str:
    return (os.environ.get(API_KEY_ENV) or "").strip()


def is_configured() -> bool:
    return bool(api_key())


def _parse_date(value: str | None) -> datetime | None:
    from apps.rippletrace.services.content_fetch import _parse_timestamp

    return _parse_timestamp(value or "")


def search(
    queries: list[str],
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    db=None,
    user_id: str | None = None,
) -> list[SearchHit]:
    """Run one or more queries and return de-duplicated hits.

    The API accepts an array of queries in a single request, so related queries (a URL
    and its quoted title, say) cost one call rather than several.
    """
    from AINDY.platform_layer.external_call_service import perform_external_call

    key = api_key()
    if not key:
        raise MentionSearchUnavailable(
            f"{API_KEY_ENV} is not set; ripple detection needs a Perplexity key."
        )

    cleaned = [query.strip() for query in queries if query and query.strip()]
    if not cleaned:
        return []

    payload = {
        "query": cleaned if len(cleaned) > 1 else cleaned[0],
        "max_results": max(1, min(20, int(max_results))),
    }

    try:
        response = perform_external_call(
            service_name="http",
            endpoint=SEARCH_ENDPOINT,
            method="POST",
            db=db,
            user_id=user_id,
            extra={"purpose": "rippletrace_mention_search", "provider": "perplexity"},
            operation=lambda: requests.post(
                SEARCH_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=SEARCH_TIMEOUT_SECONDS,
            ),
        )
    except requests.RequestException as exc:
        raise MentionSearchUnavailable(f"Could not reach the search provider: {exc}") from exc

    if response.status_code == 401:
        raise MentionSearchUnavailable("The Perplexity key was rejected (401).")
    if response.status_code == 429:
        raise MentionSearchUnavailable("Rate limited by the search provider (429).")
    if response.status_code >= 400:
        raise MentionSearchUnavailable(
            f"Search provider returned HTTP {response.status_code}."
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise MentionSearchUnavailable("Search provider returned a non-JSON body.") from exc

    hits: list[SearchHit] = []
    seen: set[str] = set()
    for row in body.get("results") or []:
        if not isinstance(row, dict):
            continue
        url = (row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        hits.append(
            SearchHit(
                url=url,
                title=(row.get("title") or "").strip(),
                snippet=(row.get("snippet") or "").strip(),
                published=(row.get("date") or row.get("last_updated") or None),
            )
        )
    return hits
