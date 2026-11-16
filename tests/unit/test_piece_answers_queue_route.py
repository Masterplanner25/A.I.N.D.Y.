"""ARTICLE_ANSWERS_SPEC B2: asking for a piece's answers when it has no stored text is a 409 with a sentence."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.app_profile


def test_a_piece_with_no_text_is_refused_with_a_sentence(app, client, monkeypatch):
    from AINDY.services.auth_service import get_current_user
    import apps.rippletrace.services.piece_answers as pa

    monkeypatch.setattr(pa, "queue_piece_answers",
                        lambda db, user_id, dp: {"queued": False, "reason": "no_text", "drop_point_id": dp})
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(uuid.uuid4()), "is_admin": False}

    response = client.post("/apps/rippletrace/drop_points/dp-x/answers")
    assert response.status_code == 409, response.text[:300]
    assert "no stored text" in response.text
