"""Declared worth, extracted from what the user said in Genesis — and dropped if they didn't.

The Worth axis of the Infinity score has had **0 declarations** since it was built. The model,
the per-kind scoring and the API all exist and are correct; nothing ever called them, because
there was no way for a person to say the number
(`TECH_DEBT.md` → `SOAK-THEN-FLIP-1`, `docs/specs/WORTH_DECLARATION_IN_GENESIS_SPEC.md`).

A blank "declare worth" panel is the obvious remedy and the wrong one. Homework gets filled in
to make the form go away, and a Worth axis fed by dutiful guesses is not uncalibrated — it is
*confidently wrong*, which is strictly worse than the honest zero it replaces. Genesis is where
the owner is already saying what matters and why, so the number can be a by-product of meaning
something rather than a field.

★ **The whole risk is that an LLM asked to fill in a worth field will fill it in.** If Genesis
decides a domain is `critical` because that reads plausibly, the fabricated row is
indistinguishable from a real one and nothing downstream can detect it. This repo has already
shipped that failure once in a different costume — `SOAK_AUDIT_2026-08-15` §3 found a learned
calibrator "winning" by memorising a constant, reported as a 0.0000 MAE.

So the defence that matters is not an instruction, it is this module: **every declaration must
carry the user's own words, and those words must be found in a user turn of the transcript, or
the declaration is dropped before it is ever written.** Prompt rules drift between model
versions; a substring check does not.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

logger = logging.getLogger(__name__)

# ── The worth vocabulary, held here rather than imported ──────────────────────────────
#
# Analytics owns the contract; masterplan reaches it through `sys.v1.analytics.declare_worth`
# and does not import `apps.analytics.*` — `test_masterplan_bootstrap_keeps_only_identity_as_
# direct_app_dependency` pins that, and the syscall migration that produced it is why
# masterplan's task and automation integrations are call-time syscalls too.
#
# So these are restated, and `test_worth_vocabulary_matches_analytics` fails if the two ever
# disagree. Validating locally is the point: a declaration with an invalid kind or level should
# be dropped at extraction, in the turn it was made, rather than raised from a syscall at lock
# — by which time the words that would have let anyone check it are three screens up.
VALID_WORTH_KINDS = frozenset({"monetary_potential", "intrinsic", "strategic"})
ORDINAL_WORTH_KINDS = frozenset({"intrinsic", "strategic"})
CARDINAL_WORTH_KINDS = frozenset({"monetary_potential"})
WORTH_ORDINAL_LEVELS = frozenset({"low", "moderate", "high", "critical"})

WORTH_STATE_KEY = "declared_worth"

# Below this, a "quote" is too short to be evidence of anything — "it", "yes", "critical" would
# all match some user turn by accident. Long enough to be a phrase, short enough that a brief
# but real statement ("that one is critical") still qualifies.
MIN_QUOTE_CHARS = 12

# ★ Agreement is not a declaration, and this only became reachable once Genesis started ASKING.
#
# While worth was volunteered, a user turn was a statement and quoting it was safe. Now the
# likely reply to "is the framework critical?" is "yeah, that one" — which is 14 characters,
# clears MIN_QUOTE_CHARS, and traces to a genuine user turn, so `user_turns` does not catch it
# either. The declaration's actual meaning lives in the ASSISTANT's question, which is exactly
# what this module exists to refuse.
#
# The rule: a quote made entirely of agreement and pointing words is agreement, not a statement.
# One content word is enough to pass — "that one is critical" is a real, brief declaration and
# must survive — so this rejects only the case where the user contributed no content at all.
_ASSENT_TOKENS = frozenset({
    "yeah", "yes", "yep", "yup", "sure", "ok", "okay", "right", "correct", "true",
    "exactly", "definitely", "absolutely", "agreed", "indeed", "no", "nope", "maybe",
    "that", "this", "those", "these", "them", "they", "it", "its", "one", "ones",
    "the", "a", "an", "both", "all", "and", "or", "too", "also", "same", "is", "are",
    "was", "were", "be", "i", "you", "we", "of", "to", "for", "on", "in", "at", "so",
})
_WORD = re.compile(r"[a-z0-9$]+")

# The model is told to elide with an ellipsis rather than paraphrase. Each fragment is then
# checked independently, which keeps a genuine quote verifiable without demanding that the user
# said one unbroken sentence.
_ELLIPSIS = re.compile(r"\.{3,}|…")
_WHITESPACE = re.compile(r"\s+")
# Smart quotes and the straight ones, stripped from the ends so a quoted quote still matches.
_EDGE_QUOTES = "\"'“”‘’ \t\n"


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, and neutralise the punctuation an LLM re-types.

    Quoting is a retyping operation, and models normalise apostrophes and dashes while doing
    it. Matching on the raw string would reject real quotes for a curly apostrophe, which
    would make quote-or-drop discard everything and look like the feature does not work.
    """
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-")
    return _WHITESPACE.sub(" ", text.lower()).strip()


def user_turns(transcript: list[dict] | None) -> list[str]:
    """The user's own words only.

    ★ The assistant's turns are excluded deliberately, and this is the load-bearing line of the
    module. Genesis reflects understanding back in its own words by design, so its replies are
    full of plausible-sounding statements about what matters. Accepting a quote from an
    assistant turn would let the model quote *itself* into a declaration — fabrication with a
    citation, which is worse than fabrication without one.
    """
    if not transcript:
        return []
    return [
        entry["content"]
        for entry in transcript
        if isinstance(entry, dict)
        and entry.get("role") == "user"
        and isinstance(entry.get("content"), str)
        and entry["content"]
    ]


def quote_is_supported(quote: str | None, transcript: list[dict] | None) -> bool:
    """True when the user actually said this.

    Every ellipsis-separated fragment must appear in **one** user turn — not spread across
    several. A quote assembled from words the user said on different days is not a quote.
    """
    if not isinstance(quote, str):
        return False
    fragments = [_normalize(part).strip(_EDGE_QUOTES) for part in _ELLIPSIS.split(quote)]
    fragments = [fragment for fragment in fragments if fragment]
    if not fragments:
        return False
    if sum(len(fragment) for fragment in fragments) < MIN_QUOTE_CHARS:
        return False

    if not _carries_content(fragments):
        return False

    turns = [_normalize(turn) for turn in user_turns(transcript)]
    return any(all(fragment in turn for fragment in fragments) for turn in turns)


def _carries_content(fragments: list[str]) -> bool:
    """At least one word in the quote must be the user's own contribution.

    A number counts — "worth 50000" is a declaration whose only content word is the figure.
    """
    words = [word for fragment in fragments for word in _WORD.findall(fragment)]
    return any(word not in _ASSENT_TOKENS for word in words)


def _clean_label(label: Any) -> str | None:
    if not isinstance(label, str):
        return None
    cleaned = _WHITESPACE.sub(" ", label).strip()
    return cleaned[:200] or None


def normalize_entry(entry: Any) -> dict[str, Any] | None:
    """Validate one extracted declaration, or return None.

    Rejects rather than coerces. An `intrinsic` worth of `8` is not "high" — accepting it would
    let the false precision the ordinal scale exists to remove back in through the side door,
    and silently.
    """
    if not isinstance(entry, dict):
        return None

    kind = str(entry.get("kind") or "").strip().lower()
    if kind not in VALID_WORTH_KINDS:
        return None

    raw_value = entry.get("value")
    if kind in ORDINAL_WORTH_KINDS:
        level = str(raw_value or "").strip().lower()
        if level not in WORTH_ORDINAL_LEVELS:
            return None
        value: Any = level
    elif kind in CARDINAL_WORTH_KINDS:
        if isinstance(raw_value, bool):
            return None
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None
        if value < 0:
            return None
    else:  # pragma: no cover - VALID_WORTH_KINDS is the union of the two sets
        return None

    quote = entry.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        return None

    return {
        "label": _clean_label(entry.get("label")),
        "kind": kind,
        "value": value,
        "quote": quote.strip()[:600],
    }


def _key(entry: dict[str, Any]) -> tuple[str, str]:
    return ((entry.get("label") or "").lower(), entry["kind"])


def merge_declared_worth(
    existing: Any, incoming: Any, transcript: list[dict] | None
) -> list[dict[str, Any]]:
    """Accumulate verified declarations across turns; a later statement about the same thing wins.

    ★ Not a replacement, unlike every other field in `summarized_state`, and the difference is
    not cosmetic. Each turn's extraction reports what *that turn* established, so a turn about
    something else returns an empty list. Replacing on every turn would erase every declaration
    the moment the conversation moved on — the field would appear to work in a single-turn test
    and hold nothing by the time the plan locked.

    ★ **Verification happens here, on the turn the words arrive**, not only at lock. The stored
    transcript is trimmed to its most recent entries, so a quote from early in a long session
    can stop being findable later — verifying only at lock would silently discard a real
    declaration for a reason that has nothing to do with whether the user said it.

    `verified` is set by this function alone. `normalize_entry` rebuilds each entry from
    `label`/`kind`/`value`/`quote` only, so a model that emits `"verified": true` in its own
    output has that discarded before it is looked at — the flag cannot be self-awarded.

    The key is (label, kind), which is the same key the DB upserts on, so re-stating a domain's
    strategic worth updates it while its monetary potential is left alone.
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    # Prior entries: already verified by an earlier pass through this function, against a
    # transcript that still contained the turn. Their flag is carried, not re-derived.
    if isinstance(existing, list):
        for raw in existing:
            entry = normalize_entry(raw)
            if entry is None:
                continue
            entry["verified"] = bool(isinstance(raw, dict) and raw.get("verified"))
            merged[_key(entry)] = entry

    if isinstance(incoming, list):
        for raw in incoming:
            entry = normalize_entry(raw)
            if entry is None:
                continue
            entry["verified"] = quote_is_supported(entry["quote"], transcript)
            merged[_key(entry)] = entry

    return list(merged.values())


def supported_declarations(
    declared_worth: Any, transcript: list[dict] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split declarations into (supported, dropped) by whether the user's words back them.

    An entry already carrying `verified` was checked against the transcript on the turn it was
    extracted (see `merge_declared_worth`) and is taken at its word. Anything else — state
    written before this feature existed, or edited by hand — is checked here.
    """
    supported: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    if not isinstance(declared_worth, list):
        return supported, dropped
    for raw in declared_worth:
        entry = normalize_entry(raw)
        if entry is None:
            if isinstance(raw, dict):
                dropped.append(dict(raw))
            continue
        already_verified = isinstance(raw, dict) and bool(raw.get("verified"))
        if already_verified or quote_is_supported(entry["quote"], transcript):
            supported.append(entry)
        else:
            dropped.append(entry)
    return supported, dropped


def _declare_worth(db, *, user_id, **payload) -> dict[str, Any]:
    """Hand one declaration to analytics through its syscall."""
    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id),
        capabilities=["analytics.write"],
        trace_id="",
        metadata={"_db": db},
    )
    result = get_dispatcher().dispatch(
        "sys.v1.analytics.declare_worth", {**payload, "user_id": str(user_id)}, ctx
    )
    # Lowercase syscall envelope, not the uppercase flow one. Since runtime 2.9.0 the values
    # are success | partial | unknown | error.
    if result.get("status") != "success":
        raise RuntimeError(result.get("error") or "declare_worth syscall failed")
    return result.get("data") or {}


def record_genesis_declarations(
    db,
    *,
    user_id: Any,
    masterplan_id: Any,
    declared_worth: Any,
    transcript: list[dict] | None,
) -> dict[str, Any]:
    """Write the supported declarations at lock, and report exactly what was written.

    A declaration with a label is about a **domain** — the thing Genesis actually talks about.
    One without a label is about the plan itself.

    Never raises. Locking a MasterPlan is the user's act and must not fail because a worth row
    did not persist; the return value carries the count and the drops so the caller can say so.
    """
    supported, dropped = supported_declarations(declared_worth, transcript)

    recorded: list[dict[str, Any]] = []
    for entry in supported:
        label = entry["label"]
        if label:
            target_type, target_id = "domain", label.lower()
        else:
            target_type, target_id = "masterplan", str(masterplan_id)
        try:
            _declare_worth(
                db,
                user_id=user_id,
                target_type=target_type,
                target_id=target_id,
                label=label,
                kind=entry["kind"],
                declared_value=entry["value"],
                # The quote is the audit trail. Stored so a declaration stays checkable after
                # the session it came from has scrolled out of the transcript window.
                note='Declared in Genesis: "{}"'.format(entry["quote"]),
            )
        except Exception as exc:
            logger.warning(
                "[Genesis] worth declaration not recorded (%s/%s, %s): %s",
                target_type,
                target_id,
                entry["kind"],
                exc,
            )
            dropped.append(entry)
            continue
        recorded.append(entry)

    if dropped:
        logger.info(
            "[Genesis] %d worth declaration(s) dropped - unsupported by the transcript",
            len(dropped),
        )
    return {"recorded": recorded, "dropped": dropped}
