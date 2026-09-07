"""Title candidates, proposed from the article and measured against the SERP budget.

The SEO tool had no way to produce a title, and no LLM anywhere — `generate_meta_description`
is deterministic trimming, not authorship (`TITLE_AS_CONTAINER_SPEC.md` §6a). Both of those
change here, on the owner's call: *"yes and yes — the tool may not call an LLM currently, but
that's always been in the plans."*

★ **This proposes; it never replaces.** `SEO_EDITING_AID_SPEC` exists because a tool that
rewrites the author's work stops being an aid, and a title generator is the feature where that
line is easiest to cross. Two things enforce it rather than describe it:

* the writer's own title is **input, never output** — it is passed as context so candidates can
  keep their conventions, and it is returned untouched in every response;
* there is no "best" candidate, no auto-apply field, and no single-title shape a client could
  drop straight into the input. A list of options requires a person to choose one.

★ **And it fails honestly.** Every other generator here has a deterministic fallback. This one
must not: a fallback title assembled from word frequencies would arrive looking exactly like a
model's suggestion, and the writer would have no way to tell a proposal from a shrug. When the
model is unavailable the answer is an empty list and a stated reason.
"""

from __future__ import annotations

import json
import logging
import re

from AINDY.config import settings
from AINDY.kernel.circuit_breaker import CircuitOpenError
from AINDY.platform_layer.external_call_service import perform_external_call
from AINDY.platform_layer.openai_client import chat_completion, get_openai_client

from apps.search.services.seo_services import TITLE_CHAR_BUDGET, TITLE_CHAR_MIN, analyze_title

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

DEFAULT_CANDIDATE_COUNT = 5
MAX_CANDIDATE_COUNT = 8

# How much of the article the model is shown. A title is decided by what the piece is about,
# which is established early; sending 40,000 characters to choose a 60-character line is paying
# for tokens that change nothing. Bounded input is also the rule every other external call here
# follows (`MAX_IMPORT_CHARS`, `MAX_TRANSCRIPT_CHARS_SENT`).
MAX_ARTICLE_CHARS_SENT = 6000

SYSTEM_PROMPT = """You are helping a writer title an article they have already written.

Your job is to propose options, not to decide. The writer picks one, edits one, or ignores
all of them.

Rules:
- Every title must be supported by the article. Do not introduce a claim, a number, a name or
  a result that is not in the text you were given.
- Aim for {budget} characters or fewer. Search results cut the rest. Below {minimum} leaves
  room unused.
- Make the options genuinely different from each other — different angles, not the same title
  with words swapped. A list of near-duplicates is one option pretending to be five.
- Plain language. No clickbait, no "Ultimate Guide", no manufactured urgency, no emoji.
- If the writer supplied a current title, follow its conventions where they are deliberate —
  a series name or recurring prefix is theirs to keep. Do not preserve its wording otherwise.
- If target keywords are given, work them in only where they fit naturally. A title that reads
  as keyword placement is worse than one that reads well.

Return ONLY valid JSON in this exact format:

{{"titles": ["...", "...", "..."]}}"""


def _user_prompt(
    text: str, *, count: int, existing_title: str | None, target_keywords: list[str] | None
) -> str:
    parts = [f"Propose {count} title options for this article."]
    if existing_title:
        parts.append(f'The writer\'s current title: "{existing_title}"')
    if target_keywords:
        parts.append("Target keywords: " + ", ".join(target_keywords))
    parts.append("---")
    parts.append(text[:MAX_ARTICLE_CHARS_SENT])
    return "\n\n".join(parts)


def _parse_titles(content: str) -> list[str]:
    """Pull the title list out of the response, tolerating a model that adds prose.

    Returns `[]` rather than raising: an unparseable response is the same situation as an
    unavailable one, and both must end in "no suggestions" rather than in something invented.
    """
    text = (content or "").strip()
    if not text.startswith("{"):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return []
        text = match.group(0)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    titles = payload.get("titles")
    if not isinstance(titles, list):
        return []
    return [item for item in titles if isinstance(item, str) and item.strip()]


def _dedupe(titles: list[str]) -> list[str]:
    """Drop exact repeats, case- and whitespace-insensitively.

    Not near-duplicate detection — the prompt asks for genuinely different angles and a
    similarity threshold here would be the tool deciding which of the writer's options are
    worth seeing. This only removes the case where the same string arrives twice.
    """
    seen: set[str] = set()
    out: list[str] = []
    for title in titles:
        cleaned = " ".join(title.split())
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def generate_title_candidates(
    text: str,
    *,
    count: int = DEFAULT_CANDIDATE_COUNT,
    existing_title: str | None = None,
    target_keywords: list[str] | None = None,
    user_id: str | None = None,
    db=None,
) -> dict:
    """Propose title options for an article, each measured against the SERP budget.

    Every candidate is measured by the same `analyze_title` the scorecard uses, so a proposal
    and the writer's own title are reported on identical terms. Candidates within budget are
    listed first; over-budget ones are **kept and marked** rather than dropped, because a
    silently shortened list would hide that the model overshot, and a writer may well prefer a
    long option they intend to trim.
    """
    # `None` means "unspecified" and takes the default; any supplied number is clamped. Folding
    # the two together with `or` would silently turn a requested 0 into 5, which is a different
    # answer from the one asked for.
    requested = DEFAULT_CANDIDATE_COUNT if count is None else int(count)
    count = max(1, min(requested, MAX_CANDIDATE_COUNT))
    article = (text or "").strip()
    if not article:
        return _empty("no article text supplied", existing_title)

    system_prompt = SYSTEM_PROMPT.format(budget=TITLE_CHAR_BUDGET, minimum=TITLE_CHAR_MIN)
    try:
        completion = perform_external_call(
            service_name="openai",
            db=db,
            user_id=user_id,
            endpoint="chat.completions.create",
            model=MODEL,
            method="openai.chat",
            extra={"purpose": "seo_title_generation", "count": count},
            operation=lambda: chat_completion(
                get_openai_client(),
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": _user_prompt(
                            article,
                            count=count,
                            existing_title=existing_title,
                            target_keywords=target_keywords,
                        ),
                    },
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
                timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
            ),
        )
    except CircuitOpenError:
        logger.warning("[SEO] title generation unavailable — OpenAI circuit open")
        return _empty("the title service is temporarily unavailable", existing_title)
    except Exception as exc:
        logger.warning("[SEO] title generation failed: %s", exc)
        return _empty("the title service could not be reached", existing_title)

    titles = _dedupe(_parse_titles(completion.choices[0].message.content))
    if not titles:
        return _empty("no usable suggestions were returned", existing_title)

    candidates = [analyze_title(title) for title in titles[:count]]
    # Within budget first, then by length. Ordering is a convenience, not a verdict — every
    # candidate carries its own measurement and the over-budget ones stay on the list.
    candidates.sort(key=lambda item: (item["over_by"] > 0, item["characters"]))

    return {
        "candidates": candidates,
        "count": len(candidates),
        "budget": TITLE_CHAR_BUDGET,
        # Echoed back untouched. The writer's title is input to this function and never output
        # from it; returning it here is what lets a client show "yours" beside the options
        # without ever having received a replacement for it.
        "current_title": existing_title or "",
        "reason": None,
    }


def _empty(reason: str, existing_title: str | None) -> dict:
    """No suggestions, and why.

    ★ Deliberately not a fallback. A deterministic title built from word frequencies would be
    indistinguishable from a model's proposal in the UI, and the writer would have no way to
    tell a suggestion from a failure. Saying nothing is the honest answer.
    """
    return {
        "candidates": [],
        "count": 0,
        "budget": TITLE_CHAR_BUDGET,
        "current_title": existing_title or "",
        "reason": reason,
    }
