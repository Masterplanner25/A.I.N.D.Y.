"""The owner's published writing, stored and recallable — `WORK_MODEL_SPEC.md` §5, phase B.

Until 2026-09-30 the system knew 214 pieces by title and url and nothing they said: the feeds carried
the text, ingestion kept a 2,000-character summary, and memory recall returned telemetry about the
writing instead of the writing. The load-bearing properties: a feed body is kept only when it is the
article; a piece's text is fetched from its platform and bounded; a platform with no text, or a piece
that is gone, is marked and not asked again, while a transient failure is retried; the text becomes
memory chunks tagged with the piece, its series and the owner's Work; and memory is rewritten only
when the text changes.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AINDY_ALLOW_SQLITE", "1")

from AINDY.db.database import Base
from AINDY.db.models.user import User
from tests.helpers.app_profile import bootstrap_app_models
from tests.helpers.runtime import import_runtime_model_registry

pytestmark = pytest.mark.app_profile

ARTICLE = ("<p>Search engines now answer questions.</p><p>" + "An argument about AI search. " * 80 + "</p>"
           "<h2>What it means</h2><p>" + "The consequence for authors. " * 60 + "</p>")


@pytest.fixture()
def db():
    import_runtime_model_registry()
    bootstrap_app_models(required=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def owner(db):
    uid = uuid.uuid4()
    db.add(User(id=uid, email=f"{uid}@example.com", hashed_password="x", is_active=True))
    db.commit()
    return uid


def _drop(db, owner, platform, slug, *, title=None, series=""):
    from apps.rippletrace.drop import DropPointDB

    hosts = {"DEV": "https://dev.to/masterplanner25/", "Substack": "https://masterplanner25.substack.com/p/",
             "Medium": "https://medium.com/masterplan-infinite-weave/", "YouTube": "https://www.youtube.com/watch?v="}
    row = DropPointDB(id=f"dp-{slug}", title=title or slug.replace("-", " ").title(), platform=platform,
                      url=hosts[platform] + slug, date_dropped=datetime(2025, 3, 1), user_id=owner,
                      tagged_entities=series, core_themes="")
    db.add(row)
    db.commit()
    return row


# ── step 1: keep what the feed carries ────────────────────────────────────────────────────


def test_a_feed_body_is_kept_only_when_it_is_the_article(db, owner):
    from apps.rippletrace.services.content_archive import keep_feed_content

    row = _drop(db, owner, "Substack", "ai-search")
    assert keep_feed_content(row, "<p>Read more on Substack</p>") is False  # an excerpt
    assert keep_feed_content(row, ARTICLE) is True
    assert (row.content_source, len(row.content_hash)) == ("feed", 64)
    assert "Search engines now answer questions.\n\nAn argument" in row.content_text
    assert keep_feed_content(row, ARTICLE) is False  # unchanged


def test_the_feed_parser_carries_the_fullest_body():
    from apps.rippletrace.services.content_fetch import parse_feed

    rss = ('<?xml version="1.0"?><rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
           '<item><title>A</title><link>https://s.example/p/a</link><description>short</description>'
           '<content:encoded><![CDATA[<p>the whole article</p>]]></content:encoded></item>'
           '<item><title>B</title><link>https://dev.to/u/b</link><description>&lt;p&gt;DEV puts it all here&lt;/p&gt;</description></item>'
           '</channel></rss>')
    entries = parse_feed(rss, "https://s.example/feed").entries
    assert [e.content for e in entries] == ["<p>the whole article</p>", "<p>DEV puts it all here</p>"]


# ── step 2: backfill ──────────────────────────────────────────────────────────────────────


def test_backfill_fetches_marks_and_retries_as_it_should(db, owner):
    from apps.rippletrace.services.content_archive import backfill_content

    dev = _drop(db, owner, "DEV", "case-study")
    video = _drop(db, owner, "YouTube", "abc123")
    gone = _drop(db, owner, "Substack", "deleted-post")
    flaky = _drop(db, owner, "Medium", "slow-post")

    def substack(row):
        raise RuntimeError("That URL returned HTTP 404 — the page was not found. Check the link.")

    def medium(row):
        raise RuntimeError("That site returned HTTP 503, which is a fault on their end.")

    fetchers = {"DEV": lambda row: "# Case study\n\n" + "Markdown body. " * 200, "Substack": substack, "Medium": medium}
    out = backfill_content(db, user_id=str(owner), fetchers=fetchers, pause=0)

    assert out == {"fetched": 1, "none": 2, "failed": 1}
    assert (dev.content_source, video.content_source, gone.content_source, flaky.content_source) == ("api", "none", "none", None)
    # the transient one is asked again next run; the others are not
    again = backfill_content(db, user_id=str(owner), fetchers=fetchers, pause=0)
    assert again == {"fetched": 0, "none": 0, "failed": 1}


def test_a_piece_is_bounded():
    from apps.rippletrace.drop import DropPointDB
    from apps.rippletrace.services.content_archive import CONTENT_MAX_CHARS, store_content

    row = DropPointDB(id="x")
    store_content(row, "word " * 20_000, "api")
    assert len(row.content_text) <= CONTENT_MAX_CHARS


# ── step 3: remember ──────────────────────────────────────────────────────────────────────


def test_chunks_follow_paragraphs_and_stay_bounded():
    from apps.rippletrace.services.content_archive import CHUNK_CHARS, chunk_text, to_text

    chunks = chunk_text(to_text(ARTICLE))
    assert len(chunks) > 1 and all(len(c) <= CHUNK_CHARS for c in chunks)
    assert chunks[0].startswith("Search engines now answer questions.")


def test_memory_carries_the_piece_its_series_and_its_work_and_is_rewritten_only_on_change(db, owner, monkeypatch):
    import AINDY.platform_layer.registry as registry
    from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
    from apps.rippletrace.container import ContainerDB
    from apps.rippletrace.services.content_archive import archive_status, remember_content, store_content

    container = ContainerDB(user_id=owner, name="2025 ChatGPT Case Study Series",
                            normalized="2025 chatgpt case study series", status="confirmed")
    db.add(container)
    db.commit()
    monkeypatch.setattr(registry, "get_job", lambda name: (
        (lambda *, user_id, db: {container.id: ["2025 ChatGPT Case Study Series"]})
        if name == "masterplan.works_by_container" else None))

    row = _drop(db, owner, "DEV", "virality-formula", title="2025 ChatGPT Case Study Series: Virality Formula",
                series="2025 ChatGPT Case Study Series")
    store_content(row, "\n\n".join(["A paragraph about virality. " * 40] * 3), "api")
    db.commit()

    first = remember_content(db, user_id=str(owner))
    nodes = MemoryNodeDAO(db).get_by_tags([f"drop:{row.id}"], limit=50, user_id=str(owner))
    assert first["remembered"] == 1 and len(nodes) == first["chunks"] > 1
    assert {"published_work", "dev", "series:2025 ChatGPT Case Study Series",
            "work:2025 ChatGPT Case Study Series"} <= set(nodes[0]["tags"])
    assert nodes[0]["content"].startswith("2025 ChatGPT Case Study Series: Virality Formula (DEV, 2025-03-01; part ")
    assert remember_content(db, user_id=str(owner)) == {"remembered": 0, "chunks": 0}  # unchanged

    store_content(row, "A rewritten piece, much shorter.", "api")
    db.commit()
    assert remember_content(db, user_id=str(owner))["chunks"] == 1
    assert len(MemoryNodeDAO(db).get_by_tags([f"drop:{row.id}"], limit=50, user_id=str(owner))) == 1

    status = archive_status(db, user_id=str(owner))
    assert (status["pieces"], status["stored"], status["recallable"], status["pending"]) == (1, 1, 1, 0)
