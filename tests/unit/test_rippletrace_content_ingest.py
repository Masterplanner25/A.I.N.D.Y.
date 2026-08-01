"""Content ingestion for rippletrace: URL safety, feed parsing, idempotent drop points.

The SSRF cases are the ones that matter most here. ``/apps/rippletrace/ingest`` makes
the server fetch a URL the user chose, so the guard in ``assert_public_url`` is the
difference between an ingestion feature and a request-forgery primitive aimed at the
container's own network.
"""

from __future__ import annotations

import os
import socket
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

from AINDY.db.database import Base
from tests.helpers.app_profile import bootstrap_app_models
from tests.helpers.runtime import import_runtime_model_registry

pytestmark = pytest.mark.app_profile

content_fetch = pytest.importorskip("apps.rippletrace.services.content_fetch")
content_ingest = pytest.importorskip("apps.rippletrace.services.content_ingest")


def _build_session():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )()


def _resolves_to(monkeypatch, address: str) -> None:
    """Pin DNS so the SSRF tests never touch the network."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port or 80))]

    monkeypatch.setattr(content_fetch.socket, "getaddrinfo", fake_getaddrinfo)


# ── URL normalization ─────────────────────────────────────────────────────────


def test_normalize_url_strips_tracking_and_fragment():
    normalized = content_fetch.normalize_url(
        "HTTPS://WWW.Example.com:443/posts/hello/?utm_source=newsletter&id=7&fbclid=xyz#section"
    )
    assert normalized == "https://www.example.com/posts/hello?id=7"


def test_normalize_url_keeps_meaningful_query():
    # For plenty of sites the query *is* the document; only known trackers go.
    assert (
        content_fetch.normalize_url("https://example.com/watch?v=abc123")
        == "https://example.com/watch?v=abc123"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.linkedin.com/posts/xyz", "LinkedIn"),
        ("https://shawn.substack.com/p/thing", "Substack"),
        ("https://youtu.be/abc", "YouTube"),
        ("https://x.com/someone/status/1", "X"),
        ("https://notaknownsite.dev/post", "notaknownsite.dev"),
    ],
)
def test_infer_platform(url, expected):
    assert content_fetch.infer_platform(url) == expected


# ── SSRF guard ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com",
        "javascript:alert(1)",
    ],
)
def test_assert_public_url_rejects_non_http_schemes(url):
    with pytest.raises(content_fetch.ContentFetchError):
        content_fetch.assert_public_url(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",       # loopback
        "10.0.0.5",        # private
        "192.168.1.10",    # private
        "172.16.4.4",      # private
        "169.254.169.254",  # cloud metadata — the classic SSRF target
        "0.0.0.0",         # unspecified
        "::1",             # IPv6 loopback
        "fd00::1",         # IPv6 unique-local
    ],
)
def test_assert_public_url_rejects_internal_addresses(monkeypatch, address):
    _resolves_to(monkeypatch, address)
    with pytest.raises(content_fetch.ContentFetchError):
        content_fetch.assert_public_url("https://internal.example.com/x")


def test_assert_public_url_rejects_embedded_credentials(monkeypatch):
    _resolves_to(monkeypatch, "93.184.216.34")
    with pytest.raises(content_fetch.ContentFetchError):
        content_fetch.assert_public_url("https://user:pass@example.com/x")


def test_assert_public_url_accepts_public_address(monkeypatch):
    _resolves_to(monkeypatch, "93.184.216.34")
    assert content_fetch.assert_public_url("https://example.com/post") == (
        "https://example.com/post"
    )


def test_assert_public_url_rejects_unresolvable_host(monkeypatch):
    def boom(*args, **kwargs):
        raise socket.gaierror("nope")

    monkeypatch.setattr(content_fetch.socket, "getaddrinfo", boom)
    with pytest.raises(content_fetch.ContentFetchError):
        content_fetch.assert_public_url("https://does-not-exist.example/x")


# ── Streamed body reading ─────────────────────────────────────────────────────


class _FakeStreamedResponse:
    """A streamed requests.Response stand-in.

    ``apparent_encoding`` raises on purpose: on a real streamed response it reads
    ``response.content``, which is unavailable once ``iter_content`` has drained the
    body. Touching it is exactly the mistake this guards against.
    """

    def __init__(self, chunks, encoding=None):
        self._chunks = chunks
        self.encoding = encoding
        self.headers = {}

    def iter_content(self, chunk_size=16384):
        yield from self._chunks

    @property
    def apparent_encoding(self):
        raise RuntimeError("The content for this response was already consumed")


def test_read_capped_does_not_touch_apparent_encoding():
    response = _FakeStreamedResponse([b"<rss>", b"body", b"</rss>"])
    assert content_fetch._read_capped(response) == "<rss>body</rss>"


def test_read_capped_honours_declared_encoding():
    response = _FakeStreamedResponse(["café".encode("latin-1")], encoding="latin-1")
    assert content_fetch._read_capped(response) == "café"


def test_read_capped_rejects_oversized_body():
    oversized = [b"x" * 65536] * ((content_fetch.MAX_RESPONSE_BYTES // 65536) + 2)
    with pytest.raises(content_fetch.ContentFetchError):
        content_fetch._read_capped(_FakeStreamedResponse(oversized))


# ── Feed parsing ──────────────────────────────────────────────────────────────


RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Shawn's Notes</title>
    <link>https://notes.example.com</link>
    <item>
      <title>Systems that measure achievement</title>
      <link>https://notes.example.com/p/achievement</link>
      <pubDate>Tue, 15 Jul 2026 09:30:00 GMT</pubDate>
      <category>strategy</category>
      <category>measurement</category>
      <description>&lt;p&gt;Why activity is not progress.&lt;/p&gt;</description>
    </item>
    <item>
      <title>Second post</title>
      <link>https://notes.example.com/p/second</link>
      <pubDate>Wed, 16 Jul 2026 11:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Journal</title>
  <link rel="alternate" href="https://atom.example.com/"/>
  <entry>
    <title>An atom entry</title>
    <link rel="alternate" href="https://atom.example.com/entries/1"/>
    <published>2026-07-20T08:00:00Z</published>
    <category term="research"/>
    <summary>A summary.</summary>
  </entry>
</feed>
"""


def test_parse_rss_feed():
    feed = content_fetch.parse_feed(RSS_FIXTURE, "https://notes.example.com/feed")
    assert feed.title == "Shawn's Notes"
    assert len(feed.entries) == 2
    first = feed.entries[0]
    assert first.url == "https://notes.example.com/p/achievement"
    assert first.title == "Systems that measure achievement"
    assert first.tags == ["strategy", "measurement"]
    assert first.published_at == datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)


def test_parse_atom_feed():
    feed = content_fetch.parse_feed(ATOM_FIXTURE, "https://atom.example.com/feed")
    assert feed.title == "Atom Journal"
    assert len(feed.entries) == 1
    entry = feed.entries[0]
    assert entry.url == "https://atom.example.com/entries/1"
    assert entry.tags == ["research"]
    assert entry.published_at == datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def test_parse_feed_rejects_html():
    with pytest.raises(content_fetch.ContentFetchError):
        content_fetch.parse_feed("<html><body>not a feed</body></html>", "https://x.example")


# ── HTML metadata ─────────────────────────────────────────────────────────────


HTML_FIXTURE = """<!doctype html>
<html><head>
  <title>Fallback Title</title>
  <meta property="og:title" content="The Real Title"/>
  <meta property="og:site_name" content="Substack"/>
  <meta property="og:description" content="A description of the post."/>
  <meta property="article:published_time" content="2026-06-01T12:00:00Z"/>
  <meta property="article:tag" content="Infinity"/>
  <meta name="keywords" content="planning, measurement"/>
  <link rel="canonical" href="/p/canonical-path"/>
  <link rel="alternate" type="application/rss+xml" href="/feed"/>
</head><body>Body text</body></html>
"""


def test_parse_page_metadata_prefers_opengraph_and_finds_feed():
    meta = content_fetch.parse_page_metadata(HTML_FIXTURE, "https://blog.example.com/p/post")
    assert meta.title == "The Real Title"
    assert meta.site_name == "Substack"
    assert meta.published_at == datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    assert meta.tags == ["Infinity", "planning", "measurement"]
    assert meta.canonical_url == "https://blog.example.com/p/canonical-path"
    assert meta.feed_urls == ["https://blog.example.com/feed"]


def test_parse_page_metadata_falls_back_to_title_tag():
    meta = content_fetch.parse_page_metadata(
        "<html><head><title>Just a title</title></head></html>", "https://x.example/a"
    )
    assert meta.title == "Just a title"
    assert meta.feed_urls == []


# ── Theme derivation ──────────────────────────────────────────────────────────


def test_derive_themes_prefers_publisher_tags():
    themes = content_ingest.derive_themes(
        title="Anything at all", summary="Words here", tags=["Strategy", "Measurement"]
    )
    assert themes == ["strategy", "measurement"]


def test_derive_themes_falls_back_to_keywords_without_stopwords():
    themes = content_ingest.derive_themes(
        title="Measuring achievement in the system",
        summary="The system should measure achievement and not activity.",
        tags=[],
    )
    assert "the" not in themes
    assert "in" not in themes
    # Title terms are weighted double, so they lead the ranking.
    assert "achievement" in themes
    assert "system" in themes


# ── Idempotent ingestion ──────────────────────────────────────────────────────


def test_drop_point_id_is_stable_and_user_scoped():
    user_a, user_b = str(uuid.uuid4()), str(uuid.uuid4())
    canonical = content_ingest.drop_point_id_for(user_a, "https://example.com/p/one")
    # Tracking params and a fragment are not part of a document's identity.
    with_noise = content_ingest.drop_point_id_for(
        user_a, "https://example.com/p/one/?utm_campaign=x#top"
    )
    assert canonical == with_noise
    assert content_ingest.drop_point_id_for(user_b, "https://example.com/p/one") != canonical


def test_upsert_drop_point_is_idempotent():
    session = _build_session()
    user_id = str(uuid.uuid4())
    try:
        row, created = content_ingest.upsert_drop_point(
            session,
            user_id=user_id,
            url="https://notes.example.com/p/achievement",
            title="Systems that measure achievement",
            tags=["strategy"],
            published_at=datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc),
        )
        session.commit()
        assert created is True
        assert row.platform == "notes.example.com"
        assert row.core_themes == "strategy"

        # Re-polling a feed re-presents the same entry; it must update, not duplicate.
        again, created_again = content_ingest.upsert_drop_point(
            session,
            user_id=user_id,
            url="https://notes.example.com/p/achievement?utm_source=rss",
            title="Systems that measure achievement (revised)",
            tags=["strategy", "measurement"],
        )
        session.commit()
        assert created_again is False
        assert again.id == row.id
        assert again.title.endswith("(revised)")

        DropPointDB = content_ingest.DropPointDB
        assert session.query(DropPointDB).count() == 1
    finally:
        session.close()


def test_upsert_leaves_date_null_when_the_source_has_none():
    """An unknown publication date must stay unknown, not become "now".

    Echo detection rejects results that predate the drop point. Stamping ingestion time
    onto an undated page makes almost the entire web look like prior art, so detection
    finds nothing for that page — forever, and silently.
    """
    session = _build_session()
    try:
        row, _ = content_ingest.upsert_drop_point(
            session,
            user_id=str(uuid.uuid4()),
            url="https://example.com/undated",
            title="No date on this one",
        )
        session.commit()
        assert row.date_dropped is None

        dated, _ = content_ingest.upsert_drop_point(
            session,
            user_id=str(uuid.uuid4()),
            url="https://example.com/dated",
            title="This one has a date",
            published_at=datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
        )
        session.commit()
        # Stored naive-UTC, because date_dropped is a legacy naive column.
        assert dated.date_dropped == datetime(2026, 5, 4, 12, 0)
    finally:
        session.close()


def test_upsert_leaves_ripple_scores_untouched():
    """Scores belong to threadweaver and are computed from pings.

    A freshly ingested publication has no ripple yet; writing a placeholder score here
    would manufacture one and feed the strategy threshold with fiction.
    """
    session = _build_session()
    try:
        row, _ = content_ingest.upsert_drop_point(
            session,
            user_id=str(uuid.uuid4()),
            url="https://example.com/p/new",
            title="New",
        )
        session.commit()
        assert row.narrative_score is None
        assert row.velocity_score is None
        assert row.spread_score is None
    finally:
        session.close()
