"""Owner notices — `AUDIT_2026-11-01` §3, `NODUS-FALLBACK-SILENT-1` and `LLM-OUTAGE-SILENT-1`.

The load-bearing properties: a Nodus fallback leaves a durable record even after the caller's
rollback; three fallbacks of one workflow in a day send one notice, and not another that day; a
provider code that needs a person is noticed on the first probe, anything else on the second; an
open provider episode is noticed once and closed once; and a failed send is still recorded, so the
next tick does not send again.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AINDY_ALLOW_SQLITE", "1")

from AINDY.db.database import Base
from AINDY.db.models.system_event import SystemEvent
from AINDY.db.models.user import User
from tests.helpers.app_profile import bootstrap_app_models
from tests.helpers.runtime import import_runtime_model_registry

from apps.automation.services import owner_notices as notices

pytestmark = pytest.mark.app_profile


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
def owner(db, monkeypatch):
    monkeypatch.delenv("AINDY_NOTICE_TO", raising=False)
    uid = uuid.uuid4()
    db.add(User(id=uid, email="owner@example.com", hashed_password="x", is_active=True, is_admin=True))
    db.add(User(id=uuid.uuid4(), email="other@example.com", hashed_password="x", is_active=True))
    db.commit()
    return uid


class Mailbox:
    def __init__(self, ok: bool = True):
        self.sent: list[dict] = []
        self.ok = ok

    def __call__(self, **kwargs):
        self.sent.append(kwargs)
        return {"success": self.ok, "route": "smtp", "error": None if self.ok else "smtp down"}


def _event(db, type_, payload, *, ago=timedelta(0)):
    db.add(SystemEvent(id=uuid.uuid4(), type=type_, source="test", payload=payload,
                       timestamp=datetime.now(timezone.utc) - ago))
    db.commit()


def _types(db, type_):
    return [row.payload for row in db.query(SystemEvent).filter(SystemEvent.type == type_).all()]


# ── recording a fallback ───────────────────────────────────────────────────────────────────


def test_a_fallback_is_a_durable_event(db, owner):
    from apps._shared.nodus import record_nodus_fallback

    record_nodus_fallback(db, workflow="share_drafts_v1", user_id=owner,
                          reason=LookupError("nodus workflow 'share_drafts_v1' is not registered"))
    db.commit()
    (payload,) = _types(db, notices.NODUS_FALLBACK_EVENT)
    assert payload["workflow"] == "share_drafts_v1"
    assert "is not registered" in payload["reason"]


def test_a_fallback_survives_the_callers_rollback(db, owner, monkeypatch):
    """`archive_owner` rolls back before its Python path; the record must be written after that."""
    import AINDY.runtime.nodus_workflow_registry as nwr
    from apps.rippletrace.services import archive_nodus

    monkeypatch.setenv("AINDY_ARCHIVE_NODUS", "1")
    monkeypatch.setattr(archive_nodus, "archive_due", lambda db, uid: True)
    monkeypatch.setattr(nwr, "run_nodus_workflow", lambda *a, **k: {"data": {"nodus_status": "failure"}})
    monkeypatch.setattr("apps.rippletrace.services.content_archive.archive_step",
                        lambda db, user_id: {"fetched": 0})
    _, via = archive_nodus.archive_owner(db, owner)
    db.commit()
    assert via == "python"
    (payload,) = _types(db, notices.NODUS_FALLBACK_EVENT)
    assert payload["workflow"] == "archive_published_work_v1"


def test_every_nodus_caller_records_its_fallback():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "apps"
    for path in ("analytics/services/orchestration/nodus_recalc.py", "analytics/services/reasoning/nodus_apply.py",
                 "rippletrace/services/archive_nodus.py", "rippletrace/services/share_nodus.py"):
        assert "record_nodus_fallback(" in (root / path).read_text(encoding="utf-8"), path


# ── Nodus notices ──────────────────────────────────────────────────────────────────────────


def test_two_fallbacks_are_not_a_notice_and_three_are_one(db, owner):
    box = Mailbox()
    for _ in range(2):
        _event(db, notices.NODUS_FALLBACK_EVENT, {"workflow": "infinity_recalc_v1", "reason": "boom"})
    assert notices.check_nodus_fallbacks(db, send=box) == []
    _event(db, notices.NODUS_FALLBACK_EVENT, {"workflow": "infinity_recalc_v1", "reason": "boom"})
    assert notices.check_nodus_fallbacks(db, send=box) == ["infinity_recalc_v1"]
    (mail,) = box.sent
    assert mail["to"] == "owner@example.com"  # admins only
    assert "3 times" in mail["subject"] and "3 x boom" in mail["body"]
    # Same day, more fallbacks: no second mail.
    _event(db, notices.NODUS_FALLBACK_EVENT, {"workflow": "infinity_recalc_v1", "reason": "boom"})
    db.commit()
    assert notices.check_nodus_fallbacks(db, send=box) == []
    assert len(box.sent) == 1


def test_fallbacks_older_than_a_day_do_not_count(db, owner):
    for _ in range(3):
        _event(db, notices.NODUS_FALLBACK_EVENT, {"workflow": "w", "reason": "r"}, ago=timedelta(hours=25))
    assert notices.check_nodus_fallbacks(db, send=Mailbox()) == []


def test_notice_to_overrides_the_admins(db, owner, monkeypatch):
    monkeypatch.setenv("AINDY_NOTICE_TO", "ops@example.com")
    box = Mailbox()
    notices.send_notice(db, "k", "open", "s", "b", send=box)
    assert [m["to"] for m in box.sent] == ["ops@example.com"]


# ── provider probe ─────────────────────────────────────────────────────────────────────────


class QuotaError(Exception):
    status_code = 429
    code = "insufficient_quota"


class ServerError(Exception):
    status_code = 503
    code = None
    body = {"error": {"type": "server_error"}}


def _fail(exc):
    def probe():
        raise exc
    return probe


def test_classify_reads_the_providers_code():
    assert notices.classify(QuotaError("You exceeded your current quota"))[:2] == ("insufficient_quota", 429)
    assert notices.classify(ServerError("down"))[:2] == ("server_error", 503)
    assert notices.classify(TimeoutError("slow"))[:2] == ("TimeoutError", None)


def test_a_code_that_needs_a_person_is_noticed_at_once_and_once(db, owner):
    box = Mailbox()
    assert notices.check_provider(db, "openai", _fail(QuotaError("quota")), send=box) == "noticed"
    assert notices.check_provider(db, "openai", _fail(QuotaError("quota")), send=box) == "failing"
    assert len(box.sent) == 1 and "insufficient_quota" in box.sent[0]["subject"]
    assert notices.check_provider(db, "openai", lambda: None, send=box) == "recovered"
    assert "recovered" in box.sent[1]["subject"]
    assert notices.check_provider(db, "openai", lambda: None, send=box) == "ok"
    assert len(box.sent) == 2


def test_a_transient_failure_needs_two_probes_in_a_row(db, owner):
    box = Mailbox()
    assert notices.check_provider(db, "openai", _fail(ServerError("down")), send=box) == "failing"
    assert box.sent == []
    db.commit()
    assert notices.check_provider(db, "openai", _fail(ServerError("down")), send=box) == "noticed"
    assert len(box.sent) == 1


def test_a_passing_probe_with_nothing_open_sends_nothing(db, owner):
    box = Mailbox()
    assert notices.check_provider(db, "openai", lambda: None, send=box) == "ok"
    assert box.sent == []


def test_a_failed_send_is_recorded_so_the_next_tick_does_not_resend(db, owner):
    box = Mailbox(ok=False)
    assert notices.check_provider(db, "openai", _fail(QuotaError("quota")), send=box) == "noticed"
    db.commit()
    assert notices.check_provider(db, "openai", _fail(QuotaError("quota")), send=box) == "failing"
    (sent,) = _types(db, notices.NOTICE_SENT_EVENT)
    assert sent["success"] is False and "smtp down" in sent["error"]


# ── the job ────────────────────────────────────────────────────────────────────────────────


def test_the_tick_is_off_without_the_flag(monkeypatch):
    monkeypatch.delenv("AINDY_OWNER_NOTICES", raising=False)
    assert notices.owner_notices_tick() == {"skipped": True, "reason": "disabled"}


def test_compose_turns_notices_on():
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert 'AINDY_OWNER_NOTICES: "${AINDY_OWNER_NOTICES:-1}"' in compose
