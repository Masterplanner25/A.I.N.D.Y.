"""What a draft claims, and what each claim leans on (ARTICLE_ANSWERS_SPEC §4, phase D1).

The SEO tool's **What does this claim?** button. A model reads the whole draft and lists its claims: checkable
facts, as decided 2026-11-08 (§8 decision 6), meaning numbers, dates and events, attributions, statements about
named products, people or organisations, and causes or comparisons stated as fact. Not opinions marked as opinion,
questions, hypotheticals, advice, or the writer's experience framed as experience.

Each claim gets one status:

* about one of the owner's Works (§4):
  * ``contradicts``: it says what the owner denied (their NEVER SAY list). A warning, information only;
  * ``confirmed``: it matches one of the Work's facts;
  * ``new``: about the Work, in neither list. Information, not an error;
* about anything else (decision 7): ``sourced`` when a link in the draft backs it, else ``unsourced``.
  This says what a claim leans on, not whether it is true. No web check.

The model only points: it names a Work, a fact id (``F3``), a denied id (``D1``) and a link id (``L2``) from
lists it is given. This module keeps a pointer only when it is real: the Work exists, the fact or denial belongs to
that Work, and the link is in the draft. Every claim is checked against the text (``found``). On any failure
``reason`` is set and the list is empty, never a guess. Paid with the writer's own key (FR-59).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MODEL = "gpt-5.5"
REASONING_EFFORT = "low"
REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")
REASONING_MAX_TOKENS = 16_000
MAX_ARTICLE_CHARS_SENT = 60_000
MAX_CLAIMS = 40
MAX_LINKS_SENT = 60
KINDS = ("number", "date_event", "attribution", "named", "cause_comparison")
STATUSES = ("contradicts", "confirmed", "new", "sourced", "unsourced")

SYSTEM_PROMPT = """You read a draft a writer is about to publish and list the CLAIMS it makes, so the writer can see
what each one leans on before publishing.

A claim is a statement presented as fact that could be checked:
- "number": a number, statistic, figure or measurement;
- "date_event": a date, or that an event happened;
- "attribution": that someone said, found, wrote or did something ("X found", "Y said");
- "named": a statement about a named product, project, person or organisation, including the writer's own;
- "cause_comparison": a cause, effect or comparison stated as fact.
NOT claims: opinions marked as opinion ("I think", "in my view"), questions, hypotheticals, advice or instructions,
and the writer's own experience framed as experience ("I found", "when I tried").

You are also given THE WRITER'S WORKS, each with numbered FACTS (F1, F2, ...) and DENIED claims (D1, D2, ...), and the
draft's LINKS (L1, L2, ...). For each claim:
- "claim": the sentence or clause from the draft that makes it, COPIED EXACTLY, word for word.
- "kind": one of the five kinds above.
- "work": the exact name of one of THE WRITER'S WORKS if the claim is about it, else null.
- "fact": the id of that Work's fact the claim matches (same meaning, not just the same topic), else null.
- "denied": the id of that Work's denied claim the claim says, or plainly implies, else null.
- "source": the id of the link in the draft that backs the claim (the link in or next to it, or the one it cites),
  else null.

Rules:
- Do not judge whether a claim is true. Do not suggest changes. Do not invent claims, facts or links.
- Only use ids from the lists you were given, and only a fact or denial of the Work you named.
- At most 40 claims; prefer the most specific ones.

Return ONLY valid JSON:
{"claims": [{"claim": "...", "kind": "...", "work": null, "fact": null, "denied": null, "source": null}]}"""


def _model() -> str:
    return (os.getenv("AINDY_CLAIMS_MODEL") or "").strip() or MODEL


def _sampling(model: str) -> dict:
    """gpt-5.x refuses `max_tokens` and any temperature but 1 (see CLAUDE.md, content.draft)."""
    if model.startswith(REASONING_PREFIXES):
        effort = (os.getenv("AINDY_CLAIMS_REASONING_EFFORT") or "").strip() or REASONING_EFFORT
        return {"max_completion_tokens": REASONING_MAX_TOKENS, "reasoning_effort": effort}
    return {"temperature": 0.2, "max_tokens": 4000}


def _host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _owner_truth(user_id: Any, db) -> dict:
    """The writer's Works as numbered facts and denied claims, from masterplan through a call-time syscall
    (search does not import masterplan); it reads only the caller's Works."""
    import uuid as _uuid

    from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

    ctx = SyscallContext(execution_unit_id=str(_uuid.uuid4()), user_id=str(user_id),
                         capabilities=["work.read"], trace_id="", metadata={"_db": db})
    result = get_dispatcher().dispatch("sys.v1.work.get_claim_truth", {}, ctx)
    if result.get("status") != "success":
        raise RuntimeError(result.get("error") or "work claim truth syscall failed")
    data = result.get("data") or {}
    return {"works": list(data.get("works") or []), "own_hosts": list(data.get("own_hosts") or [])}


def build_context(truth: dict, links: list[str]) -> str:
    """The numbered lists the model points into."""
    lines = ["THE WRITER'S WORKS"]
    if not truth["works"]:
        lines.append("(none)")
    for work in truth["works"]:
        lines.append(f"\nWORK: {work['name']} ({work.get('kind') or 'work'})")
        lines += [f"F{i}: {fact}" for i, fact in enumerate(work.get("facts") or [], start=1)]
        lines += [f"D{i}: {claim}" for i, claim in enumerate(work.get("denied") or [], start=1)]
    lines.append("\nLINKS IN THE DRAFT")
    lines += [f"L{i}: {url}" for i, url in enumerate(links[:MAX_LINKS_SENT], start=1)] or ["(none)"]
    return "\n".join(lines)


def _pick(ref: Any, prefix: str, items: list) -> tuple[int, Any] | None:
    """`F3` → (3, items[2]) when it exists; anything else → None."""
    match = re.fullmatch(rf"{prefix}(\d+)", str(ref or "").strip().upper())
    if not match:
        return None
    index = int(match.group(1))
    return (index, items[index - 1]) if 1 <= index <= len(items) else None


def parse_response(content: str, article: str, truth: dict, links: list[str]) -> dict:
    """The model's JSON, cleaned, every pointer checked. Unusable input gives an empty list."""
    from apps.rippletrace.public import fold_text, passage_in

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

    folded = fold_text(article)
    works = {" ".join(str(w["name"]).lower().split()): w for w in truth["works"]}
    own_hosts = {h.lower().removeprefix("www.") for h in truth.get("own_hosts") or []}
    sent_links = links[:MAX_LINKS_SENT]
    claims: list[dict] = []
    for item in payload.get("claims") or []:
        if not isinstance(item, dict):
            continue
        claim = " ".join(str(item.get("claim") or "").split())
        if not claim:
            continue
        kind = str(item.get("kind") or "").strip().lower().replace(" ", "_")
        work = works.get(" ".join(str(item.get("work") or "").lower().split()))
        fact = _pick(item.get("fact"), "F", work.get("facts") or []) if work else None
        denied = _pick(item.get("denied"), "D", work.get("denied") or []) if work else None
        source = _pick(item.get("source"), "L", sent_links)
        if work and denied:
            status = "contradicts"
        elif work and fact:
            status = "confirmed"
        elif work:
            status = "new"
        else:
            status = "sourced" if source else "unsourced"
        claims.append({
            "claim": claim,
            "kind": kind if kind in KINDS else "named",
            "found": passage_in(claim, folded),
            "work": work["name"] if work else None,
            "status": status,
            "fact": fact[1] if fact and status == "confirmed" else None,
            "denied": denied[1] if denied else None,
            "source": source[1] if source else None,
        })
        if len(claims) >= MAX_CLAIMS:
            break

    sources = []
    for url in links:
        leaning = [i for i, c in enumerate(claims) if c["source"] == url]
        sources.append({"url": url, "own": _host(url) in own_hosts, "claims": leaning})
    counts = {status: sum(1 for c in claims if c["status"] == status) for status in STATUSES}
    return {"claims": claims, "counts": counts, "sources": sources}


def _empty(reason: str, model: str, links: list[str] | None = None) -> dict:
    return {"claims": [], "counts": {s: 0 for s in STATUSES},
            "sources": [{"url": u, "own": False, "claims": []} for u in links or []],
            "works_checked": 0, "model": model, "reason": reason}


def article_claims(text: str, *, title: str | None = None, user_id: str | None = None, db=None) -> dict:
    """What a draft claims, and what each claim leans on."""
    from AINDY.config import settings
    from AINDY.kernel.circuit_breaker import CircuitOpenError
    from AINDY.platform_layer.external_call_service import perform_external_call
    from AINDY.platform_layer.openai_client import chat_completion
    from apps._shared.provider_keys import llm_client, raise_key_problem
    from apps.rippletrace.public import extract_links

    model = _model()
    article = (text or "").strip()
    if not article:
        return _empty("no article text supplied", model)
    links = extract_links(article)
    client = llm_client(user_id, db=db)  # whose key pays (FR-59); a 402, never a quiet empty result
    try:
        truth = _owner_truth(user_id, db)
    except Exception as exc:
        logger.warning("[SEO] claims: the writer's Works could not be read: %s", exc)
        return _empty("your Works could not be read", model, links)

    heading = f'The writer\'s title: "{title}"\n\n' if title else ""
    user = f"{build_context(truth, links)}\n\n---\n\n{heading}THE DRAFT\n{article[:MAX_ARTICLE_CHARS_SENT]}"
    try:
        completion = perform_external_call(
            service_name="openai",
            db=db,
            user_id=user_id,
            endpoint="chat.completions.create",
            model=model,
            method="openai.chat",
            extra={"purpose": "seo_article_claims"},
            operation=lambda: chat_completion(
                client,
                model=model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                timeout=max(float(settings.OPENAI_CHAT_TIMEOUT_SECONDS or 0), 120.0),
                **_sampling(model),
            ),
        )
    except CircuitOpenError:
        logger.warning("[SEO] article claims unavailable: OpenAI circuit open")
        return _empty("the claims service is temporarily unavailable", model, links)
    except Exception as exc:
        raise_key_problem(exc)
        logger.warning("[SEO] article claims failed: %s", exc)
        return _empty("the claims service could not be reached", model, links)

    result = parse_response(completion.choices[0].message.content, article, truth, links)
    if not result["claims"]:
        return {**_empty("no claims were returned", model, links), "sources": result["sources"],
                "works_checked": len(truth["works"])}
    result.update({"works_checked": len(truth["works"]), "model": model, "reason": None,
                   "truncated_input": len(article) > MAX_ARTICLE_CHARS_SENT})
    return result
