"""Release handoff phase 3b — deciding the gate by replying to the gate email (`RELEASE_HANDOFF_SPEC.md` §7.3).

The properties the spec lists: a reply is acted on once; a reply without the code, sent before the gate,
or sent after the stage moved is ignored; only Sent Mail is read, so a forged `From` in the inbox never
counts; the same tick twice changes nothing. Plus: the gate email itself (also in Sent) is never taken
for a reply, and a reply GitHub refuses is still spent and confirmed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from apps.automation.services import release_handoff_service as rh
from apps.automation.services import release_reply as rr
from tests.unit.test_release_handoff import USER, ReviewingGitHub, _handoff, _tick, at, records  # noqa: F401

pytestmark = pytest.mark.app_profile


@pytest.fixture
def reply_enabled(monkeypatch):
    monkeypatch.setenv("AINDY_GITHUB_APPROVE_TOKEN", "github_pat_approve_test")
    monkeypatch.setenv("AINDY_SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("AINDY_SMTP_USER", "owner@example.com")
    monkeypatch.setenv("AINDY_SMTP_PASSWORD", "app-password")
    monkeypatch.delenv("AINDY_RELEASE_REPLY_IMAP_HOST", raising=False)


def mail(subject: str, body: str, sent: datetime, message_id: str = "<m@x>") -> bytes:
    message = EmailMessage()
    message["From"] = "owner@example.com"
    message["To"] = "owner@example.com"
    message["Subject"] = subject
    message["Date"] = format_datetime(sent)
    message["Message-ID"] = message_id
    message.set_content(body)
    return bytes(message)


class FakeImap:
    """Gmail over IMAP, holding one mailbox per folder. Records what was opened and searched."""

    def __init__(self, folders: dict[str, list[bytes]]):
        self.folders, self.selected, self.logins, self.searches = folders, None, [], []

    def login(self, user, password):
        self.logins.append(user)

    def select(self, name, readonly=False):
        assert readonly is True
        self.selected = name.strip('"')
        return ("OK", [b"1"]) if self.selected in self.folders else ("NO", [])

    def search(self, charset, *criteria):
        self.searches.append(criteria)
        code = criteria[-1].strip('"')
        hits = [str(i + 1).encode() for i, raw in enumerate(self.folders[self.selected])
                if code in rr.parse(raw)["subject"]]
        return "OK", [b" ".join(hits)]

    def fetch(self, num, what):
        return "OK", [(b"1 (BODY[] {n}", self.folders[self.selected][int(num) - 1]), b")"]

    def logout(self):
        pass


def _mailbox(sent=(), inbox=()):
    imap = FakeImap({"[Gmail]/Sent Mail": list(sent), "INBOX": list(inbox)})
    return rr.SentMailbox(connect=lambda host: imap), imap


def _at_gate(db_session, records):  # noqa: F811
    row = _handoff(db_session)
    _tick(db_session, row, "04:57:00", records)
    gate_mail = records["mail"][-1]
    assert row.stage == "at_gate" and gate_mail["subject"].startswith(f"[{rr.reply_code(row.id)}] ")
    # The gate email went out at the tick; replies are judged against that moment.
    row.notified = {**row.notified, "at_gate": {**row.notified["at_gate"], "at": at("04:57:00").isoformat()}}
    db_session.commit()
    return row, gate_mail


def _reply(row, gate_subject, word, sent, message_id="<r1@x>"):
    return mail(f"Re: {gate_subject}", f"{word}\n\nOn Sat, A.I.N.D.Y. wrote:\n> {gate_subject}", sent, message_id)


def test_the_gate_email_carries_the_code_and_says_how_to_reply(db_session, records, reply_enabled):  # noqa: F811
    _, gate_mail = _at_gate(db_session, records)
    assert "reply to this email with APPROVE or REJECT as the first word" in gate_mail["body"]


def test_without_the_approve_token_the_gate_email_has_no_code(db_session, records, monkeypatch):  # noqa: F811
    monkeypatch.delenv("AINDY_GITHUB_APPROVE_TOKEN", raising=False)
    monkeypatch.setenv("AINDY_SMTP_USER", "owner@example.com")
    monkeypatch.setenv("AINDY_SMTP_PASSWORD", "app-password")
    row = _handoff(db_session)
    _tick(db_session, row, "04:57:00", records)
    assert not rr.email_reply_enabled()
    assert records["mail"][-1]["subject"] == "aindy-runtime 2.27.0 is waiting for your approval"
    assert "reply to this email" not in records["mail"][-1]["body"]


def test_an_approve_reply_approves_once_and_is_confirmed(db_session, records, reply_enabled):  # noqa: F811
    row, gate_mail = _at_gate(db_session, records)
    gate_raw = mail(gate_mail["subject"], gate_mail["body"], at("04:57:00"), "<gate@x>")
    mailbox, imap = _mailbox(sent=[gate_raw, _reply(row, gate_mail["subject"], "Approve.", at("04:59:00"))])
    github = ReviewingGitHub(at("05:00:00"))
    entry = rr.check_replies(db_session, row, mailbox, github=github, send=records["send"])
    assert entry["word"] == "APPROVE" and entry["outcome"] == "approved"
    assert github.reviews[0]["state"] == "approved"
    assert github.reviews[0]["comment"] == "Approved from A.I.N.D.Y. (email)"
    assert rh.decision(row)["via"] == "email"
    assert records["mail"][-1]["subject"] == "aindy-runtime 2.27.0: approved from your reply, publishing"
    assert imap.selected == "[Gmail]/Sent Mail"
    # The same tick again: the reply is spent, nothing is sent twice.
    assert rr.check_replies(db_session, row, mailbox, github=github, send=records["send"]) is None
    assert len(github.reviews) == 1


def test_a_reject_reply_rejects(db_session, records, reply_enabled):  # noqa: F811
    row, gate_mail = _at_gate(db_session, records)
    mailbox, _ = _mailbox(sent=[_reply(row, gate_mail["subject"], "REJECT - tests are red", at("04:59:00"))])
    github = ReviewingGitHub(at("05:00:00"))
    assert rr.check_replies(db_session, row, mailbox, github=github, send=records["send"])["outcome"] == "rejected"
    assert github.reviews[0]["state"] == "rejected"


def test_the_gate_email_itself_and_other_words_are_not_replies(db_session, records, reply_enabled):  # noqa: F811
    row, gate_mail = _at_gate(db_session, records)
    gate_raw = mail(gate_mail["subject"], "APPROVE?", at("04:57:00"), "<gate@x>")   # even if it began so
    chatter = _reply(row, gate_mail["subject"], "Thanks", at("04:58:00"))
    mailbox, _ = _mailbox(sent=[gate_raw, chatter])
    github = ReviewingGitHub(at("05:00:00"))
    assert rr.check_replies(db_session, row, mailbox, github=github, send=records["send"]) is None
    assert github.reviews == []


def test_a_reply_without_the_code_or_before_the_gate_is_ignored(db_session, records, reply_enabled):  # noqa: F811
    row, gate_mail = _at_gate(db_session, records)
    no_code = mail("Re: aindy-runtime 2.27.0 is waiting for your approval", "APPROVE", at("04:59:00"))
    early = _reply(row, gate_mail["subject"], "APPROVE", at("04:56:00"))
    mailbox, _ = _mailbox(sent=[no_code, early])
    github = ReviewingGitHub(at("05:00:00"))
    assert rr.check_replies(db_session, row, mailbox, github=github, send=records["send"]) is None
    assert github.reviews == []


def test_only_sent_mail_is_read_so_a_forged_inbox_message_never_counts(db_session, records, reply_enabled):  # noqa: F811
    row, gate_mail = _at_gate(db_session, records)
    forged = _reply(row, gate_mail["subject"], "APPROVE", at("04:59:00"))
    mailbox, imap = _mailbox(sent=[], inbox=[forged])
    github = ReviewingGitHub(at("05:00:00"))
    assert rr.check_replies(db_session, row, mailbox, github=github, send=records["send"]) is None
    assert github.reviews == [] and imap.selected == "[Gmail]/Sent Mail"


def test_the_first_deciding_reply_wins(db_session, records, reply_enabled):  # noqa: F811
    row, gate_mail = _at_gate(db_session, records)
    mailbox, _ = _mailbox(sent=[_reply(row, gate_mail["subject"], "APPROVE", at("05:01:00"), "<late@x>"),
                                _reply(row, gate_mail["subject"], "REJECT", at("04:58:00"), "<first@x>")])
    github = ReviewingGitHub(at("05:02:00"))
    entry = rr.check_replies(db_session, row, mailbox, github=github, send=records["send"])
    assert entry["message_id"] == "<first@x>" and [r["state"] for r in github.reviews] == ["rejected"]


def test_a_reply_after_github_decided_is_spent_and_says_so(db_session, records, reply_enabled):  # noqa: F811
    row, gate_mail = _at_gate(db_session, records)
    mailbox, _ = _mailbox(sent=[_reply(row, gate_mail["subject"], "APPROVE", at("05:08:00"))])
    github = ReviewingGitHub(at("05:08:00"))               # PyPI started 05:07: nothing pending any more
    entry = rr.check_replies(db_session, row, mailbox, github=github, send=records["send"])
    assert entry["outcome"] == "already_decided" and github.reviews == []
    assert records["mail"][-1]["subject"] == "aindy-runtime 2.27.0: GitHub says it was already decided"
    assert rr.check_replies(db_session, row, mailbox, github=github, send=records["send"]) is None


def test_after_the_stage_moved_replies_are_not_read(db_session, records, reply_enabled):  # noqa: F811
    row, gate_mail = _at_gate(db_session, records)
    _tick(db_session, row, "05:08:00", records)            # approved on GitHub
    mailbox, imap = _mailbox(sent=[_reply(row, gate_mail["subject"], "APPROVE", at("05:00:00"))])
    assert rr.check_replies(db_session, row, mailbox, github=ReviewingGitHub(at("05:08:00")),
                            send=records["send"]) is None
    assert imap.logins == []                                # not even a login


def test_the_tick_reads_replies_through_process(db_session, records, reply_enabled):  # noqa: F811
    row, gate_mail = _at_gate(db_session, records)
    mailbox, _ = _mailbox(sent=[_reply(row, gate_mail["subject"], "approve", at("04:59:00"))])
    github = ReviewingGitHub(at("05:00:00"))
    rh.process(db_session, row, github, now=at("05:00:00"), send=records["send"], mailbox=mailbox)
    assert [r["state"] for r in github.reviews] == ["approved"] and row.stage == "at_gate"


def test_a_broken_mailbox_does_not_break_the_tick(db_session, records, reply_enabled):  # noqa: F811
    row, _ = _at_gate(db_session, records)

    class Broken(rr.SentMailbox):
        def messages(self, code, since):
            raise OSError("imap down")

    github = ReviewingGitHub(at("05:00:00"))
    assert rh.process(db_session, row, github, now=at("05:00:00"), send=records["send"], mailbox=Broken()) == []
    assert row.stage == "at_gate" and github.reviews == []


def test_first_word_skips_blank_and_quoted_lines():
    assert rr.first_word("\n\n> APPROVE\nreject it\n") == "REJECT"
    assert rr.first_word("Approve!\nOn Sat ... wrote:") == "APPROVE"
    assert rr.first_word("") == ""


def test_the_imap_host_follows_the_smtp_host(monkeypatch):
    monkeypatch.setenv("AINDY_SMTP_HOST", "smtp.gmail.com")
    monkeypatch.delenv("AINDY_RELEASE_REPLY_IMAP_HOST", raising=False)
    assert rr._imap_host() == "imap.gmail.com"
    monkeypatch.setenv("AINDY_RELEASE_REPLY_IMAP_HOST", "mail.example.com")
    assert rr._imap_host() == "mail.example.com"


def test_the_code_is_stable_per_handoff_and_differs_between_them():
    assert rr.reply_code("a") == rr.reply_code("a") and rr.reply_code("a") != rr.reply_code("b")
    assert len(rr.reply_code("a")) == 8 and rr.reply_code("a").isalnum()


def test_utc_dates_compare(reply_enabled):
    sent = datetime(2026, 10, 10, 4, 59, tzinfo=timezone.utc)
    assert rr.parse(mail("x", "APPROVE", sent))["sent"] == sent
