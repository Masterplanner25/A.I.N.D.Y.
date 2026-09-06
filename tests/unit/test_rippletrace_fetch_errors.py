"""A blocked page must point at the feed, not just report the status code.

The owner pasted a published article URL into RippleTrace ingestion on 2026-09-06 and got:

    API Error (422): {"detail":{"error":"content_fetch_failed",
                      "message":"That URL returned HTTP 403."}}

Accurate, and a dead end. It reads as *your link is broken* when the link is fine — the
publisher simply refuses scripted requests.

**Measured the same day, and the measurement corrected two wrong guesses:**

* Not the User-Agent. The article returned **200** with RippleTrace's own
  `AINDY-RippleTrace/1.0` UA before it returned 403.
* Not the container, the egress IP, or the HTTP client. Host and container share a public
  IP, and `curl` from the container failed the same way `requests` did.
* It is **volume/behaviour-based**: the same URL, machine, client and IP returned 200 twice
  and then 403 within a minute. No header change can fix that.

**The recovery is real rather than a consolation.** That publication's RSS feed returned
**200 from both host and container** while the article page was 403 — a feed is a document
publishers intend machines to read. And RippleTrace is built for it:
`ingest_url` classifies what you paste, and *"a feed becomes a subscription; a page becomes
one drop point"* — so the feed is both the thing that works and the better outcome, because
it ingests every future post rather than this one.

Normally `ingest_url` discovers the feed for the user from the page's `<link rel=alternate>`
and returns `suggested_feeds`. A block breaks exactly that path — no page, no discovered
feed — so the error message has to carry the advice the page would have carried.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

content_fetch = pytest.importorskip("apps.rippletrace.services.content_fetch")
_status_error_message = content_fetch._status_error_message


@pytest.mark.parametrize("code", [401, 403, 405, 406, 429, 451])
def test_a_blocked_status_names_the_feed_as_the_way_through(code):
    """Every status that means "we refuse scripted requests" must offer the recovery."""
    message = _status_error_message(code)

    assert "feed" in message.lower(), f"HTTP {code} left the user with no next step: {message}"
    assert str(code) in message, "the status is still worth stating, just not on its own"


def test_the_403_message_no_longer_reads_as_a_broken_link():
    """The exact failure the owner hit."""
    message = _status_error_message(403)

    assert message != "That URL returned HTTP 403."
    # It must attribute the refusal to the publisher, not to the user's URL.
    assert "blocks automated" in message
    # And it must say why the feed is the better outcome, not merely an alternative.
    assert "future post" in message


def test_a_404_is_still_the_users_link_and_says_so():
    """Not everything is a block. A 404 genuinely is a bad URL and must not suggest a feed.

    Blurring these would train the user to ignore the advice.
    """
    message = _status_error_message(404)

    assert "not found" in message.lower()
    assert "feed" not in message.lower()


def test_a_server_error_is_attributed_to_the_publisher_and_invites_a_retry():
    message = _status_error_message(503)

    assert "their end" in message
    assert "retry" in message.lower()
    assert "feed" not in message.lower(), "a 5xx is transient; a feed is not the fix"


def test_an_unclassified_status_still_reports_something_true():
    """The fallback must stay honest rather than guessing at a cause."""
    message = _status_error_message(418)

    assert "418" in message
    assert "feed" not in message.lower()


def test_rate_limiting_is_treated_as_a_block_not_a_server_fault():
    """429 is the status most likely to be hit by repeated ingestion attempts.

    Classifying it as a 5xx-style "retry later" would send the user back into the same wall.
    """
    assert "feed" in _status_error_message(429).lower()
    assert "their end" not in _status_error_message(429)
