"""What's the structure? (ARTICLE_ANSWERS_SPEC §5, phase D2, decided 2026-11-08).

**The goal (owner): reveal that there is a structure in the first place.** Not whether it is deliberate, and never a
grade. Three parts:

* ``structure_report`` (free, no model; the SEO tool calls it after every analysis):
  * the **skeleton**: sections in order with their share of the words, how the piece opens and how it closes;
  * **repeated openings**: sentences that start the same way, every instance quoted. Digits are folded, so "Phase 1 —",
    "Phase 2 —" and "Phase 3 —" are one pattern;
  * the **repeats** from the old repetition panel (`editing_aid.repetition_report`), folded in (decision 11): a repeated
    phrase that lives inside one opening pattern is shown as part of it, the rest on their own.
* ``series_shape`` (free): beside the draft, what its series' published pieces share: headings that recur, how they
  open and close, and their usual length. Side by side, never a score (decision 9).
* ``name_patterns`` (one gpt-5.5 call, on a button, the writer's key): the patterns named, such as contrast, lists,
  naming sequences and refrains, with every instance quoted and checked against the text. A pattern needs two
  instances found in the text, or it is dropped.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from statistics import median
from typing import Any

logger = logging.getLogger(__name__)

# ── the free pass ───────────────────────────────────────────────────────────────────────

_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_HTML_HEADING = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
_BOLD_LINE = re.compile(r"^\s*(?:\*\*|__)(.+?)(?:\*\*|__)\s*$")
_TAG = re.compile(r"<[^>]+>")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.-]*")

OPENING_WORDS_TWO = 3      # two-word openings need three sentences to be a pattern
OPENING_WORDS_THREE = 2    # three-word openings need two
MAX_OPENINGS = 10
MAX_INSTANCES = 8
EXCERPT_CHARS = 220
QUOTE_CHARS = 180


def _plain(line: str) -> str:
    return " ".join(_TAG.sub(" ", _MD_LINK.sub(r"\1", line)).replace("**", "").replace("__", "").split())


def _words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def _blocks(text: str) -> list[tuple[str, str]]:
    """The draft as ("heading" | "para", plain text) blocks, in order."""
    body = _HTML_HEADING.sub(lambda m: "\n\n# " + _plain(m.group(1)) + "\n\n", text or "")
    body = re.sub(r"</?(p|div|br|li|ul|ol|blockquote)[^>]*>", "\n\n", body, flags=re.IGNORECASE)
    blocks: list[tuple[str, str]] = []
    for chunk in re.split(r"\n\s*\n", body):
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        para: list[str] = []
        for line in lines:
            heading = _MD_HEADING.match(line) or _BOLD_LINE.match(line)
            if heading and len(_words(heading.group(1))) <= 14:
                if para:
                    blocks.append(("para", _plain(" ".join(para))))
                    para = []
                blocks.append(("heading", _plain(heading.group(1))))
            else:
                para.append(line)
        if para:
            text_ = _plain(" ".join(para))
            if text_:
                blocks.append(("heading" if _looks_like_heading(text_, len(para)) else "para", text_))
    return blocks


def _looks_like_heading(text: str, lines: int) -> bool:
    """A short standalone paragraph with no closing sentence punctuation ("What's Next?" is allowed its "?").
    Platform feeds (Medium, Substack) drop heading markup, so a published piece's headings arrive as exactly
    this; without it every stored piece reads as one section (measured 2026-11-08: 3,017 words, 1 section)."""
    words = _words(text)
    return lines == 1 and 1 <= len(words) <= 10 and not re.search(r"[.!,;:…\"”’)]\s*$", text)


def skeleton(text: str) -> dict:
    """Sections in order with their share of the words; how the piece opens and closes."""
    blocks = _blocks(text)
    sections: list[dict] = []
    current = {"heading": None, "words": 0, "paragraphs": 0}
    for kind, content in blocks:
        if kind == "heading":
            if current["heading"] is not None or current["words"]:
                sections.append(current)
            current = {"heading": content, "words": 0, "paragraphs": 0}
        else:
            current["words"] += len(_words(content))
            current["paragraphs"] += 1
    if current["heading"] is not None or current["words"]:
        sections.append(current)
    total = sum(s["words"] for s in sections) or 1
    for section in sections:
        section["share"] = round(section["words"] / total * 100, 1)
    paras = [c for k, c in blocks if k == "para"]
    return {
        "sections": sections,
        "words": sum(s["words"] for s in sections),
        "paragraphs": len(paras),
        "opening": (paras[0][:EXCERPT_CHARS] if paras else ""),
        "closing": (paras[-1][:EXCERPT_CHARS] if paras else ""),
        "closing_heading": next((s["heading"] for s in reversed(sections) if s["heading"]), None),
    }


def sentences(text: str) -> list[str]:
    """The draft's sentences (headings are not sentences)."""
    out: list[str] = []
    for kind, content in _blocks(text):
        if kind == "para":
            out += [s.strip() for s in _SENTENCE_SPLIT.split(content) if len(_words(s)) >= 2]
    return out


def _opening_key(sentence: str, width: int) -> str | None:
    words = [w.lower().strip(".'’-") for w in _words(sentence)[:width]]
    if len(words) < width or not all(words):
        return None
    return " ".join("#" if w.isdigit() else w for w in words)


def repeated_openings(all_sentences: list[str]) -> list[dict]:
    """Sentences that start the same way, every instance quoted; a three-word opening is kept over the two-word
    opening it narrows when it covers the same sentences."""
    groups: dict[tuple[int, str], list[int]] = {}
    for index, sentence in enumerate(all_sentences):
        for width in (2, 3):
            key = _opening_key(sentence, width)
            if key:
                groups.setdefault((width, key), []).append(index)
    found = []
    for (width, key), members in groups.items():
        if len(members) >= (OPENING_WORDS_THREE if width == 3 else OPENING_WORDS_TWO):
            found.append({"opening": key.replace("#", "N"), "width": width, "members": members})
    kept = []
    for item in sorted(found, key=lambda f: (-f["width"], -len(f["members"]))):
        if item["width"] == 2 and any(set(item["members"]) == set(k["members"]) for k in kept):
            continue
        kept.append(item)
    kept.sort(key=lambda f: (-len(f["members"]), f["opening"]))
    return [{"opening": k["opening"], "count": len(k["members"]),
             "instances": [all_sentences[i][:QUOTE_CHARS] for i in k["members"][:MAX_INSTANCES]],
             "_members": k["members"]}
            for k in kept[:MAX_OPENINGS]]


def fold_repeats(repetition: dict, openings: list[dict], all_sentences: list[str]) -> dict:
    """The repetition report's phrases, each either inside one opening pattern (every use is in its sentences) or
    on its own. Overused words and one-word sentence openers stay as they were."""
    lowered = [" ".join(_words(s)).lower() for s in all_sentences]
    standalone = []
    for phrase in repetition.get("repeated_phrases") or []:
        needle = phrase["phrase"]
        home = None
        for pattern in openings:
            inside = sum(lowered[i].count(needle) for i in pattern["_members"])
            if inside and inside >= phrase["occurrences"]:
                home = pattern
                break
        if home is not None:
            home.setdefault("repeats", []).append({"phrase": needle, "occurrences": phrase["occurrences"]})
        else:
            standalone.append(phrase)
    return {"phrases": standalone, "overused_words": repetition.get("overused_words") or [],
            "single_word_openers": repetition.get("sentence_openers") or []}


def structure_report(text: str) -> dict:
    """The free pass: skeleton, repeated openings, and the old repetition report folded in."""
    from apps.search.services.editing_aid import repetition_report

    all_sentences = sentences(text)
    openings = repeated_openings(all_sentences)
    repeats = fold_repeats(repetition_report(text or ""), openings, all_sentences)
    for pattern in openings:
        pattern.pop("_members", None)
        pattern.setdefault("repeats", [])
    return {"skeleton": skeleton(text), "openings": openings, "repeats": repeats}


# ── the series beside it ────────────────────────────────────────────────────────────────


def _norm_heading(heading: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9#? ]", " ", re.sub(r"\d+", "#", heading.lower())).split())


def series_shape(pieces: list[dict], draft_skeleton: dict) -> dict:
    """What the series' pieces share: recurring headings (in at least half of them), recurring openings and
    closings of the first and last paragraph, the usual closing heading, and the usual length. Beside each shared
    heading, whether the draft has it: information, never a score."""
    shapes = [skeleton(p.get("text") or "") for p in pieces if (p.get("text") or "").strip()]
    n = len(shapes)
    if n < 2:
        return {"pieces": n, "headings": [], "openings": [], "closings": [], "closing_heading": None,
                "median_words": shapes[0]["words"] if n else None, "median_sections": len(shapes[0]["sections"]) if n else None}
    threshold = max(2, (n + 1) // 2)
    heading_counts: Counter = Counter()
    labels: dict[str, str] = {}
    for shape in shapes:
        seen = set()
        for section in shape["sections"]:
            if section["heading"]:
                key = _norm_heading(section["heading"])
                if key and key not in seen:
                    seen.add(key)
                    heading_counts[key] += 1
                    labels.setdefault(key, section["heading"])
    draft_headings = {_norm_heading(s["heading"]) for s in draft_skeleton["sections"] if s["heading"]}
    headings = [{"heading": labels[k], "pieces": c, "in_draft": k in draft_headings}
                for k, c in heading_counts.most_common() if c >= threshold]

    def recurring(texts: list[str]) -> list[dict]:
        counts: Counter = Counter()
        sample: dict[str, str] = {}
        for t in texts:
            key = _opening_key(t, 3) or _opening_key(t, 2)
            if key:
                counts[key] += 1
                sample.setdefault(key, t[:QUOTE_CHARS])
        return [{"starts": k.replace("#", "N"), "pieces": c, "example": sample[k]} for k, c in counts.most_common(5)
                if c >= threshold]

    closing_heads = Counter(_norm_heading(s["closing_heading"]) for s in shapes if s["closing_heading"])
    top_close = closing_heads.most_common(1)
    close_key = top_close[0][0] if top_close and top_close[0][1] >= threshold else None
    return {
        "pieces": n,
        "headings": headings,
        "openings": recurring([s["opening"] for s in shapes]),
        "closings": recurring([s["closing"] for s in shapes]),
        "closing_heading": ({"heading": next(s["closing_heading"] for s in shapes
                                             if s["closing_heading"] and _norm_heading(s["closing_heading"]) == close_key),
                             "pieces": top_close[0][1],
                             "in_draft": _norm_heading(draft_skeleton.get("closing_heading") or "") == close_key}
                            if close_key else None),
        "median_words": int(median(s["words"] for s in shapes)),
        "median_sections": int(median(len(s["sections"]) for s in shapes)),
    }


def structure_with_series(text: str, *, title: str | None, series: str | None, user_id: Any, db) -> dict:
    """The free pass plus the draft's series beside it (the route's whole answer)."""
    from apps.rippletrace.public import series_pieces

    report = structure_report(text)
    try:
        found = series_pieces(db, user_id, title=title, series=series, exclude_title=title)
    except Exception as exc:  # the draft's own structure stands without its series
        logger.warning("[SEO] structure: series could not be read: %s", exc)
        found = {"series": None, "options": [], "pieces": []}
    report["series"] = {
        "name": found.get("series"),
        "options": found.get("options") or [],
        "shape": series_shape(found.get("pieces") or [], report["skeleton"]) if found.get("series") else None,
        "titles": [p["title"] for p in found.get("pieces") or []][:12],
    }
    return report


# ── naming the patterns (one model call, on a button) ───────────────────────────────────

MODEL = "gpt-5.5"
REASONING_EFFORT = "low"
REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")
REASONING_MAX_TOKENS = 16_000
MAX_ARTICLE_CHARS_SENT = 60_000
MAX_PATTERNS = 12
KINDS = ("contrast", "list", "naming_sequence", "refrain", "parallel", "question_answer", "other")

SYSTEM_PROMPT = """You read a draft and REVEAL ITS STRUCTURE: the patterns the writing repeats. The writer often cannot
see them in their own text. Do not judge whether a pattern is good, bad, deliberate or accidental. Do not suggest changes.

Find the patterns that occur at least twice. Kinds:
- "contrast": a set-up and its turn ("It wasn't X. It was Y.", "Not A, but B").
- "list": the same construction repeated as a run ("It could inspect... It could search... It could identify...").
- "naming_sequence": numbered or named steps ("Phase 1 — ...", "Phase 2 — ...").
- "refrain": a line or phrase that returns across the piece.
- "parallel": sentences or paragraphs built the same way without sharing words.
- "question_answer": a question the text asks and then answers itself.
- "other": a structure that fits none of these.

For each pattern:
- "name": a few words naming it, as a reader would ("the 'It wasn't X. It was Y.' turn").
- "kind": one of the kinds above.
- "instances": each occurrence, the sentence or short passage COPIED EXACTLY, word for word. At least two.

At most 12 patterns, the clearest first. Return ONLY valid JSON:
{"patterns": [{"name": "...", "kind": "...", "instances": ["...", "..."]}]}"""


def _model() -> str:
    return (os.getenv("AINDY_STRUCTURE_MODEL") or "").strip() or MODEL


def _sampling(model: str) -> dict:
    """gpt-5.x refuses `max_tokens` and any temperature but 1 (see CLAUDE.md, content.draft)."""
    if model.startswith(REASONING_PREFIXES):
        effort = (os.getenv("AINDY_STRUCTURE_REASONING_EFFORT") or "").strip() or REASONING_EFFORT
        return {"max_completion_tokens": REASONING_MAX_TOKENS, "reasoning_effort": effort}
    return {"temperature": 0.2, "max_tokens": 4000}


def parse_patterns(content: str, article: str) -> list[dict]:
    """The model's patterns, each instance checked against the text; a pattern with fewer than two instances found
    in the text is dropped, since one instance is not a pattern."""
    from apps.rippletrace.public import fold_text, passage_in

    raw = (content or "").strip()
    if not raw.startswith("{"):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        raw = match.group(0) if match else ""
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    folded = fold_text(article)
    patterns = []
    for item in payload.get("patterns") or []:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())
        kind = str(item.get("kind") or "").strip().lower().replace(" ", "_")
        instances = [" ".join(str(i).split()) for i in item.get("instances") or [] if isinstance(i, str) and i.strip()]
        found = [i for i in dict.fromkeys(instances) if passage_in(i, folded)]
        if not name or len(found) < 2:
            continue
        patterns.append({"name": name, "kind": kind if kind in KINDS else "other",
                         "instances": [i[:QUOTE_CHARS * 2] for i in found[:MAX_INSTANCES]],
                         "dropped_instances": len(set(instances)) - len(found)})
        if len(patterns) >= MAX_PATTERNS:
            break
    return patterns


def name_patterns(text: str, *, title: str | None = None, user_id: Any = None, db=None) -> dict:
    """The draft's patterns, named. Fails honestly: on any failure ``reason`` is set and the list is empty."""
    from AINDY.config import settings
    from AINDY.kernel.circuit_breaker import CircuitOpenError
    from AINDY.platform_layer.external_call_service import perform_external_call
    from AINDY.platform_layer.openai_client import chat_completion
    from apps._shared.provider_keys import llm_client, raise_key_problem

    model = _model()
    article = (text or "").strip()
    if not article:
        return {"patterns": [], "model": model, "reason": "no article text supplied"}
    client = llm_client(user_id, db=db)  # whose key pays (FR-59); a 402, never a quiet empty result
    heading = f'The writer\'s title: "{title}"\n\n' if title else ""
    try:
        completion = perform_external_call(
            service_name="openai", db=db, user_id=user_id, endpoint="chat.completions.create", model=model,
            method="openai.chat", extra={"purpose": "seo_structure_patterns"},
            operation=lambda: chat_completion(
                client, model=model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": heading + article[:MAX_ARTICLE_CHARS_SENT]}],
                timeout=max(float(settings.OPENAI_CHAT_TIMEOUT_SECONDS or 0), 120.0),
                **_sampling(model),
            ),
        )
    except CircuitOpenError:
        logger.warning("[SEO] structure patterns unavailable: OpenAI circuit open")
        return {"patterns": [], "model": model, "reason": "the structure service is temporarily unavailable"}
    except Exception as exc:
        raise_key_problem(exc)
        logger.warning("[SEO] structure patterns failed: %s", exc)
        return {"patterns": [], "model": model, "reason": "the structure service could not be reached"}
    patterns = parse_patterns(completion.choices[0].message.content, article)
    return {"patterns": patterns, "model": model,
            "reason": None if patterns else "no patterns with two instances in the text were returned",
            "truncated_input": len(article) > MAX_ARTICLE_CHARS_SENT}
