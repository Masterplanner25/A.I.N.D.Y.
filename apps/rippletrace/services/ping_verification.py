"""Does the page that came back actually cite you?

`RIPPLE-PINGS-NOT-ECHOES-1` / `docs/verification/DEFECT_RIPPLE_PINGS_ARE_NOT_ECHOES.md`.

RippleTrace's detection searches for a drop point's URL plus its distinctive title as an exact
phrase — the right query. The provider is an **answer engine**, which does not return pages
containing a phrase; it answers the question and returns the sources it used. Those are
topically related by construction and are almost never the piece searched for.

Measured on the live corpus 2026-09-07: **1 of 256 pings pointed at a URL plausibly connected
to the author.** `openai.com` was the most common "platform that echoed you", 36 times.

★ **The fix is to look.** Fetch the candidate and check whether it contains the drop point's URL
or its title. That is the only thing that turns a citation into an echo, and it cannot be
approximated by tuning the query, the result cap or the threshold — all three sit downstream of
an instrument that answers a different question.

★ **And to be honest when looking is impossible.** Some publishers refuse scripted requests
(`_BLOCKED_STATUSES` — 401/403/405/406/429/451), which is why feed subscription exists at all.
A page that cannot be fetched is `unverified`, not rejected: *"we looked and it does not cite
you"* and *"we could not look"* are different answers, and only the first is evidence. Scoring
counts `verified` alone, so an unverifiable ping is carried without inflating anything.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from apps.rippletrace.services.content_fetch import (
    ContentFetchError,
    fetch_url,
    normalize_url,
    strip_html,
)

logger = logging.getLogger(__name__)

# The three states a ping can be in. `rejected` exists as a value but is never stored — a
# candidate that demonstrably fails verification is not written at all, because a page that
# does not cite you is not a ripple. The constant is here so the vocabulary is in one place and
# so `_verify_hit` can report the outcome it reached.
VERIFIED = "verified"
UNVERIFIED = "unverified"
REJECTED = "rejected"

# ★ The default for every row that predates this feature, set by the migration. The existing
# 256 pings are correctly-recorded answers to a different question — labelling them is honest,
# deleting them would silently rewrite history the engines have already reasoned over, which is
# the same reasoning that keeps a dismissed container's tags in place.
DEFAULT_VERIFICATION = UNVERIFIED

# A title has to be long enough that finding it on a page means something. Shorter than this
# and a match is a coincidence — the same reasoning as `MIN_DISTINCTIVE_TITLE_CHARS` in
# detection, applied to the other end of the pipe.
MIN_TITLE_MATCH_CHARS = 25

# One fetch per candidate is the cost of this feature, and detection can produce up to 200
# candidates per run (10 drop points x 20 results). This bounds a single run so verification
# cannot turn a background job into an outbound crawl. Anything beyond it is left `unverified`
# rather than skipped, so the ping still exists and simply does not score.
MAX_VERIFICATIONS_PER_RUN = 60

_WHITESPACE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return _WHITESPACE.sub(" ", (text or "").lower()).strip()


def _url_variants(url: str) -> set[str]:
    """The forms a link to this page plausibly takes on someone else's site.

    A page citing you might write the canonical URL, the same URL without a scheme, or with a
    trailing slash. Matching only the exact normalized form would call a real echo unverified.
    """
    if not url:
        return set()
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    bare = f"{parsed.netloc}{parsed.path}".rstrip("/")
    return {
        variant
        for variant in (
            normalized.lower(),
            normalized.lower().rstrip("/"),
            bare.lower(),
            bare.lower().lstrip("www."),
        )
        if variant
    }


def page_cites(page_text: str, *, drop_url: str, drop_title: str | None) -> bool:
    """True when this page contains the drop point's URL or its title.

    Either is sufficient. A link is the strongest evidence, but plenty of genuine echoes name
    a piece without linking it, and requiring the link would discard those.
    """
    haystack = _normalize_text(page_text)
    if not haystack:
        return False

    for variant in _url_variants(drop_url):
        if variant and variant in haystack:
            return True

    title = _normalize_text(drop_title or "")
    if len(title) >= MIN_TITLE_MATCH_CHARS and title in haystack:
        return True
    return False


def verify_hit(
    *, hit_url: str, drop_url: str, drop_title: str | None, db=None, user_id: str | None = None
) -> tuple[str, str | None]:
    """Fetch the candidate and decide. Returns ``(state, reason)``.

    Never raises. Verification is an improvement to a detection run that already works, and a
    fetch failure must not lose the ping — it downgrades it to `unverified`, which is exactly
    what a fetch failure means.
    """
    if not hit_url or not drop_url:
        return UNVERIFIED, "nothing to check against"

    try:
        result = fetch_url(hit_url, db=db, user_id=user_id)
    except ContentFetchError as exc:
        # Includes the blocked statuses. The publisher refuses scripted requests; that is a
        # fact about them, not evidence about whether they cited you.
        return UNVERIFIED, str(exc)[:200]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[rippletrace] verification fetch failed for %s: %s", hit_url, exc)
        return UNVERIFIED, "fetch failed"

    text = strip_html(result.text or "")
    if not text.strip():
        # A page that renders its body in JavaScript returns nothing useful here. Saying "it
        # does not cite you" from an empty fetch would be a confident wrong answer.
        return UNVERIFIED, "no readable text"

    if page_cites(text, drop_url=drop_url, drop_title=drop_title):
        return VERIFIED, None
    return REJECTED, "page does not reference the drop point"
