import os

import requests
from AINDY.platform_layer.openai_client import get_openai_client, chat_completion
from AINDY.config import settings
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from AINDY.db import models
from AINDY.platform_layer.external_call_service import perform_external_call

def web_search(query: str) -> str:
    """External web search via the Perplexity Search API.

    Previously this issued ``GET https://api.perplexity.ai/search?q=…`` with no
    Authorization header — right host, wrong method, no auth — so it never returned
    results even before a key existed. The endpoint takes a POST with the query in a
    JSON body and a Bearer token, and answers with structured
    ``{title, url, snippet}`` rows.

    Returns flattened text because the caller (``ai_analyze``) wants prose to summarize.
    """
    key = (os.environ.get("PERPLEXITY_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "PERPLEXITY_API_KEY is not set; web research is unavailable."
        )

    url = "https://api.perplexity.ai/search"
    resp = perform_external_call(
        service_name="http",
        endpoint=url,
        method="POST",
        extra={"purpose": "research_web_search", "provider": "perplexity"},
        operation=lambda: requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"query": query, "max_results": 10},
            timeout=20,
        ),
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Web search failed with HTTP {resp.status_code}.")

    results = (resp.json() or {}).get("results") or []
    rendered = "\n\n".join(
        f"{row.get('title', '').strip()}\n{row.get('url', '').strip()}\n"
        f"{row.get('snippet', '').strip()}"
        for row in results
        if isinstance(row, dict)
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

