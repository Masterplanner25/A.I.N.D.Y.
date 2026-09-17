"""Recording a citation the author found — verified before it counts.

`RIPPLE-PINGS-NOT-ECHOES-1`, decided 2026-09-16: the paid mention sweep is retired (the
instrument costs more than the signal is worth — three citations in eighteen months, all found
by accident). The author records the page; the system fetches it and applies the SAME verifier
detection used. The three outcomes are the verifier's three, and the middle one is the one worth
defending: an author's say-so about a page we cannot read is kept as `unverified`, never promoted.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.rippletrace.drop import DropPointDB, PingDB
from apps.rippletrace.services import citation_record as cr
from apps.rippletrace.services.content_fetch import ContentFetchError
from apps.rippletrace.services.ripple_detection import ping_id_for

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
DROP_URL = "https://masterplanner25.substack.com/p/ethics-and-accountability"
DROP_TITLE = "2025 ChatGPT Case Study Series: Ethics and Accountability"
CITING_URL = "https://example.org/roundup/ai-ethics-reading-list"


def _drop(db):
    row = DropPointDB(
        id=f"dp-{uuid.uuid4()}", title=DROP_TITLE, platform="Substack", url=DROP_URL,
        date_dropped=datetime(2026, 1, 1), core_themes="", tagged_entities="",
        intent="published", user_id=USER,
    )
    db.add(row)
    db.commit()
    return row


def _page(html: str):
    return type("R", (), {"text": html, "status_code": 200})()


def _serve(monkeypatch, html: str):
    monkeypatch.setattr(cr, "fetch_url", lambda url, **kw: _page(html))


def test_a_page_that_cites_the_piece_is_recorded_verified_and_scores(db_session, monkeypatch):
    drop = _drop(db_session)
    _serve(monkeypatch, f"<html><title>AI ethics reading list</title><body>See {DROP_URL} for the full argument.</body></html>")

    out = cr.record_citation(db_session, drop_point=drop, url=CITING_URL, user_id=str(USER))

    assert out["verification"] == "verified" and out["created"] is True
    row = db_session.query(PingDB).filter(PingDB.id == out["ping_id"]).one()
    assert row.ping_type == cr.PING_TYPE_CITATION
    assert row.verification == "verified"
    assert row.verification_note == cr.RECORDED_BY_AUTHOR
    assert row.connection_summary == "AI ethics reading list"
    assert row.id == ping_id_for(drop.id, CITING_URL), "same identity a sweep would produce"
    # It scores — the whole point of a verified ping.
    db_session.refresh(drop)
    assert (drop.narrative_score or 0) > 0


def test_a_page_that_does_not_cite_is_refused_and_nothing_is_written(db_session, monkeypatch):
    drop = _drop(db_session)
    _serve(monkeypatch, "<html><body>A long essay about AI ethics that never mentions the piece.</body></html>")

    with pytest.raises(cr.NotACitation):
        cr.record_citation(db_session, drop_point=drop, url=CITING_URL, user_id=str(USER))
    assert db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).count() == 0


def test_a_page_that_cannot_be_read_is_kept_unverified_and_does_not_score(db_session, monkeypatch):
    """The author's say-so is not evidence; a 403 is a fact about the publisher."""
    drop = _drop(db_session)

    def _blocked(url, **kw):
        raise ContentFetchError("publisher refuses scripted fetches (403)")

    monkeypatch.setattr(cr, "fetch_url", _blocked)
    out = cr.record_citation(db_session, drop_point=drop, url=CITING_URL, user_id=str(USER))

    assert out["verification"] == "unverified"
    assert "403" in (out["note"] or "")
    db_session.refresh(drop)
    assert (drop.narrative_score or 0) == 0


def test_recording_a_known_unverified_page_can_upgrade_it_never_downgrade(db_session, monkeypatch):
    drop = _drop(db_session)
    _serve(monkeypatch, "<html><body>nothing readable here?</body></html>")
    # First: the page "cites" nothing readable → rejected? No — it has text and no reference.
    # Use a blocked fetch to create the unverified row first.
    monkeypatch.setattr(cr, "fetch_url", lambda url, **kw: (_ for _ in ()).throw(ContentFetchError("403")))
    first = cr.record_citation(db_session, drop_point=drop, url=CITING_URL, user_id=str(USER))
    assert first["verification"] == "unverified"

    # The publisher relents; the page cites the piece.
    _serve(monkeypatch, f"<html><body>{DROP_URL}</body></html>")
    second = cr.record_citation(db_session, drop_point=drop, url=CITING_URL, user_id=str(USER))
    assert second["created"] is False and second["upgraded"] is True
    assert second["verification"] == "verified"

    # And a later unreadable fetch does not take it back.
    monkeypatch.setattr(cr, "fetch_url", lambda url, **kw: (_ for _ in ()).throw(ContentFetchError("403")))
    third = cr.record_citation(db_session, drop_point=drop, url=CITING_URL, user_id=str(USER))
    assert third["verification"] == "verified" and third["upgraded"] is False
    assert db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).count() == 1


def test_the_drop_point_itself_is_not_a_citation(db_session, monkeypatch):
    drop = _drop(db_session)
    _serve(monkeypatch, f"<html><body>{DROP_URL}</body></html>")
    with pytest.raises(cr.NotACitation):
        cr.record_citation(db_session, drop_point=drop, url=DROP_URL + "?utm=x", user_id=str(USER))
