"""ARTICLE_ANSWERS_SPEC phase B2: what each published piece answers, stored once per version of its text.

The owner's decisions (2026-11-08): gpt-5.5 reads (1), new pieces automatically and older ones on
request (3), not in the Infinity score (4). Same lifecycle as share drafts: one set per piece, the
earliest copy of a cross-post holds it, Nodus first with a recorded Python fallback.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import AINDY.runtime.nodus_workflow_registry as nwr
from AINDY.db.database import Base
from AINDY.db.models.user import User
from tests.helpers.app_profile import bootstrap_app_models
from tests.helpers.runtime import import_runtime_model_registry

pytestmark = pytest.mark.app_profile

ARTICLE = "An agent is a loop that plans, acts and checks its own results. " * 40
READING = {
    "answers": [{"question": "What is an agent?", "passage": "An agent is a loop", "kind": "what_is",
                 "passage_found": True}],
    "raised": [{"question": "How does it remember?", "passage": "", "passage_found": False}],
    "range": {"what_is": 1, "how": 0, "why": 0, "compared_with": 0, "who": 0, "other": 0},
    "model": "gpt-5.5",
    "reason": None,
}


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


@pytest.fixture()
def reader(monkeypatch):
    """The gpt-5.5 read, faked; records each call."""
    from apps.rippletrace.services import piece_answers

    calls = []

    def fake(text, *, title, user_id, db):
        calls.append(title)
        return dict(READING)

    monkeypatch.setattr(piece_answers, "_reader", fake)
    return calls


def _drop(db, owner, slug, *, platform="DEV", title=None, when=datetime(2026, 11, 1), text=ARTICLE,
          remembered=True, answers=None):
    from apps.rippletrace.drop import DropPointDB

    row = DropPointDB(id=f"dp-{slug}", title=title or slug.replace("-", " ").title(), platform=platform,
                      url=f"https://{platform.lower()}.example/{slug}", date_dropped=when, user_id=owner,
                      tagged_entities="", core_themes="", answers=answers)
    if text:
        row.content_text = text
        row.content_hash = f"h-{slug}"
        row.content_memory_hash = row.content_hash if remembered else None
    db.add(row)
    db.commit()
    return row


# ── which piece is due ─────────────────────────────────────────────────────────────────


def test_only_new_remembered_pieces_are_due_oldest_first(db, owner):
    from apps.rippletrace.services.piece_answers import answers_due

    _drop(db, owner, "old", answers="skipped")  # stored before B2: new pieces only
    _drop(db, owner, "unremembered", remembered=False)
    _drop(db, owner, "later", when=datetime(2026, 11, 5))
    _drop(db, owner, "earlier", when=datetime(2026, 11, 2))
    assert answers_due(db, owner).id == "dp-earlier"


def test_a_cross_post_is_one_piece_and_its_later_copy_is_marked(db, owner):
    from apps.rippletrace.services.piece_answers import answers_due

    first = _drop(db, owner, "a-dev", title="Same Piece", when=datetime(2026, 11, 2))
    copy = _drop(db, owner, "a-medium", platform="Medium", title="Same Piece", when=datetime(2026, 11, 3))
    first.answers = "made"
    db.commit()
    assert answers_due(db, owner) is None
    assert copy.answers == "cross_post"


# ── reading and storing ────────────────────────────────────────────────────────────────


def test_answers_are_stored_with_the_text_they_were_read_from(db, owner, reader):
    from apps.rippletrace.piece_answers import PieceAnswersDB
    from apps.rippletrace.services.piece_answers import make_piece_answers

    row = _drop(db, owner, "new")
    out = make_piece_answers(db, owner, "dp-new")
    assert out == {"drop_point_id": "dp-new", "answers": 1, "stored": True}
    stored = db.query(PieceAnswersDB).one()
    assert stored.content_hash == "h-new" and stored.answers[0]["question"] == "What is an agent?"
    assert row.answers == "made"

    # The same text again is never read twice.
    row.answers = None
    db.commit()
    assert make_piece_answers(db, owner, "dp-new")["stored"] is False
    assert reader == ["New"] and db.query(PieceAnswersDB).count() == 1


def test_a_failed_read_stores_nothing_and_the_piece_is_marked_failed(db, owner, monkeypatch):
    from apps.rippletrace.piece_answers import PieceAnswersDB
    from apps.rippletrace.services import piece_answers

    monkeypatch.setattr(piece_answers, "_reader",
                        lambda text, **k: {"answers": [], "raised": [], "reason": "the answers service could not be reached"})
    row = _drop(db, owner, "new")
    with pytest.raises(RuntimeError, match="could not be reached"):
        piece_answers.make_piece_answers(db, owner, "dp-new")
    piece_answers.mark_failed(db, "dp-new")
    assert db.query(PieceAnswersDB).count() == 0
    assert row.answers == "failed"


def test_another_users_piece_is_never_read(db, owner, reader):
    from apps.rippletrace.services.piece_answers import get_piece_answers, make_piece_answers, queue_piece_answers

    _drop(db, owner, "mine")
    stranger = uuid.uuid4()
    with pytest.raises(LookupError):
        make_piece_answers(db, stranger, "dp-mine")
    assert queue_piece_answers(db, stranger, "dp-mine") == {"queued": False, "reason": "not_found"}
    assert get_piece_answers(db, stranger, "dp-mine") == {"found": False}
    assert reader == []


# ── older pieces on request, and reading back ──────────────────────────────────────────


def test_an_older_piece_is_queued_on_request_and_a_copy_queues_the_original(db, owner):
    from apps.rippletrace.services.piece_answers import queue_piece_answers

    original = _drop(db, owner, "x-dev", title="Older", when=datetime(2026, 9, 1), answers="skipped")
    _drop(db, owner, "x-medium", platform="Medium", title="Older", when=datetime(2026, 9, 2), answers="skipped")
    assert queue_piece_answers(db, owner, "dp-x-medium") == {"queued": True, "drop_point_id": "dp-x-dev"}
    assert original.answers is None


def test_reading_back_says_when_the_answers_came_from_older_text(db, owner, reader):
    from apps.rippletrace.services.piece_answers import get_piece_answers, make_piece_answers

    row = _drop(db, owner, "p")
    _drop(db, owner, "p-copy", platform="Medium", title="P", when=datetime(2026, 11, 3))
    make_piece_answers(db, owner, "dp-p")

    current = get_piece_answers(db, owner, "dp-p-copy")  # a copy reads its earliest copy's answers
    assert current["read_from"] == "dp-p" and current["stale"] is False and len(current["answers"]) == 1

    row.content_hash = "h-p-edited"
    db.commit()
    assert get_piece_answers(db, owner, "dp-p")["stale"] is True


# ── the job: Nodus when something is due, then Python, then failed ─────────────────────


class TestJob:

    def test_flag_default_off(self, monkeypatch):
        from apps.rippletrace.services.answers_nodus import nodus_answers_enabled

        monkeypatch.delenv("AINDY_PIECE_ANSWERS_NODUS", raising=False)
        assert nodus_answers_enabled() is False
        monkeypatch.setenv("AINDY_PIECE_ANSWERS_NODUS", "1")
        assert nodus_answers_enabled() is True

    def test_nothing_due_starts_no_worker(self, db, owner, monkeypatch):
        from apps.rippletrace.services.answers_nodus import answers_owner

        monkeypatch.setenv("AINDY_PIECE_ANSWERS_NODUS", "1")
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda *a, **k: pytest.fail("nothing is due"))
        _drop(db, owner, "old", answers="skipped")
        assert answers_owner(db, owner) == (None, "none")

    def test_due_runs_the_workflow_for_that_piece_as_the_owner(self, db, owner, monkeypatch):
        from apps.rippletrace.services.answers_nodus import answers_owner

        monkeypatch.setenv("AINDY_PIECE_ANSWERS_NODUS", "1")
        _drop(db, owner, "new")
        captured = {}
        result = {"drop_point_id": "dp-new", "answers": 1, "stored": True}
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda name, **k: captured.update(k, name=name) or {
            "data": {"nodus_status": "success",
                     "nodus_output_state": {"answers_result": {"status": "success", "data": result}}}})

        assert answers_owner(db, owner) == (result, "nodus")
        assert captured["name"] == "piece_answers_v1" and captured["user_id"] == str(owner)
        assert captured["input_payload"] == {"args": {"drop_point_id": "dp-new"}}

    def test_a_failed_vm_run_falls_back_to_python_and_is_recorded(self, db, owner, monkeypatch, reader):
        import apps._shared.nodus as shared_nodus
        from apps.rippletrace.services.answers_nodus import answers_owner

        monkeypatch.setenv("AINDY_PIECE_ANSWERS_NODUS", "1")
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda name, **k: {"data": {"nodus_status": "failure"}})
        recorded = []
        monkeypatch.setattr(shared_nodus, "record_nodus_fallback", lambda db, **k: recorded.append(k["workflow"]))
        _drop(db, owner, "new")

        outcome, via = answers_owner(db, owner)
        assert via == "python" and outcome["stored"] is True
        assert recorded == ["piece_answers_v1"]

    def test_both_failing_marks_the_piece_failed(self, db, owner, monkeypatch):
        from apps.rippletrace.services import piece_answers
        from apps.rippletrace.services.answers_nodus import answers_owner

        monkeypatch.delenv("AINDY_PIECE_ANSWERS_NODUS", raising=False)
        monkeypatch.setattr(piece_answers, "_reader", lambda text, **k: {"reason": "no usable answers were returned"})
        row = _drop(db, owner, "new")

        assert answers_owner(db, owner)[1] == "failed"
        assert row.answers == "failed"


# ── the workflow ───────────────────────────────────────────────────────────────────────


_ND = Path(__file__).resolve().parents[2] / "apps" / "rippletrace" / "nodus" / "piece_answers_v1.nd"


def test_the_workflow_compiles_and_is_registered():
    from AINDY.runtime.nodus_flow_compiler import compile_nodus_flow
    from AINDY.runtime.nodus_workflow_registry import get_nodus_workflow
    from apps.rippletrace import bootstrap

    assert compile_nodus_flow(_ND.read_text(encoding="utf-8"))["workflow_name"] == "piece_answers_v1"
    bootstrap._register_nodus_workflows()
    assert get_nodus_workflow("piece_answers_v1")["kind"] == "flow-graph"


def test_the_syscall_name_grants_the_capability_it_requires():
    import AINDY.main  # noqa: F401  registers the app's syscalls
    from AINDY.kernel.syscall_dispatcher import _infer_dispatch_capability
    from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

    called = re.findall(r'sys\("([\w.]+)"', _ND.read_text(encoding="utf-8"))
    assert called == ["sys.v1.rippletrace.create_piece_answers"]
    assert _infer_dispatch_capability(called[0]) == SYSCALL_REGISTRY[called[0]].capability


def test_the_syscall_acts_for_the_run_user_not_the_payload(monkeypatch):
    from AINDY.kernel.syscall_registry import SyscallContext
    from apps.rippletrace import syscalls
    from apps.rippletrace.services import piece_answers

    seen = {}
    monkeypatch.setattr(syscalls, "_session_from_context", lambda ctx: (object(), False))
    monkeypatch.setattr(piece_answers, "make_piece_answers",
                        lambda db, user_id, drop_point_id: seen.update(user=user_id, piece=drop_point_id) or {})
    ctx = SyscallContext(execution_unit_id="eu", user_id="run-user", capabilities=["rippletrace.write"], trace_id="t")
    syscalls._handle_create_piece_answers({"user_id": "someone-else", "drop_point_id": "dp-1"}, ctx)
    assert seen == {"user": "run-user", "piece": "dp-1"}
