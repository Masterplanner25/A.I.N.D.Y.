"""Share drafts — what to post once a piece is published, written from the piece (owner, 2026-10-25).

The load-bearing properties: only a new piece whose text is stored and remembered is due, oldest
first; a cross-post is one piece, so its later copies are marked and skipped; the previous piece in a
confirmed series gets its *What's Next?* footer; the four drafts and the piece's mark are one
transaction, so a retried step cannot write a second set; the links come from the piece, never the
model; and the job runs `share_drafts_v1.nd` only when something is due, falling back to Python and
then to ``failed`` rather than retrying every tick.

No test makes a network call: the model is passed in as ``complete``.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AINDY_ALLOW_SQLITE", "1")

import AINDY.platform_layer.registry as registry
import AINDY.runtime.nodus_workflow_registry as nwr
from AINDY.db.database import Base
from AINDY.db.models.user import User
from tests.helpers.app_profile import bootstrap_app_models
from tests.helpers.runtime import import_runtime_model_registry

pytestmark = pytest.mark.app_profile

SERIES = "2026 Agents Case Study Series"
ARTICLE = "The opening sets up the project. " * 200 + "A version is a promise about behaviour."
READING = {
    "central_point": "A version number is a promise the release has to keep.",
    "linkedin_post": "A version is a promise.\n\nWhat I learned shipping one.",
    "short_post": "A version number is a promise about behaviour.",
    "meta_description": "Why a release number is a commitment about behaviour.",
    "series_footer": "## What's Next?\n\nNext in the series: What a version promises.",
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
def save_job(monkeypatch):
    """The masterplan job, as the registry would hand it over."""
    from apps.masterplan.services.draft_service import save_share_drafts

    real = registry.get_job
    monkeypatch.setattr(registry, "get_job",
                        lambda name: save_share_drafts if name == "masterplan.save_share_drafts" else real(name))


def _drop(db, owner, slug, *, platform="DEV", title=None, when=datetime(2026, 10, 20), series="",
          text=ARTICLE, remembered=True, share=None):
    from apps.rippletrace.drop import DropPointDB

    row = DropPointDB(id=f"dp-{slug}", title=title or slug.replace("-", " ").title(), platform=platform,
                      url=f"https://{platform.lower()}.example/{slug}", date_dropped=when, user_id=owner,
                      tagged_entities=series, core_themes="", share_drafts=share)
    if text:
        row.content_text = text
        row.content_hash = f"h-{slug}"
        row.content_memory_hash = row.content_hash if remembered else None
    db.add(row)
    db.commit()
    return row


def _series(db, owner):
    from apps.rippletrace.container import ContainerDB

    db.add(ContainerDB(user_id=owner, name=SERIES, normalized=SERIES.lower(), status="confirmed"))
    db.commit()


def _model(reading=READING, calls=None):
    def complete(prompt, *, db, user_id):
        if calls is not None:
            calls.append(prompt)
        return json.dumps(reading)
    return complete


# ── which piece is due ─────────────────────────────────────────────────────────────────


def test_the_oldest_remembered_new_piece_is_due(db, owner):
    from apps.rippletrace.services.share_drafts import share_due

    _drop(db, owner, "older-skipped", when=datetime(2026, 1, 1), share="skipped")
    _drop(db, owner, "not-yet-remembered", when=datetime(2026, 10, 1), remembered=False)
    _drop(db, owner, "a-video", when=datetime(2026, 10, 2), text=None)
    _drop(db, owner, "second", when=datetime(2026, 10, 22))
    _drop(db, owner, "first", when=datetime(2026, 10, 21))
    _drop(db, uuid.uuid4(), "someone-else", when=datetime(2026, 9, 1))

    assert share_due(db, owner).id == "dp-first"


def test_a_cross_post_is_one_piece_and_its_later_copy_is_marked(db, owner):
    from apps.rippletrace.services.share_drafts import share_due

    _drop(db, owner, "medium-copy", platform="Medium", title="What a version promises", when=datetime(2026, 10, 21))
    _drop(db, owner, "dev-copy", platform="DEV", title="What a version promises", when=datetime(2026, 10, 23),
          share=None)
    # The Medium copy is earlier, so it is the piece; then the DEV copy is a copy.
    first = share_due(db, owner)
    assert first.id == "dp-medium-copy"
    first.share_drafts = "made"
    db.commit()
    assert share_due(db, owner) is None
    from apps.rippletrace.drop import DropPointDB

    assert db.get(DropPointDB, "dp-dev-copy").share_drafts == "cross_post"


def test_the_previous_piece_in_the_series_is_found(db, owner):
    from apps.rippletrace.services.share_drafts import previous_in_series

    _series(db, owner)
    _drop(db, owner, "part-one", when=datetime(2026, 9, 1), series=SERIES)
    _drop(db, owner, "part-two", when=datetime(2026, 10, 1), series=SERIES)
    _drop(db, owner, "unrelated", when=datetime(2026, 10, 10))
    new = _drop(db, owner, "part-three", when=datetime(2026, 10, 20), series=SERIES)

    name, previous = previous_in_series(db, new)
    assert name == SERIES and previous.id == "dp-part-two"


def test_no_series_means_no_previous_piece(db, owner):
    from apps.rippletrace.services.share_drafts import previous_in_series

    _drop(db, owner, "part-one", when=datetime(2026, 9, 1), series=SERIES)  # not confirmed
    assert previous_in_series(db, _drop(db, owner, "part-two", series=SERIES)) is None


# ── what is written ────────────────────────────────────────────────────────────────────


def test_four_drafts_are_saved_with_the_piece_marked_in_one_go(db, owner, save_job):
    from apps.masterplan.work_model import WorkDraft
    from apps.rippletrace.services.share_drafts import make_share_drafts

    _series(db, owner)
    _drop(db, owner, "part-two", when=datetime(2026, 10, 1), series=SERIES,
          text="The earlier piece.\n\n## What's Next?\n\nComing soon.")
    row = _drop(db, owner, "what-a-version-promises", title="What a version promises", series=SERIES)

    out = make_share_drafts(db, owner, row.id, complete=_model())

    assert out["made"] == 4 and out["series_footer"] is True
    assert row.share_drafts == "made"
    drafts = {d.kind: d for d in db.query(WorkDraft).filter(WorkDraft.drop_point_id == row.id)}
    assert set(drafts) == {"linkedin_post", "short_post", "meta_description", "series_footer"}
    # The links are the piece's own, added by the code, never written by the model.
    assert drafts["linkedin_post"].body.endswith("\n\n" + row.url)
    assert drafts["short_post"].body.endswith(" " + row.url)
    assert drafts["meta_description"].body == READING["meta_description"]
    # The footer lost the link, so it gets it back; and it says where it goes.
    assert row.url in drafts["series_footer"].body
    assert "Part Two" in drafts["series_footer"].title and "https://dev.example/part-two" in drafts["series_footer"].brief
    # Every draft says what the model read the piece as, and which piece it came from.
    assert all(d.brief.endswith("Read as: " + READING["central_point"]) or d.brief.startswith("Read as:")
               for d in drafts.values())
    assert drafts["short_post"].sources == [{"title": "What a version promises", "url": row.url,
                                             "platform": "DEV", "kind": "own"}]


def test_a_made_piece_is_never_written_twice(db, owner, save_job):
    from apps.rippletrace.services.share_drafts import make_share_drafts

    row = _drop(db, owner, "piece")
    calls: list = []
    make_share_drafts(db, owner, row.id, complete=_model(calls=calls))
    again = make_share_drafts(db, owner, row.id, complete=_model(calls=calls))

    assert again["reason"] == "already_made" and len(calls) == 1


def test_without_a_previous_piece_no_footer_is_kept(db, owner, save_job):
    from apps.rippletrace.services.share_drafts import make_share_drafts

    out = make_share_drafts(db, owner, _drop(db, owner, "standalone").id, complete=_model())
    assert out["made"] == 3 and "series_footer" not in out["kinds"]


def test_the_model_reads_the_whole_piece_and_is_told_not_to_link(db, owner, save_job):
    from apps.rippletrace.services.share_drafts import _SYSTEM, make_share_drafts

    calls: list = []
    make_share_drafts(db, owner, _drop(db, owner, "piece").id, complete=_model(calls=calls))
    assert "A version is a promise about behaviour." in calls[0]  # the end of a long piece
    assert "Do NOT include any link" in _SYSTEM
    assert "Never introduce a claim" in _SYSTEM


def test_an_unusable_answer_saves_nothing_and_failure_is_marked(db, owner, save_job):
    from apps.masterplan.work_model import WorkDraft
    from apps.rippletrace.services.share_drafts import make_share_drafts, mark_failed

    row = _drop(db, owner, "piece")
    with pytest.raises(ValueError):
        make_share_drafts(db, owner, row.id, complete=lambda prompt, **k: "not json")
    mark_failed(db, row.id)

    assert row.share_drafts == "failed"
    assert db.query(WorkDraft).count() == 0


# ── asking for an older piece ──────────────────────────────────────────────────────────


def test_an_older_piece_is_queued_on_request_and_a_copy_queues_the_original(db, owner):
    from apps.rippletrace.services.share_drafts import queue_piece

    original = _drop(db, owner, "original", title="Same", when=datetime(2025, 1, 1), share="skipped")
    _drop(db, owner, "copy", title="Same", platform="Medium", when=datetime(2025, 2, 1), share="skipped")
    _drop(db, owner, "video", text=None, share="skipped")

    assert queue_piece(db, owner, "dp-copy") == {"queued": True, "drop_point_id": "dp-original"}
    assert original.share_drafts is None
    assert queue_piece(db, owner, "dp-video")["reason"] == "no_text"
    assert queue_piece(db, uuid.uuid4(), "dp-original")["reason"] == "not_found"


# ── the job: Nodus when something is due, then Python, then failed ─────────────────────


class TestJob:

    def test_flag_default_off(self, monkeypatch):
        from apps.rippletrace.services.share_nodus import nodus_share_enabled

        monkeypatch.delenv("AINDY_SHARE_DRAFTS_NODUS", raising=False)
        assert nodus_share_enabled() is False
        monkeypatch.setenv("AINDY_SHARE_DRAFTS_NODUS", "1")
        assert nodus_share_enabled() is True

    def test_nothing_due_starts_no_worker(self, db, owner, monkeypatch):
        from apps.rippletrace.services.share_nodus import share_owner

        monkeypatch.setenv("AINDY_SHARE_DRAFTS_NODUS", "1")
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda *a, **k: pytest.fail("nothing is due"))
        _drop(db, owner, "old", share="skipped")
        assert share_owner(db, owner) == (None, "none")

    def test_due_runs_the_workflow_for_that_piece_as_the_owner(self, db, owner, monkeypatch):
        from apps.rippletrace.services.share_nodus import share_owner

        monkeypatch.setenv("AINDY_SHARE_DRAFTS_NODUS", "1")
        _drop(db, owner, "new")
        captured = {}
        result = {"made": 3, "drop_point_id": "dp-new"}
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda name, **k: captured.update(k, name=name) or {
            "data": {"nodus_status": "success",
                     "nodus_output_state": {"share_result": {"status": "success", "data": result}}}})

        assert share_owner(db, owner) == (result, "nodus")
        assert captured["name"] == "share_drafts_v1" and captured["user_id"] == str(owner)
        assert captured["input_payload"] == {"args": {"drop_point_id": "dp-new"}}

    def test_a_failed_vm_run_falls_back_to_python(self, db, owner, monkeypatch, save_job):
        from apps.rippletrace.services import share_drafts
        from apps.rippletrace.services.share_nodus import share_owner

        monkeypatch.setenv("AINDY_SHARE_DRAFTS_NODUS", "1")
        monkeypatch.setattr(nwr, "run_nodus_workflow", lambda name, **k: {"data": {"nodus_status": "failure"}})
        monkeypatch.setattr(share_drafts, "_complete", _model())
        _drop(db, owner, "new")

        outcome, via = share_owner(db, owner)
        assert via == "python" and outcome["made"] == 3

    def test_both_failing_marks_the_piece_failed(self, db, owner, monkeypatch, save_job):
        from apps.rippletrace.services import share_drafts
        from apps.rippletrace.services.share_nodus import share_owner

        monkeypatch.delenv("AINDY_SHARE_DRAFTS_NODUS", raising=False)
        monkeypatch.setattr(share_drafts, "_complete", lambda prompt, **k: "")
        row = _drop(db, owner, "new")

        assert share_owner(db, owner)[1] == "failed"
        assert row.share_drafts == "failed"


# ── the workflow ───────────────────────────────────────────────────────────────────────


_ND = Path(__file__).resolve().parents[2] / "apps" / "rippletrace" / "nodus" / "share_drafts_v1.nd"


def test_the_workflow_compiles_and_is_registered():
    from AINDY.runtime.nodus_flow_compiler import compile_nodus_flow
    from AINDY.runtime.nodus_workflow_registry import get_nodus_workflow
    from apps.rippletrace import bootstrap

    assert compile_nodus_flow(_ND.read_text(encoding="utf-8"))["workflow_name"] == "share_drafts_v1"
    bootstrap._register_nodus_workflows()
    assert get_nodus_workflow("share_drafts_v1")["kind"] == "flow-graph"


def test_the_syscall_name_grants_the_capability_it_requires():
    import AINDY.main  # noqa: F401  registers the app's syscalls
    from AINDY.kernel.syscall_dispatcher import _infer_dispatch_capability
    from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

    called = re.findall(r'sys\("([\w.]+)"', _ND.read_text(encoding="utf-8"))
    assert called == ["sys.v1.rippletrace.create_share_drafts"]
    assert _infer_dispatch_capability(called[0]) == SYSCALL_REGISTRY[called[0]].capability


def test_the_syscall_acts_for_the_run_user_not_the_payload(monkeypatch):
    from AINDY.kernel.syscall_registry import SyscallContext
    from apps.rippletrace import syscalls
    from apps.rippletrace.services import share_drafts

    seen = {}
    monkeypatch.setattr(syscalls, "_session_from_context", lambda ctx: (object(), False))
    monkeypatch.setattr(share_drafts, "make_share_drafts",
                        lambda db, user_id, drop_point_id: seen.update(user=user_id, piece=drop_point_id) or {})
    ctx = SyscallContext(execution_unit_id="eu", user_id="run-user", capabilities=["rippletrace.write"], trace_id="t")
    syscalls._handle_create_share_drafts({"user_id": "someone-else", "drop_point_id": "dp-1"}, ctx)
    assert seen == {"user": "run-user", "piece": "dp-1"}
