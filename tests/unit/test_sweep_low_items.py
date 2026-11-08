"""The 11-07 route sweep's low-severity items, closed 2026-11-08.

Each test pins one: operator-only status pages, owner checks on ids a caller supplies, owned
writes, a scan scoped to its caller, bounded config values, and one open prediction per drop point.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.app_profile


def _as_user(app, user_id=None, is_admin=False):
    from AINDY.services.auth_service import get_current_user

    user_id = user_id or uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(user_id), "is_admin": is_admin}
    return user_id


# ── Operator-only status pages ────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/apps/automation/scheduler/status", "/apps/dashboard/health"])
def test_status_pages_need_an_operator(app, client, path):
    _as_user(app)
    refused = client.get(path)
    assert refused.status_code == 403, refused.text[:300]


# ── Automation log replay ─────────────────────────────────────────────────────────────


def test_another_users_automation_log_reads_as_missing(app, client, db_session, mock_db):
    from apps.automation.automation_log import AutomationLog
    from apps.automation.services.automation_execution_service import get_automation_log

    owner = uuid.uuid4()
    log = AutomationLog(id=str(uuid.uuid4()), source="test", user_id=owner,
                        payload={"execution_token": "t", "run_id": "r"})
    db_session.add(log)
    db_session.commit()

    assert get_automation_log(db_session, log.id, str(uuid.uuid4())) is None
    assert get_automation_log(db_session, log.id, str(owner)).id == log.id

    _as_user(app)
    refused = client.post(f"/apps/automation/logs/{log.id}/replay")
    assert refused.status_code == 404, refused.text[:300]


# ── seo/analyze writes are owned ──────────────────────────────────────────────────────


def test_seo_analyze_saves_its_rows_with_the_caller(app, client, monkeypatch):
    import apps.analytics.public as analytics
    from apps.search.routes import seo_routes

    monkeypatch.setattr(
        seo_routes, "analyze_seo_content",
        lambda *a, **k: {"readability": 61.0, "word_count": 120, "keyword_densities": {"x": 2.0}},
    )
    saved = []
    monkeypatch.setattr(analytics, "save_calculation",
                        lambda db, metric, value, user_id=None: saved.append((metric, user_id)))
    caller = _as_user(app)
    assert client.post("/apps/seo/analyze", json={"text": "some words here"}).status_code == 200
    assert {metric for metric, _ in saved} == {"seo_readability", "seo_word_count", "seo_avg_keyword_density"}
    assert all(user_id == str(caller) for _, user_id in saved)


# ── Recurrence check scans only the caller's tasks ────────────────────────────────────


def test_recurrence_check_scans_only_the_callers_tasks(monkeypatch):
    import threading

    from apps.tasks.flows import tasks_flows
    from apps.tasks.services import task_service

    seen = []
    done = threading.Event()

    def fake(user_id=None):
        seen.append(user_id)
        done.set()

    monkeypatch.setattr(task_service, "handle_recurrence", fake)
    caller = uuid.uuid4()
    assert tasks_flows.tasks_recurrence_check_node({}, {"user_id": str(caller)})["status"] == "SUCCESS"
    assert done.wait(5)
    assert seen == [caller]

    seen.clear()
    assert tasks_flows.tasks_recurrence_check_node({}, {})["status"] == "SUCCESS"
    assert seen == []  # no user, no scan


# ── Search feedback keeps only the caller's own history id ────────────────────────────


def test_search_feedback_drops_another_users_history_id(db_session):
    from apps.search.models.result_feedback import SearchResultFeedback
    from apps.search.models.search_history import SearchHistory
    from apps.search.services.feedback_service import record_feedback

    other, me = uuid.uuid4(), uuid.uuid4()
    theirs = SearchHistory(id=f"h-{uuid.uuid4().hex}", user_id=other, query="q", result={})
    mine = SearchHistory(id=f"h-{uuid.uuid4().hex}", user_id=me, query="q", result={})
    db_session.add_all([theirs, mine])
    db_session.commit()

    record_feedback(db_session, user_id=str(me), query="q1", result_ref="r1", signal="click", history_id=theirs.id)
    record_feedback(db_session, user_id=str(me), query="q2", result_ref="r2", signal="click", history_id=mine.id)
    stored = {row.query: row.history_id for row in db_session.query(SearchResultFeedback)
              .filter(SearchResultFeedback.user_id == me)}
    assert stored["q1"] is None
    assert stored["q2"] == mine.id


# ── ARM config values are bounded ─────────────────────────────────────────────────────


def test_arm_config_values_are_clamped(app, client):
    _as_user(app)
    response = client.put(
        "/apps/arm/config",
        json={"updates": {"retry_limit": 1000, "retry_delay_seconds": -5, "max_output_tokens": 10**9,
                          "temperature": "not a number"}},
    )
    assert response.status_code == 200, response.text[:300]
    config = response.json()["data"]["config"]
    assert config["retry_limit"] == 5
    assert config["retry_delay_seconds"] == 1
    assert config["max_output_tokens"] == 4000
    assert config["temperature"] == 0.2  # a non-number is dropped, not stored


# ── A strategy's objective must be on its plan ────────────────────────────────────────


def test_a_strategy_cannot_name_an_objective_off_its_plan(db_session):
    from apps.masterplan.services import strategy_layer_service as layer

    with pytest.raises(ValueError, match="is not on plan"):
        layer.create_strategy(
            db_session, masterplan_id=999_999, user_id=str(uuid.uuid4()), name="A strategy",
            objective_id=str(uuid.uuid4()),
        )


# ── One open prediction per drop point ────────────────────────────────────────────────


def test_repeated_predictions_leave_one_open_learning_record(db_session):
    from apps.automation.public import list_learning_records
    from apps.rippletrace.services.learning_engine import record_prediction

    drop_point_id = f"drop-{uuid.uuid4().hex[:8]}"
    first = record_prediction(db_session, drop_point_id, "emerging_signal", 1.0, 2.0)
    for _ in range(5):
        again = record_prediction(db_session, drop_point_id, "emerging_signal", 1.0, 2.0)
        assert again["id"] == first["id"]
    rows = [r for r in list_learning_records(db_session) if r.get("drop_point_id") == drop_point_id]
    assert len(rows) == 1
