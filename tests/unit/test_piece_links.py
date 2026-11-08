"""ARTICLE_ANSWERS_SPEC phase B1: a piece keeps the links its writer made (decision 2, 2026-11-08).

`to_text` turns a fetched body into plain text and strips HTML with its hrefs, so every Substack and
Medium piece had lost its links. `content_links` keeps them from the raw body.
"""

from __future__ import annotations

import uuid

import pytest

from apps.rippletrace.models import DropPointDB
from apps.rippletrace.services import content_archive
from apps.rippletrace.services.links import extract_links

pytestmark = pytest.mark.app_profile


# ── Reading links ─────────────────────────────────────────────────────────────────────


def test_markdown_links_but_not_images():
    text = ("See [part one](https://dev.to/me/one) and ![diagram](https://img.example/d.png). "
            "Also https://medium.com/@me/three?source=rss----x---4. Again [one](https://dev.to/me/one).")
    assert extract_links(text) == ["https://dev.to/me/one", "https://medium.com/@me/three?source=rss----x---4"]


def test_html_takes_hrefs_and_text_urls_never_tag_attributes():
    html = ('<p>Read <a href="https://me.substack.com/p/two">two</a>.</p>'
            '<img src="https://cdn.example/i.png"><script src="https://evil.example/s.js"></script>'
            "<p>Also https://example.org/x.</p>")
    assert extract_links(html) == ["https://me.substack.com/p/two", "https://example.org/x"]


# ── Keeping them ──────────────────────────────────────────────────────────────────────


def _row(db, owner, platform, url, text=None, links=None):
    row = DropPointDB(id=f"dp-{uuid.uuid4().hex[:10]}", title="A piece", platform=platform, url=url,
                      core_themes="", tagged_entities="", intent="published", user_id=owner)
    if text is not None:
        content_archive.store_content(row, text, "api")
    row.content_links = links
    db.add(row)
    db.commit()
    return row


def test_links_are_kept_even_when_the_text_is_unchanged():
    row = DropPointDB(id="dp-x", title="t", platform="Substack", url="https://me.substack.com/p/x")
    body = "<p>" + "Words. " * 200 + '<a href="https://me.substack.com/p/y">y</a></p>'
    assert content_archive.store_content(row, content_archive.to_text(body), "api",
                                         links=content_archive.piece_links(body)) is True
    row.content_links = None
    # Same text again: not a change, but the links are still kept.
    assert content_archive.store_content(row, content_archive.to_text(body), "api",
                                         links=content_archive.piece_links(body)) is False
    assert row.content_links == ["https://me.substack.com/p/y"]


def test_a_feed_body_keeps_its_links():
    row = DropPointDB(id="dp-f", title="t", platform="Medium", url="https://medium.com/@me/f")
    body = "<p>" + "Words. " * 300 + '<a href="https://dev.to/me/earlier">the earlier part</a></p>'
    assert content_archive.keep_feed_content(row, body) is True
    assert row.content_links == ["https://dev.to/me/earlier"]


def test_backfill_reads_dev_from_text_and_fetches_the_rest(db_session):
    owner, other = uuid.uuid4(), uuid.uuid4()
    dev = _row(db_session, owner, "DEV", "https://dev.to/me/a", text="Read [b](https://dev.to/me/b) first. " * 30)
    substack = _row(db_session, owner, "Substack", "https://me.substack.com/p/s", text="Plain text. " * 30)
    medium = _row(db_session, owner, "Medium", "https://medium.com/@me/m", text="Old piece. " * 30)
    broken = _row(db_session, owner, "Substack", "https://me.substack.com/p/broken", text="More. " * 30)
    done = _row(db_session, owner, "Substack", "https://me.substack.com/p/done", text="Done. " * 30, links=["https://x"])
    theirs = _row(db_session, other, "DEV", "https://dev.to/them/t", text="[x](https://dev.to/them/u) " * 30)

    fetched = []

    def substack_fetch(row):
        fetched.append(row.id)
        if row.id == broken.id:
            raise RuntimeError("HTTP 503")
        return "<p>" + "Plain text. " * 30 + '<a href="https://dev.to/me/a">a</a></p>'

    out = content_archive.backfill_links(
        db_session, user_id=owner, pause=0,
        fetchers={"Substack": substack_fetch, "Medium": lambda row: None},
    )
    for row in (dev, substack, medium, broken, done, theirs):
        db_session.refresh(row)

    assert dev.content_links == ["https://dev.to/me/b"]
    assert substack.content_links == ["https://dev.to/me/a"]
    assert medium.content_links is None  # the feed no longer carries it: left unread, not emptied
    assert broken.content_links is None
    assert done.content_links == ["https://x"]  # already had links: not touched
    assert theirs.content_links is None  # another user's piece is never read
    assert done.id not in fetched
    assert out["DEV"]["from_text"] == 1
    assert out["Substack"] == {"from_text": 0, "fetched": 1, "unavailable": 0, "failed": 1}
    assert out["Medium"]["unavailable"] == 1
