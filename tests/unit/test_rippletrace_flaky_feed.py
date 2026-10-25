"""A feed that has worked before and answers 404 or 5xx is retried within the poll, and if it still
fails it reads `unavailable` with a message that says the link is fine — not "check the link".

Found 2026-10-25: YouTube's `feeds/videos.xml` for the owner's channel answered 404 404 404 200 404 in
five tries while the channel page loaded, so an hourly poll of one request showed a source that had
ingested 15 videos as a broken link.
"""
from __future__ import annotations

import uuid

import pytest

from apps.rippletrace.models import ContentSourceDB
from apps.rippletrace.services import content_ingest
from apps.rippletrace.services.content_fetch import ContentFetchError, FetchResult

pytestmark = pytest.mark.app_profile

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxxxxxxxxxxxxxxxxxxxx"
EMPTY_FEED = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Knight</title></feed>"""


def _source(db, *, ingested=15):
    row = ContentSourceDB(id=str(uuid.uuid4()), user_id=None, feed_url=FEED, site_url=FEED,
                          title="Knight", platform="YouTube", kind="feed", active=True,
                          ingested_count=ingested, last_entry_count=ingested)
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def answers(monkeypatch):
    """The feed's answers in order: an int is an HTTP error status, "ok" is a readable empty feed."""
    script, calls = [], []
    monkeypatch.setattr(content_ingest, "FLAKY_RETRY_DELAYS", (0.0, 0.0))

    def fetch(url, **kwargs):
        calls.append(url)
        answer = script.pop(0)
        if answer == "ok":
            return FetchResult(url=url, status_code=200, content_type="application/atom+xml", text=EMPTY_FEED,
                               etag=None, last_modified=None)
        raise ContentFetchError(f"HTTP {answer}", status_code=answer)

    monkeypatch.setattr(content_ingest, "fetch_url", fetch)
    return script, calls


def test_a_404_then_200_is_ok_within_one_poll(db_session, answers):
    script, calls = answers
    script += [404, 404, "ok"]
    source = _source(db_session)
    assert content_ingest.poll_source(db_session, source)["status"] == "ok"
    assert len(calls) == 3 and source.last_status == "ok" and source.last_error is None


def test_a_working_feed_that_keeps_failing_is_unavailable_not_a_broken_link(db_session, answers):
    script, calls = answers
    script += [404, 404, 404]
    source = _source(db_session)
    result = content_ingest.poll_source(db_session, source)
    assert result["status"] == "unavailable" and len(calls) == 3
    assert "has worked before (15 items)" in source.last_error and "Check the link" not in source.last_error


def test_a_5xx_is_retried_too(db_session, answers):
    script, calls = answers
    script += [503, "ok"]
    assert content_ingest.poll_source(db_session, _source(db_session))["status"] == "ok" and len(calls) == 2


def test_a_feed_that_never_worked_gets_the_plain_error_on_one_try(db_session, answers):
    script, calls = answers
    script += [404]
    source = _source(db_session, ingested=0)
    assert content_ingest.poll_source(db_session, source)["status"] == "error"
    assert len(calls) == 1 and source.last_error == "HTTP 404"


def test_a_403_is_not_retried(db_session, answers):
    script, calls = answers
    script += [403]
    source = _source(db_session)
    assert content_ingest.poll_source(db_session, source)["status"] == "error" and len(calls) == 1
