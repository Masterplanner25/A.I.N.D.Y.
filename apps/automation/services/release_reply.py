"""Deciding the release gate by replying to the gate email — `RELEASE_HANDOFF_SPEC.md` §7.3, phase 3b.

The gate email's subject carries a per-handoff code (`[R7K2Q9XM]`), and its body says to reply with
APPROVE or REJECT as the first word. While a handoff waits at the gate, the watcher's tick reads **the
owner's Sent Mail over IMAP**, not the inbox: a message is in Sent only if the owner's own account sent
it, so a forged `From` never gets in (self-sent mail carries no DKIM verdict to check instead).

A reply is acted on only if its subject has the code, it is not the gate email itself, it was sent after
the gate email, the handoff is still at the gate with no decision, and it is the first such reply. It is
recorded before GitHub is called, so it is acted on once whatever GitHub answers, and a confirmation
email says what happened.

On only when the approve token is set and the mail account's credentials are (`AINDY_SMTP_USER`,
`AINDY_SMTP_PASSWORD`, the same Gmail app password, which logs in to IMAP).
"""
from __future__ import annotations

import base64
import email
import hashlib
import imaplib
import logging
import os
import re
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from apps.automation.services.github_actions import approve_token

logger = logging.getLogger(__name__)

WORDS = {"APPROVE": "approved", "REJECT": "rejected"}
DEFAULT_MAILBOX = "[Gmail]/Sent Mail"
#: Messages read per tick at most; a handoff's code matches a handful.
MAX_MESSAGES = 20


def reply_code(handoff_id: str) -> str:
    """Eight characters bound to the handoff, derived rather than stored, so no migration."""
    digest = hashlib.sha256(f"release-handoff:{handoff_id}".encode()).digest()
    return base64.b32encode(digest).decode()[:8]


def _imap_host() -> str:
    explicit = (os.getenv("AINDY_RELEASE_REPLY_IMAP_HOST") or "").strip()
    if explicit:
        return explicit
    smtp = (os.getenv("AINDY_SMTP_HOST") or "").strip()
    return f"imap.{smtp[5:]}" if smtp.startswith("smtp.") else ""


def _credentials() -> tuple[str, str]:
    return (os.getenv("AINDY_SMTP_USER") or "").strip(), os.getenv("AINDY_SMTP_PASSWORD") or ""


def email_reply_enabled() -> bool:
    user, password = _credentials()
    return bool(approve_token() and user and password and _imap_host())


def first_word(body: str) -> str:
    """The first word the owner wrote: the first non-blank line that is not quoted text."""
    for line in (body or "").splitlines():
        line = line.strip()
        if not line or line.startswith(">"):
            continue
        word = re.sub(r"[^A-Za-z]", "", line.split()[0])
        return word.upper()
    return ""


def _plain_text(message: Message) -> str:
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_type() == "text/plain" and not part.get_filename():
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


def parse(raw: bytes) -> dict:
    message = email.message_from_bytes(raw)
    try:
        sent = parsedate_to_datetime(message.get("Date"))
        sent = sent if sent.tzinfo else sent.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        sent = None
    return {"subject": str(message.get("Subject") or ""), "sent": sent,
            "message_id": str(message.get("Message-ID") or ""), "word": first_word(_plain_text(message))}


def pick_reply(messages: list[dict], *, code: str, gate_subject: str, gate_sent: datetime) -> dict | None:
    """The first reply that decides, or None. Pure: the same mailbox always gives the same answer."""
    replies = [m for m in messages
               if f"[{code}]" in m["subject"]
               and m["subject"].strip() != gate_subject.strip()
               and m["sent"] is not None and m["sent"] >= gate_sent
               and m["word"] in WORDS]
    return min(replies, key=lambda m: m["sent"]) if replies else None


class SentMailbox:
    """The owner's Sent Mail, read-only. One login per tick at most, and only when it is first needed."""

    def __init__(self, *, mailbox: str | None = None, connect: Callable[[str], Any] | None = None):
        self.mailbox = mailbox or (os.getenv("AINDY_RELEASE_REPLY_MAILBOX") or DEFAULT_MAILBOX)
        self._connect = connect or (lambda host: imaplib.IMAP4_SSL(host, 993, timeout=20))
        self._client = None

    def _open(self):
        if self._client is None:
            user, password = _credentials()
            client = self._connect(_imap_host())
            client.login(user, password)
            status, _ = client.select(f'"{self.mailbox}"', readonly=True)
            if status != "OK":
                client.logout()
                raise RuntimeError(f"cannot open {self.mailbox}")
            self._client = client
        return self._client

    def messages(self, code: str, since: datetime) -> list[dict]:
        client = self._open()
        status, data = client.search(None, "SINCE", since.strftime("%d-%b-%Y"), "SUBJECT", f'"[{code}]"')
        if status != "OK":
            return []
        found = []
        for num in (data[0] or b"").split()[-MAX_MESSAGES:]:
            status, parts = client.fetch(num, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
            if status == "OK" and raw:
                found.append(parse(raw))
        return found

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.logout()
            except Exception:
                pass
            self._client = None


def _gate_email(handoff) -> tuple[str, datetime] | None:
    """The gate email this handoff sent with a reply code, as (subject, sent at), if it sent one."""
    from apps.automation.services.release_handoff_service import _ts

    entry = (handoff.notified or {}).get("at_gate") or {}
    subject, at = str(entry.get("subject") or ""), _ts(entry.get("at"))
    if not entry.get("success") or not at or f"[{reply_code(handoff.id)}]" not in subject:
        return None
    return subject, at


def awaiting_reply(handoff) -> bool:
    from apps.automation.services.release_handoff_service import decision

    return (handoff.stage == "at_gate" and decision(handoff) is None and _gate_email(handoff) is not None
            and not any(e.get("stage") == "reply" for e in handoff.history or []))


def check_replies(db, handoff, mailbox: SentMailbox, *, github=None,
                  send: Callable[..., dict] | None = None) -> dict | None:
    """Act on the owner's reply to this handoff's gate email, once. Returns the reply entry, or None."""
    from fastapi import HTTPException

    from apps.automation.services import release_handoff_service as rh

    if not awaiting_reply(handoff):
        return None
    subject, sent_at = _gate_email(handoff)
    reply = pick_reply(mailbox.messages(reply_code(handoff.id), sent_at),
                       code=reply_code(handoff.id), gate_subject=subject, gate_sent=sent_at)
    if reply is None:
        return None
    state = WORDS[reply["word"]]
    entry = {"stage": "reply", "word": reply["word"], "message_id": reply["message_id"],
             "sent": rh._iso(reply["sent"]), "at": rh._iso(rh._now()), "outcome": "pending"}
    # Recorded and committed before GitHub is called: whatever GitHub answers, this reply is spent.
    handoff.history = [*(handoff.history or []), entry]
    db.commit()
    try:
        rh.decide(db, handoff.user_id, handoff.id, state, via="email", github=github)
        outcome = state
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        outcome = "already_decided" if exc.status_code == 409 else f"error: {detail.get('message')}"
    entry = {**entry, "outcome": outcome}
    handoff.history = [e if e.get("stage") != "reply" else entry for e in handoff.history or []]
    db.commit()
    _confirm(db, handoff, entry, send=send)
    return entry


def confirmation(handoff, entry: dict) -> tuple[str, str]:
    from apps.automation.services.release_handoff_service import project_name

    project = f"{project_name(handoff.repo)} {handoff.version}"
    link = handoff.run_url or f"https://github.com/{handoff.repo}/actions"
    outcome = entry["outcome"]
    if outcome == "approved":
        return (f"{project}: approved from your reply, publishing",
                f"Your reply approved {project} on GitHub. A.I.N.D.Y. follows it to PyPI and emails you when it "
                f"is done.\n\nRun: {link}")
    if outcome == "rejected":
        return (f"{project}: rejected from your reply",
                f"Your reply rejected {project} on GitHub. Nothing is published.\n\nRun: {link}")
    if outcome == "already_decided":
        return (f"{project}: GitHub says it was already decided",
                f"Your reply ({entry['word']}) was not sent: the gate for {project} was already decided.\n\n"
                f"Run: {link}")
    return (f"{project}: your reply could not be sent to GitHub",
            f"Your reply ({entry['word']}) reached A.I.N.D.Y., but GitHub did not take it ({outcome}).\n\n"
            f"Nothing retries a reply. Decide on GitHub: {link}")


def _confirm(db, handoff, entry: dict, *, send: Callable[..., dict] | None = None) -> None:
    from apps.automation.services.release_handoff_service import _recipient

    if send is None:
        from AINDY.platform_layer.email_channel import send_email as send
    to = _recipient(db, handoff)
    if not to:
        return
    subject, body = confirmation(handoff, entry)
    result = send(to=to, subject=subject, body=body, db=db, user_id=str(handoff.user_id))
    if not result.get("success"):
        logger.warning("[release] reply confirmation for %s not delivered: %s", handoff.tag, result.get("error"))
