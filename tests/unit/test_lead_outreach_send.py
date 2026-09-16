"""Search's real send — the `email` channel delivers, but only to a hand-entered recipient.

BUILD_PLAN carried "Search's real send" as open since the execution layer shipped. The blocker was
never the send call (the runtime ships `email_channel.send_email`); it was that a lead carries no
address. Owner's decision 2026-09-16: recipients are entered by hand on the lead — no enrichment,
no scraping. These tests pin the four outcomes of `execute(channel="email")` and the two rules
around them: a lead without a contact is never emailed, and a `sent` action cannot be reverted.
"""
from __future__ import annotations

import uuid

import pytest

from apps.search.models.leadgen_model import LeadGenResult
from apps.search.services.lead_execution_service import LeadExecutionService
from apps.search.services.leadgen_service import set_lead_contact

pytestmark = pytest.mark.app_profile


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    def _raise(item):
        raise RuntimeError("no llm in tests")

    monkeypatch.setattr(LeadExecutionService, "_llm_draft", staticmethod(_raise))


def _seed(db, user_id: str, contact: str | None, company: str = "Acme") -> int:
    row = LeadGenResult(
        query="q", user_id=uuid.UUID(user_id), company=company, url="https://acme.example",
        context="hiring", fit_score=85, intent_score=85, data_quality_score=90, overall_score=85,
        reasoning="r", contact_email=contact,
    )
    db.add(row)
    db.commit()
    return row.id


def _capture_send(monkeypatch, *, success=True, route="smtp", error=None):
    calls: list[dict] = []

    def fake_send(**kw):
        calls.append(kw)
        return {"success": success, "route": route, "error": error}

    monkeypatch.setattr("AINDY.platform_layer.email_channel.send_email", fake_send)
    return calls


class TestEmailChannel:
    def test_gate_on_and_contact_present_sends_and_records(self, db_session, monkeypatch):
        monkeypatch.setenv("AINDY_SEARCH_OUTREACH_SEND", "1")
        calls = _capture_send(monkeypatch, route="smtp")
        uid = str(uuid.uuid4())
        _seed(db_session, uid, "buyer@acme.example")

        result = LeadExecutionService(db=db_session, user_id=uid).execute(channel="email")

        assert result["actions"][0]["status"] == "sent"
        assert len(calls) == 1
        assert calls[0]["to"] == "buyer@acme.example"
        assert calls[0]["user_id"] == uid
        assert calls[0]["subject"] and calls[0]["body"]
        rec = LeadExecutionService(db=db_session, user_id=uid).history()[0]
        assert rec["status"] == "sent"
        assert rec["recipient"] == "buyer@acme.example"
        assert rec["sent_at"] is not None
        assert rec["note"] == "sent via smtp"

    def test_gate_on_but_no_contact_stays_queued_and_never_calls_send(self, db_session, monkeypatch):
        monkeypatch.setenv("AINDY_SEARCH_OUTREACH_SEND", "1")
        calls = _capture_send(monkeypatch)
        uid = str(uuid.uuid4())
        _seed(db_session, uid, None)

        result = LeadExecutionService(db=db_session, user_id=uid).execute(channel="email")

        assert result["actions"][0]["status"] == "queued"
        assert calls == []
        rec = LeadExecutionService(db=db_session, user_id=uid).history()[0]
        assert "no recipient" in rec["note"]
        assert rec["recipient"] is None and rec["sent_at"] is None

    def test_provider_failure_records_failed_not_sent(self, db_session, monkeypatch):
        monkeypatch.setenv("AINDY_SEARCH_OUTREACH_SEND", "1")
        _capture_send(monkeypatch, success=False, error="SMTP connect refused")
        uid = str(uuid.uuid4())
        _seed(db_session, uid, "buyer@acme.example")

        result = LeadExecutionService(db=db_session, user_id=uid).execute(channel="email")

        assert result["actions"][0]["status"] == "failed"
        rec = LeadExecutionService(db=db_session, user_id=uid).history()[0]
        assert rec["status"] == "failed"
        assert "SMTP connect refused" in rec["note"]
        assert rec["sent_at"] is None

    def test_gate_off_never_calls_send_even_with_a_contact(self, db_session, monkeypatch):
        monkeypatch.delenv("AINDY_SEARCH_OUTREACH_SEND", raising=False)
        calls = _capture_send(monkeypatch)
        uid = str(uuid.uuid4())
        _seed(db_session, uid, "buyer@acme.example")

        result = LeadExecutionService(db=db_session, user_id=uid).execute(channel="email")

        assert result["actions"][0]["status"] == "queued"
        assert calls == []

    def test_draft_channel_never_sends(self, db_session, monkeypatch):
        monkeypatch.setenv("AINDY_SEARCH_OUTREACH_SEND", "1")
        calls = _capture_send(monkeypatch)
        uid = str(uuid.uuid4())
        _seed(db_session, uid, "buyer@acme.example")

        result = LeadExecutionService(db=db_session, user_id=uid).execute(channel="draft")

        assert result["actions"][0]["status"] == "drafted"
        assert calls == []

    def test_a_sent_action_cannot_be_reverted_and_the_lead_stays_actioned(self, db_session, monkeypatch):
        monkeypatch.setenv("AINDY_SEARCH_OUTREACH_SEND", "1")
        calls = _capture_send(monkeypatch)
        uid = str(uuid.uuid4())
        _seed(db_session, uid, "buyer@acme.example")
        svc = LeadExecutionService(db=db_session, user_id=uid)
        action_id = svc.execute(channel="email")["actions"][0]["action_id"]

        assert svc.revert(action_id)["status"] == "sent_cannot_revert"
        # Dedup still holds: a second run must not email the same person again.
        again = svc.execute(channel="email")
        assert again["status"] == "no_action"
        assert len(calls) == 1


class TestLeadContact:
    def test_set_and_clear(self, db_session):
        uid = str(uuid.uuid4())
        lead_id = _seed(db_session, uid, None)

        out = set_lead_contact(db_session, user_id=uid, lead_id=lead_id, contact_email=" Buyer@acme.example ")
        assert out["contact_email"] == "Buyer@acme.example"
        out = set_lead_contact(db_session, user_id=uid, lead_id=lead_id, contact_email="")
        assert out["contact_email"] is None

    def test_malformed_address_is_refused(self, db_session):
        uid = str(uuid.uuid4())
        lead_id = _seed(db_session, uid, None)
        with pytest.raises(ValueError):
            set_lead_contact(db_session, user_id=uid, lead_id=lead_id, contact_email="not-an-address")

    def test_another_users_lead_is_not_found(self, db_session):
        owner, other = str(uuid.uuid4()), str(uuid.uuid4())
        lead_id = _seed(db_session, owner, None)
        assert set_lead_contact(db_session, user_id=other, lead_id=lead_id, contact_email="x@y.example") is None
