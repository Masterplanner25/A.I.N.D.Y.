"""ARTICLE_ANSWERS_SPEC phase B3: how one published piece connects to the owner's other pieces."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.rippletrace.container import ContainerDB
from apps.rippletrace.models import DropPointDB
from apps.rippletrace.services.piece_links import piece_link_report

pytestmark = pytest.mark.app_profile

SERIES = "Agents Series"


def _piece(db, owner, slug, title, *, platform="DEV", when, links=None, series=SERIES):
    row = DropPointDB(id=f"dp-{slug}-{uuid.uuid4().hex[:6]}", title=title, platform=platform,
                      url=f"https://{platform.lower()}.example/{slug}", date_dropped=when, user_id=owner,
                      core_themes="", tagged_entities=series, intent="published", content_links=links)
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def catalogue(db_session):
    owner = uuid.uuid4()
    db_session.add(ContainerDB(user_id=owner, name=SERIES, normalized=SERIES.lower(), status="confirmed"))
    db_session.commit()
    one = _piece(db_session, owner, "one", "Part One", when=datetime(2026, 9, 1), links=[])
    two = _piece(db_session, owner, "two", "Part Two", when=datetime(2026, 9, 8),
                 links=["https://dev.example/one", "https://example.org/elsewhere", "https://dev.example/two"])
    two_medium = _piece(db_session, owner, "two-m", "Part Two", platform="Medium", when=datetime(2026, 9, 9), links=None)
    three = _piece(db_session, owner, "three", "Part Three", when=datetime(2026, 9, 15),
                   links=[two_medium.url + "?utm_source=feed"])  # links Part Two through its Medium copy
    other_owner = uuid.uuid4()
    _piece(db_session, other_owner, "theirs", "Their Piece", when=datetime(2026, 9, 2), links=[two.url], series="")
    return {"owner": owner, "one": one, "two": two, "two_medium": two_medium, "three": three, "other": other_owner}


def test_links_to_and_linked_from_count_any_copy_as_the_piece(db_session, catalogue):
    report = piece_link_report(db_session, catalogue["owner"], catalogue["two"].id)

    assert [p["title"] for p in report["links_to"]] == ["Part One"]  # its own URL is not a link to itself
    assert [p["title"] for p in report["linked_from"]] == ["Part Three"]  # through the Medium copy
    assert report["other_links"] == 1
    assert report["unread_copies"] == 1  # the Medium copy's links are unknown, not "none"


def test_series_neighbours_and_whether_each_pair_links(db_session, catalogue):
    [series] = piece_link_report(db_session, catalogue["owner"], catalogue["two"].id)["series"]
    assert series["name"] == SERIES and series["position"] == 2 and series["of"] == 3

    assert series["previous"]["title"] == "Part One"
    assert series["previous"]["this_links_to_it"] is True and series["previous"]["it_links_here"] is False
    assert series["next"]["title"] == "Part Three"
    assert series["next"]["this_links_to_it"] is False and series["next"]["it_links_here"] is True


def test_only_the_callers_pieces_are_read(db_session, catalogue):
    # Another user's piece linking to Part Two is not "linked from" for this owner.
    report = piece_link_report(db_session, catalogue["owner"], catalogue["two"].id)
    assert "Their Piece" not in [p["title"] for p in report["linked_from"]]
    # And another user cannot read this owner's piece.
    assert piece_link_report(db_session, catalogue["other"], catalogue["two"].id) == {"found": False}


def test_the_route_404s_for_someone_elses_piece(app, client, db_session, mock_db, catalogue):
    from AINDY.services.auth_service import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"sub": str(catalogue["other"]), "is_admin": False}
    assert client.get(f"/apps/rippletrace/drop_points/{catalogue['two'].id}/links").status_code == 404
