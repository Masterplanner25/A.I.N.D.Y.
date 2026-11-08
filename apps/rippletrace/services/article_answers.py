"""Usability, the owner's definition: the range of questions an article answers (ARTICLE_ANSWERS_SPEC §2).

A model reads the whole article and returns:

* ``answers``: questions the article answers, each with the passage that answers it and its kind
  (*what is*, *how*, *why*, *compared with*, *who*, or *other*);
* ``raised``: questions the article brings up and leaves open (some on purpose, such as a series
  setting up its next part; the writer decides);
* ``range``: the answers counted by kind, a spread and not a score.

Every passage is checked against the article. ``passage_found`` says whether it appears there
(whitespace, case and curly quotes aside), so the writer can tell the model's quote from its
paraphrase rather than trust a count. Nothing here suggests wording that would make the article
answer more (`SEO_EDITING_AID_SPEC`).

Decided 2026-11-08 (§8): gpt-5.5 at low reasoning effort, run on a button, never on typing. It fails
honestly: on any failure ``reason`` is set and the lists are empty, never a guess.

Lives in RippleTrace (moved from search 2026-11-08, phase B2) because answers are stored per published
piece here; the SEO tool reaches it through `apps.rippletrace.public`.
"""
from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

MODEL = "gpt-5.5"
REASONING_EFFORT = "low"
REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")
REASONING_MAX_TOKENS = 16_000
MAX_ARTICLE_CHARS_SENT = 60_000
MAX_ANSWERS = 30
MAX_RAISED = 12
KINDS = ("what_is", "how", "why", "compared_with", "who", "other")

SYSTEM_PROMPT = """You read an article a writer has written and report what questions it answers,
for someone deciding whether an AI search engine could use this text to answer people.

Read the WHOLE article. Then list:

1. "answers": the questions this article actually answers. For each:
   - "question": the question, phrased the way a reader would ask it.
   - "passage": the sentence or two from the article that answers it, COPIED EXACTLY, word for word.
   - "kind": one of "what_is", "how", "why", "compared_with", "who", "other".
   Only questions the text answers itself. Not questions it merely mentions.
2. "raised": questions the article brings up and leaves open. For each, "question" and the
   "passage" (copied exactly) that raises it.

Rules:
- Do not suggest changes to the article. Do not judge its quality.
- Do not invent facts, names or numbers that are not in the article.
- At most 30 answers and 12 raised questions; prefer the most distinct ones.

Return ONLY valid JSON:
{"answers": [{"question": "...", "passage": "...", "kind": "..."}], "raised": [{"question": "...", "passage": "..."}]}"""


def _model() -> str:
    return (os.getenv("AINDY_ANSWERS_MODEL") or "").strip() or MODEL


def _sampling(model: str) -> dict:
    """gpt-5.x refuses `max_tokens` and any temperature but 1 (see CLAUDE.md, content.draft)."""
    if model.startswith(REASONING_PREFIXES):
        effort = (os.getenv("AINDY_ANSWERS_REASONING_EFFORT") or "").strip() or REASONING_EFFORT
        return {"max_completion_tokens": REASONING_MAX_TOKENS, "reasoning_effort": effort}
    return {"temperature": 0.2, "max_tokens": 4000}


def _fold(text: str) -> str:
    """For matching a quoted passage against the article: case, whitespace and quote styles aside."""
    text = text or ""
    # A link reads as its words: `[found](https://…)` and `<a href="…">found</a>` are "found" to a reader,
    # so a quote of the sentence must match. Images go entirely; other tags drop.
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.lower()
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                                         "–": "-", "—": "-", "…": "..."}))
    text = re.sub(r"[*_`#>]", "", text)  # markdown emphasis and headings
    return " ".join(text.split())


def passage_in(passage: str, article_folded: str) -> bool:
    folded = _fold(passage).strip(" .\"'")
    return bool(folded) and folded in article_folded


def parse_response(content: str, article: str) -> dict:
    """The model's JSON, cleaned and checked against the article. Unusable input gives empty lists."""
    text = (content or "").strip()
    if not text.startswith("{"):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        text = match.group(0) if match else ""
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    folded = _fold(article)
    answers: list[dict] = []
    for item in payload.get("answers") or []:
        if not isinstance(item, dict):
            continue
        question = " ".join(str(item.get("question") or "").split())
        passage = " ".join(str(item.get("passage") or "").split())
        if not question:
            continue
        kind = str(item.get("kind") or "other").strip().lower().replace(" ", "_")
        answers.append({"question": question, "passage": passage,
                        "kind": kind if kind in KINDS else "other",
                        "passage_found": passage_in(passage, folded)})
        if len(answers) >= MAX_ANSWERS:
            break

    raised: list[dict] = []
    for item in payload.get("raised") or []:
        if not isinstance(item, dict):
            continue
        question = " ".join(str(item.get("question") or "").split())
        passage = " ".join(str(item.get("passage") or "").split())
        if not question:
            continue
        raised.append({"question": question, "passage": passage, "passage_found": passage_in(passage, folded)})
        if len(raised) >= MAX_RAISED:
            break

    counts = {kind: 0 for kind in KINDS}
    for answer in answers:
        counts[answer["kind"]] += 1
    return {"answers": answers, "raised": raised, "range": counts}


def _empty(reason: str, model: str) -> dict:
    return {"answers": [], "raised": [], "range": {kind: 0 for kind in KINDS}, "model": model, "reason": reason}


def article_answers(text: str, *, title: str | None = None, user_id: str | None = None, db=None) -> dict:
    """What questions the article answers, and which it raises and leaves open."""
    from AINDY.config import settings
    from AINDY.kernel.circuit_breaker import CircuitOpenError
    from AINDY.platform_layer.external_call_service import perform_external_call
    from AINDY.platform_layer.openai_client import chat_completion
    from apps._shared.provider_keys import llm_client, raise_key_problem

    model = _model()
    article = (text or "").strip()
    if not article:
        return _empty("no article text supplied", model)

    user = f'The writer\'s title: "{title}"\n\n---\n\n' if title else ""
    client = llm_client(user_id, db=db)  # whose key pays (FR-59); a 402, never a quiet empty result
    try:
        completion = perform_external_call(
            service_name="openai",
            db=db,
            user_id=user_id,
            endpoint="chat.completions.create",
            model=model,
            method="openai.chat",
            extra={"purpose": "seo_article_answers"},
            operation=lambda: chat_completion(
                client,
                model=model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": user + article[:MAX_ARTICLE_CHARS_SENT]}],
                timeout=max(float(settings.OPENAI_CHAT_TIMEOUT_SECONDS or 0), 120.0),
                **_sampling(model),
            ),
        )
    except CircuitOpenError:
        logger.warning("[SEO] article answers unavailable: OpenAI circuit open")
        return _empty("the answers service is temporarily unavailable", model)
    except Exception as exc:
        raise_key_problem(exc)
        logger.warning("[SEO] article answers failed: %s", exc)
        return _empty("the answers service could not be reached", model)

    result = parse_response(completion.choices[0].message.content, article)
    if not result["answers"] and not result["raised"]:
        return _empty("no usable answers were returned", model)
    result["model"] = model
    result["reason"] = None
    result["truncated_input"] = len(article) > MAX_ARTICLE_CHARS_SENT
    return result
