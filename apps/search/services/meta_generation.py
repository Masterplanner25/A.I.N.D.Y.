"""Meta description, written from the whole article's central point.

Until 2026-10-25 the "generated" description was the article's first ~160 characters, cut at a
sentence end (`generate_meta_description`). Nothing read the article. The owner asked how the
tool arrives at a description: does it find the central argument and build around it, or is it
summarising by position? It was the second, and the answer is now the first.

The model is asked for two things, and both come back:

* ``central_point`` — the one-sentence point it took the article to make. Shown to the writer,
  so a description built on the wrong reading is visible as a wrong reading rather than as a
  plausible sentence;
* ``meta_description`` — written around that point, keeping the framing of the writer's title.

★ Same rules as `title_generation`: it proposes and never replaces, it is measured against the
SERP budget rather than silently trimmed, and **it fails honestly**. An opening-lines fallback
would arrive looking exactly like a description the model wrote from the whole piece, which is
the confusion this module exists to end.
"""

from __future__ import annotations

import json
import logging
import re

from AINDY.config import settings
from AINDY.kernel.circuit_breaker import CircuitOpenError
from AINDY.platform_layer.external_call_service import perform_external_call
from AINDY.platform_layer.openai_client import chat_completion, get_openai_client

from apps.search.services.seo_services import (
    META_CHAR_BUDGET,
    META_CHAR_MIN,
    count_characters,
    truncate_preview,
)
from apps.search.services.title_generation import MAX_ARTICLE_CHARS_SENT, MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are helping a writer describe an article they have already written, for
the description line under a search result.

First read the WHOLE article and decide the single point it makes: the argument or discovery
the piece exists to deliver, in the writer's own terms. Not its most frequent topic, and not a
theme it passes through on the way.

Then write the description around that point.

Rules:
- Aim for {budget} characters or fewer. Search results cut the rest. Below {minimum} leaves
  room unused.
- If the writer supplied a title, it states what they think the piece is about. Keep that
  framing. Describe the point the title makes, not a different one the article also touches.
- Do not introduce a claim, a number, a name or a result that is not in the article.
- Plain language. No clickbait, no manufactured urgency, no emoji, no "In this article".

Return ONLY valid JSON in this exact format:

{{"central_point": "...", "meta_description": "..."}}"""


def _user_prompt(text: str, *, title: str | None) -> str:
    parts = ["Describe this article."]
    if title:
        parts.append(f'The writer\'s title: "{title}"')
    parts.append("---")
    parts.append(text[:MAX_ARTICLE_CHARS_SENT])
    return "\n\n".join(parts)


def _parse(content: str) -> tuple[str, str]:
    """(central_point, meta_description), or empty strings when the response is unusable."""
    text = (content or "").strip()
    if not text.startswith("{"):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return "", ""
        text = match.group(0)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    point = payload.get("central_point")
    meta = payload.get("meta_description")
    return (
        " ".join(point.split()) if isinstance(point, str) else "",
        " ".join(meta.split()) if isinstance(meta, str) else "",
    )


def generate_meta_from_article(
    text: str,
    *,
    title: str | None = None,
    budget: int | None = None,
    user_id: str | None = None,
    db=None,
) -> dict:
    """Write a meta description from the article's central point, measured against the budget.

    Over budget is kept and marked, never trimmed here: a description cut mid-thought by the
    tool reads as finished, and the writer may prefer to shorten it their own way.
    """
    budget = int(budget or META_CHAR_BUDGET)
    article = (text or "").strip()
    if not article:
        return _empty("no article text supplied", budget)

    try:
        completion = perform_external_call(
            service_name="openai",
            db=db,
            user_id=user_id,
            endpoint="chat.completions.create",
            model=MODEL,
            method="openai.chat",
            extra={"purpose": "seo_meta_generation"},
            operation=lambda: chat_completion(
                get_openai_client(),
                model=MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT.format(budget=budget, minimum=META_CHAR_MIN),
                    },
                    {"role": "user", "content": _user_prompt(article, title=title)},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
                timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
            ),
        )
    except CircuitOpenError:
        logger.warning("[SEO] meta generation unavailable — OpenAI circuit open")
        return _empty("the description service is temporarily unavailable", budget)
    except Exception as exc:
        logger.warning("[SEO] meta generation failed: %s", exc)
        return _empty("the description service could not be reached", budget)

    point, meta = _parse(completion.choices[0].message.content)
    if not meta:
        return _empty("no usable description was returned", budget)

    characters = count_characters(meta)
    preview, truncated = truncate_preview(meta, budget)
    return {
        "meta_description": meta,
        "central_point": point,
        "characters": characters,
        "budget": budget,
        "over_by": max(0, characters - budget),
        "serp_preview": preview,
        "truncated": truncated,
        "reason": None,
    }


def _empty(reason: str, budget: int) -> dict:
    return {
        "meta_description": "",
        "central_point": "",
        "characters": 0,
        "budget": budget,
        "over_by": 0,
        "serp_preview": "",
        "truncated": False,
        "reason": reason,
    }
