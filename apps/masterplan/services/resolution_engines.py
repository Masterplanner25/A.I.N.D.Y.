"""The answer engines a resolution check asks — `RESOLUTION_CHECK_SPEC.md` §1, §7 decision 2.

Each is asked the question exactly as a person would type it, with live web search, and returns the
answer and the URLs it cited. Verified reachable 2026-09-30 with the keys this stack already holds;
OpenAI's `gpt-4o-search-preview` is retired (404), so OpenAI is asked through the Responses API with its
`web_search` tool. Every call is metered through `perform_external_call` like the rest of the system.
"""
from __future__ import annotations

import os
from typing import Callable

import requests

TIMEOUT_SECONDS = 120


def _model(env: str, default: str) -> str:
    return (os.getenv(env) or "").strip() or default


def _call(service: str, url: str, *, headers: dict, body: dict, purpose: str) -> dict:
    from AINDY.platform_layer.external_call_service import perform_external_call

    response = perform_external_call(
        service_name=service,
        endpoint=url,
        method="POST",
        model=body.get("model"),
        extra={"purpose": purpose},
        operation=lambda: requests.post(url, headers=headers, json=body, timeout=TIMEOUT_SECONDS),
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{service} answered HTTP {response.status_code}: {response.text[:200]}")
    return response.json()


def ask_perplexity(question: str) -> dict:
    data = _call(
        "perplexity", "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}"},
        body={"model": _model("AINDY_RESOLUTION_PERPLEXITY_MODEL", "sonar"),
              "messages": [{"role": "user", "content": question}]},
        purpose="resolution_check",
    )
    citations = data.get("citations") or [r.get("url") for r in data.get("search_results") or []]
    return {"answer": data["choices"][0]["message"]["content"], "citations": [c for c in citations if c]}


def ask_openai(question: str) -> dict:
    data = _call(
        "openai", "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        body={"model": _model("AINDY_RESOLUTION_OPENAI_MODEL", "gpt-4.1"),
              "tools": [{"type": "web_search"}], "input": question},
        purpose="resolution_check",
    )
    texts, citations = [], []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            texts.append(part.get("text") or "")
            citations += [a.get("url") for a in part.get("annotations") or [] if a.get("type") == "url_citation"]
    return {"answer": "\n".join(t for t in texts if t), "citations": [c for c in citations if c]}


def ask_claude(question: str) -> dict:
    data = _call(
        "anthropic", "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
        body={"model": _model("AINDY_RESOLUTION_CLAUDE_MODEL", "claude-sonnet-5"), "max_tokens": 900,
              "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
              "messages": [{"role": "user", "content": question}]},
        purpose="resolution_check",
    )
    texts, citations = [], []
    for block in data.get("content") or []:
        if block.get("type") == "text":
            texts.append(block.get("text") or "")
            citations += [c.get("url") for c in block.get("citations") or [] if c.get("url")]
    return {"answer": "".join(texts).strip(), "citations": list(dict.fromkeys(c for c in citations if c))}


ENGINES: dict[str, Callable[[str], dict]] = {
    "perplexity": ask_perplexity,
    "openai": ask_openai,
    "claude": ask_claude,
}


def configured_engines() -> list[str]:
    """`AINDY_RESOLUTION_ENGINES` (comma-separated) narrows the set; all three by default (decision 2)."""
    wanted = [e.strip() for e in (os.getenv("AINDY_RESOLUTION_ENGINES") or "").split(",") if e.strip()]
    return [e for e in (wanted or list(ENGINES)) if e in ENGINES]
