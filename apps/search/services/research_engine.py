import os

import requests
from AINDY.platform_layer.openai_client import get_openai_client, chat_completion
from AINDY.config import settings
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from AINDY.db import models
from AINDY.platform_layer.external_call_service import perform_external_call

#: Perplexity's search recency values (checked against its API reference, 2026-09-28).
RECENCY_VALUES = ("hour", "day", "week", "month", "year")


def web_search_results(
    query: str,
    *,
    domains: list[str] | None = None,
    recency: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    """External web search via the Perplexity Search API, as rows: ``{title, url, snippet, date}``.

    ``domains`` limits the search to those sites (at most 20, Perplexity's cap) and ``recency`` to
    results that recent. Both were available all along and never sent: until MARKET_MODEL_SPEC
    phase B, every search was the whole open web at any age. Verified live 2026-09-30: a job-board
    filter returns job postings (Greenhouse), the open web returns listicles.

    Previously this issued ``GET https://api.perplexity.ai/search?q=…`` with no
    Authorization header — right host, wrong method, no auth — so it never returned
    results even before a key existed. The endpoint takes a POST with the query in a
    JSON body and a Bearer token.
    """
    key = (os.environ.get("PERPLEXITY_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "PERPLEXITY_API_KEY is not set; web research is unavailable."
        )
    body: dict = {"query": query, "max_results": max(1, min(int(max_results or 10), 20))}
    if domains:
        body["search_domain_filter"] = [d for d in domains if d][:20]
    if recency:
        if recency not in RECENCY_VALUES:
            raise ValueError(f"recency must be one of: {', '.join(RECENCY_VALUES)}")
        body["search_recency_filter"] = recency

    url = "https://api.perplexity.ai/search"
    resp = perform_external_call(
        # The second Perplexity call site in this repo — the first is rippletrace's mention
        # detection. Both hit `/search`, both spend the same key, and both were labelled
        # `http`, so neither was countable against the other.
        service_name="perplexity",
        endpoint=url,
        method="POST",
        extra={"purpose": "research_web_search", "filtered": bool(domains or recency)},
        operation=lambda: requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=20,
        ),
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Web search failed with HTTP {resp.status_code}.")
    return [
        {
            "title": str(row.get("title") or "").strip(),
            "url": str(row.get("url") or "").strip(),
            "snippet": str(row.get("snippet") or "").strip(),
            "date": row.get("date") or row.get("last_updated"),
        }
        for row in (resp.json() or {}).get("results") or []
        if isinstance(row, dict)
    ]


def web_search(query: str) -> str:
    """The open-web search as flattened text, because its callers (``ai_analyze``, the research
    tool) want prose to summarise."""
    rendered = "\n\n".join(
        f"{row['title']}\n{row['url']}\n{row['snippet']}" for row in web_search_results(query)
    )
    return rendered[:5000]  # limit content size

def ai_analyze(content: str) -> str:
    """Summarize and extract next actions."""
    prompt = f"Summarize and extract 3 recommended actions:\n\n{content}"
    completion = perform_external_call(
        service_name="openai",
        endpoint="chat.completions.create",
        model="gpt-4o",
        method="openai.chat",
        extra={"purpose": "research_ai_analyze"},
        operation=lambda: chat_completion(
            get_openai_client(),
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
        ),
    )
    return completion.choices[0].message.content

def save_result(db: Session, query, summary, source):
    record = models.ResearchResult(
        query=query,
        summary=summary,
        source=source,
        # ResearchResult.created_at is a legacy naive DateTime column; SQLAlchemy may strip tzinfo here.
        created_at=datetime.now(timezone.utc)
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record

