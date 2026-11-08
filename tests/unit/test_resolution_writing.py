"""ARTICLE_ANSWERS_SPEC phase C: what the engines missed, beside what the owner's published writing says.

For each question of the latest finished Resolution Check that the engines did not fully resolve, the
owner's pieces that answer questions ABOUT its subject. Deterministic, no model call, and never a claim
that a piece closes the gap.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from apps.masterplan.services import resolution_writing as rw

pytestmark = pytest.mark.app_profile


@pytest.mark.parametrize("text, name, expected", [
    ("What is A.I.N.D.Y. for?", "A.I.N.D.Y.", True),
    ("What is AINDY for?", "A.I.N.D.Y.", True),
    ("How does aindy runtime boot?", "Aindy-runtime", True),
    ("How does aindyruntime boot?", "Aindy-runtime", True),
    ("What is nodus?", "Nodus", True),
    ("What are nodules?", "Nodus", False),  # whole words only
    ("Who is Shawn?", "Shawn Knight", False),
])
def test_names_ignore_case_and_punctuation_but_not_word_boundaries(text, name, expected):
    assert rw.names(text, name) is expected


def _work(db, owner, name, kind="project"):
    from apps.masterplan.work_model import Work

    work = Work(id=str(uuid.uuid4()), user_id=owner, name=name, kind=kind, summary=name, role="creator",
                status="active", provenance="owner")
    db.add(work)
    db.commit()
    return work


def _run(db, owner, questions, verdicts):
    from apps.masterplan.work_model import ResolutionAnswer, ResolutionRun

    run = ResolutionRun(id=str(uuid.uuid4()), user_id=owner, scope="core", status="done", questions=questions,
                        engines=["openai", "claude"], created_at=datetime(2026, 11, 2, tzinfo=timezone.utc))
    db.add(run)
    db.commit()
    for key, resolutions in verdicts.items():
        for engine, resolution in zip(("openai", "claude"), resolutions):
            db.add(ResolutionAnswer(run_id=run.id, user_id=owner, question_key=key, engine=engine,
                                    scores={"resolution": resolution}))
    db.commit()
    return run


@pytest.fixture()
def checked(db_session):
    owner = uuid.uuid4()
    nodus = _work(db_session, owner, "Nodus")
    aindy = _work(db_session, owner, "A.I.N.D.Y.")
    runtime = _work(db_session, owner, "Aindy-runtime")
    questions = [
        {"key": f"direct:{nodus.id}", "kind": "direct", "subject": nodus.id, "text": "What is Nodus?"},
        {"key": f"direct:{aindy.id}", "kind": "direct", "subject": aindy.id, "text": "What is A.I.N.D.Y.?"},
        {"key": f"direct:{runtime.id}", "kind": "direct", "subject": runtime.id, "text": "What is Aindy-runtime?"},
        {"key": f"pair:{aindy.id}:{runtime.id}", "kind": "relation", "subject": aindy.id,
         "text": "How are A.I.N.D.Y. and Aindy-runtime related?"},
    ]
    _run(db_session, owner, questions, {
        f"direct:{nodus.id}": ["absent", "absent"],
        f"direct:{aindy.id}": ["mixed", "resolved"],
        f"direct:{runtime.id}": ["resolved", "listed"],  # the engines got it: never listed
        f"pair:{aindy.id}:{runtime.id}": ["wrong", "resolved"],
    })
    return {"owner": owner, "nodus": nodus, "aindy": aindy, "runtime": runtime}


PIECES = [
    {"drop_point_id": "dp-1", "title": "Why Claude Code", "url": "https://dev.to/me/1", "answers": [
        # Mentions Nodus only in the passage: it is about Claude Code, not an answer about Nodus.
        {"question": "Why did the writer start using Claude Code?", "passage": "Carrying Nodus by hand was slow.",
         "kind": "why", "passage_found": True},
    ]},
    {"drop_point_id": "dp-2", "title": "Building Nodus", "url": "https://dev.to/me/2", "answers": [
        {"question": "What is Nodus built to do?", "passage": "Nodus is a workflow language.", "kind": "what_is",
         "passage_found": True},
    ]},
    {"drop_point_id": "dp-3", "title": "The Stack", "url": "https://dev.to/me/3", "answers": [
        {"question": "How does AINDY run on the aindy runtime?", "passage": "It is built on it.", "kind": "how",
         "passage_found": True},
        {"question": "Who wrote AINDY?", "passage": "Shawn did.", "kind": "who", "passage_found": True},
    ]},
]


def test_only_what_the_engines_missed_and_only_answers_about_it(db_session, checked):
    out = rw.answered_in_writing(db_session, checked["owner"], pieces=PIECES)
    nodus, aindy, runtime = checked["nodus"].id, checked["aindy"].id, checked["runtime"].id

    assert f"direct:{runtime}" not in out  # resolved or listed on every engine
    assert [p["title"] for p in out[f"direct:{nodus}"]["pieces"]] == ["Building Nodus"]
    assert out[f"direct:{nodus}"]["pieces"][0]["question"] == "What is Nodus built to do?"
    # "Who wrote AINDY?" names it but is a who-question: it does not take on "What is A.I.N.D.Y.?";
    # the how-question does.
    assert [p["question"] for p in out[f"direct:{aindy}"]["pieces"]] == ["How does AINDY run on the aindy runtime?"]
    assert [p["title"] for p in out[f"pair:{aindy}:{runtime}"]["pieces"]] == ["The Stack"]


def test_a_relation_needs_both_names(db_session, checked):
    only_one = [{"drop_point_id": "dp-x", "title": "Just AINDY", "url": None, "answers": [
        {"question": "How does AINDY plan?", "passage": "It plans.", "kind": "how", "passage_found": True}]}]
    out = rw.answered_in_writing(db_session, checked["owner"], pieces=only_one)
    assert out[f"pair:{checked['aindy'].id}:{checked['runtime'].id}"]["pieces"] == []


def test_no_finished_check_means_nothing(db_session):
    assert rw.answered_in_writing(db_session, uuid.uuid4(), pieces=PIECES) == {}


def test_the_planner_clause_names_up_to_two_pieces(db_session, checked):
    out = rw.answered_in_writing(db_session, checked["owner"], pieces=PIECES)
    clause = rw.writing_clause(out, checked["nodus"].id)
    assert clause == 'your published pieces answering questions about it: "Building Nodus"'
    assert rw.writing_clause(out, checked["runtime"].id) is None


def test_the_planner_line_carries_the_clause(db_session, checked, monkeypatch):
    from apps.masterplan.services import resolution_review

    original = rw.answered_in_writing
    monkeypatch.setattr(rw, "answered_in_writing", lambda db, uid: original(db, uid, pieces=PIECES))
    lines = resolution_review.planner_lines(db_session, checked["owner"])

    assert lines[checked["nodus"].id].endswith('your published pieces answering questions about it: "Building Nodus"')
    assert "published pieces" not in lines[checked["runtime"].id]  # resolved: no clause, relation or not


def test_only_current_readings_of_the_owners_pieces_count(db_session):
    from apps.rippletrace.models import DropPointDB, PieceAnswersDB
    from apps.rippletrace.services.piece_answers import answered_pieces

    owner, other = uuid.uuid4(), uuid.uuid4()
    current = DropPointDB(id="dp-cur", title="Current", platform="DEV", url="https://dev.to/c", user_id=owner,
                          core_themes="", tagged_entities="", intent="published", content_hash="h2")
    edited = DropPointDB(id="dp-old", title="Edited", platform="DEV", url="https://dev.to/o", user_id=owner,
                         core_themes="", tagged_entities="", intent="published", content_hash="h-new")
    theirs = DropPointDB(id="dp-theirs", title="Theirs", platform="DEV", url="https://dev.to/t", user_id=other,
                         core_themes="", tagged_entities="", intent="published", content_hash="h3")
    db_session.add_all([current, edited, theirs])
    for drop, hash_, user in ((current, "h2", owner), (edited, "h-old", owner), (theirs, "h3", other)):
        db_session.add(PieceAnswersDB(user_id=user, drop_point_id=drop.id, content_hash=hash_,
                                      answers=[{"question": "Q"}], raised=[], answer_range={}))
    db_session.commit()

    assert [p["drop_point_id"] for p in answered_pieces(db_session, owner)] == ["dp-cur"]


# ── Masterplan reaches RippleTrace by a call-time syscall, never an import ──────────────


def test_the_syscall_grants_the_capability_its_name_infers():
    import AINDY.main  # noqa: F401  registers the app's syscalls
    from AINDY.kernel.syscall_dispatcher import _infer_dispatch_capability
    from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

    name = "sys.v1.rippletrace.get_answered_pieces"
    assert SYSCALL_REGISTRY[name].capability == "rippletrace.read" == _infer_dispatch_capability(name)


def test_the_syscall_reads_the_callers_pieces_not_a_payload_user(monkeypatch):
    from AINDY.kernel.syscall_registry import SyscallContext
    from apps.rippletrace import syscalls
    from apps.rippletrace.services import piece_answers

    seen = {}
    monkeypatch.setattr(syscalls, "_session_from_context", lambda ctx: (object(), False))
    monkeypatch.setattr(piece_answers, "answered_pieces", lambda db, user_id: seen.setdefault("user", user_id) and [])
    ctx = SyscallContext(execution_unit_id="eu", user_id="caller", capabilities=["rippletrace.read"], trace_id="t")
    assert syscalls._handle_get_answered_pieces({"user_id": "someone-else"}, ctx) == {"pieces": []}
    assert seen == {"user": "caller"}


def test_masterplan_asks_through_the_dispatcher_as_the_owner(monkeypatch):
    import AINDY.kernel.syscall_dispatcher as dispatcher

    calls = []

    class Fake:
        def dispatch(self, name, payload, ctx):
            calls.append((name, ctx.user_id, ctx.capabilities))
            return {"status": "success", "data": {"pieces": [{"title": "T", "answers": []}]}}

    monkeypatch.setattr(dispatcher, "get_dispatcher", lambda: Fake())
    owner = uuid.uuid4()
    assert rw._answered_pieces(object(), owner) == [{"title": "T", "answers": []}]
    assert calls == [("sys.v1.rippletrace.get_answered_pieces", str(owner), ["rippletrace.read"])]
