"""Which of the owner's published pieces answer what AI search got wrong (ARTICLE_ANSWERS_SPEC §2, phase C).

The tie between two things the app already keeps:
- the Resolution Check's latest finished run: its questions (*"What is Nodus?"*, *"Who is Shawn Knight?"*,
  *"How are A and B related?"*) and each engine's verdict;
- what each published piece answers, stored per piece (phase B2), read through
  `sys.v1.rippletrace.get_answered_pieces`: masterplan reaches other domains by call-time syscalls only.

For every question the engines did not fully resolve, it lists the owner's pieces that answer questions
**about** that subject, each with the question it answers and the passage. That is the signal worth
surfacing: *the engines got this wrong or could not answer it, and here is what your published writing
says about it*. It does not claim a piece answers the engines' exact question; matching names cannot tell
"What is A.I.N.D.Y.?" from "What still needed to happen after the A.I.N.D.Y. prototype?" (found live,
2026-11-08). The owner reads the question and judges.

**The match is deterministic and explainable, no model call:** a stored answer matches a question when
the question it answers names the question's subject (for a relation, one subject there and both in its
question or passage; a passage that merely mentions a name does not count) and its kind fits the question (a *what is* question takes *what is*, *how* or *why* answers; a person takes *who*).
Names are compared without case or punctuation, so "A.I.N.D.Y." matches "AINDY" and "Aindy-runtime"
matches "aindy runtime".

Disambiguation comes from many signals, never one article (owner, 2026-11-08). So this reports which
pieces bear on a gap; it never says a piece closes it.

Read-only. Not in the Infinity score (decision 4).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: Verdicts that count as the engines getting it: the owner's entity, or (for a shared name) one of the
#: name's listed meanings. Anything else is a gap a piece may bear on.
RESOLVED = {"resolved", "listed"}

#: The answer kinds that take on each question kind.
KIND_FITS = {
    "direct": {"what_is", "how", "why", "other"},
    "person-bare": {"who", "what_is", "other"},
    "person-context": {"who", "what_is", "other"},
    "relation": {"compared_with", "how", "why", "what_is", "other"},
}

MAX_PIECES_PER_QUESTION = 5
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    """Lowercase word tokens, with runs of single letters joined, so "a.i.n.d.y." reads as "aindy"."""
    out: list[str] = []
    run = ""
    for token in _WORD.findall((text or "").lower()):
        if len(token) == 1 and token.isalpha():
            run += token
            continue
        if run:
            out.append(run)
            run = ""
        out.append(token)
    if run:
        out.append(run)
    return out


def names(text: str, name: str) -> bool:
    """Whether ``text`` names ``name`` as whole words (or as one joined word: "aindy runtime" / "aindyruntime")."""
    needle = _tokens(name)
    if not needle:
        return False
    hay = _tokens(text)
    width = len(needle)
    if any(hay[i:i + width] == needle for i in range(len(hay) - width + 1)):
        return True
    return "".join(needle) in hay


def _subjects(question: dict) -> list[str]:
    if question.get("kind") == "relation":
        parts = str(question.get("key") or "").split(":")
        return parts[1:3] if len(parts) >= 3 else [question.get("subject")]
    return [question.get("subject")]


def _answered_pieces(db: Session, uid) -> list[dict]:
    """The owner's pieces with stored answers, from RippleTrace through a call-time syscall: masterplan
    imports no other domain (`test_import_boundaries`), and the syscall reads only the caller's pieces."""
    import uuid as _uuid

    from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

    ctx = SyscallContext(execution_unit_id=str(_uuid.uuid4()), user_id=str(uid),
                         capabilities=["rippletrace.read"], trace_id="", metadata={"_db": db})
    result = get_dispatcher().dispatch("sys.v1.rippletrace.get_answered_pieces", {}, ctx)
    if result.get("status") != "success":
        raise RuntimeError(result.get("error") or "answered pieces syscall failed")
    return list((result.get("data") or {}).get("pieces") or [])


def answered_in_writing(db: Session, uid, *, pieces: list[dict] | None = None) -> dict[str, dict]:
    """Per question key of the latest finished check that the engines did not fully resolve: the
    question, how the engines did, and the owner's pieces that answer questions about its subject."""
    from apps.masterplan.services.resolution_review import _resolved_phrase
    from apps.masterplan.work_model import ResolutionAnswer, ResolutionRun, Work

    run = (db.query(ResolutionRun).filter(ResolutionRun.user_id == uid, ResolutionRun.status == "done")
           .order_by(ResolutionRun.created_at.desc()).first())
    if run is None:
        return {}
    verdicts: dict[str, list[dict]] = {}
    for answer in db.query(ResolutionAnswer).filter(ResolutionAnswer.run_id == run.id).all():
        if answer.scores and not answer.error:
            verdicts.setdefault(answer.question_key, []).append(answer.scores)

    work_names = {w.id: w.name for w in db.query(Work.id, Work.name).filter(Work.user_id == uid).all()}
    if pieces is None:
        pieces = _answered_pieces(db, uid)

    out: dict[str, dict] = {}
    for question in run.questions or []:
        scores = verdicts.get(question.get("key"))
        if not scores or all(s.get("resolution") in RESOLVED for s in scores):
            continue
        subject_names = [work_names.get(s) for s in _subjects(question)]
        if not subject_names or not all(subject_names):
            continue
        fits = KIND_FITS.get(question.get("kind"), set())
        found = []
        for piece in pieces:
            for answer in piece.get("answers") or []:
                if answer.get("kind") not in fits:
                    continue
                asked = answer.get("question") or ""
                text = f"{asked} {answer.get('passage') or ''}"
                # The question the piece answers must name the subject; a passage that only mentions it
                # is about something else ("Why did the writer start using Claude Code?" mentions Nodus,
                # and is not an answer to "What is Nodus?": found live, 2026-11-08). For a relation, one
                # name in the question and both in the question or passage.
                if any(names(asked, n) for n in subject_names) and all(names(text, n) for n in subject_names):
                    found.append({"title": piece["title"], "url": piece.get("url"),
                                  "drop_point_id": piece["drop_point_id"], "question": answer.get("question"),
                                  "passage": answer.get("passage"), "passage_found": answer.get("passage_found")})
                    break  # one answer per piece is enough to show it bears on the question
            if len(found) >= MAX_PIECES_PER_QUESTION:
                break
        out[question["key"]] = {"question": question.get("text"), "kind": question.get("kind"),
                                "subjects": subject_names, "engines": _resolved_phrase(scores), "pieces": found}
    return out


def writing_clause(answered: dict[str, dict], subject: str) -> str | None:
    """For the planner: the owner's pieces that answer questions about a not-resolved ``subject``."""
    titles: list[str] = []
    # The subject's own questions only, as the planner line itself counts them: a relation question is
    # not in the line, so its pieces are not either (a resolved Work must not read as a gap).
    own_keys = {f"{kind}:{subject}" for kind in ("direct", "person-bare", "person-context")}
    for key, entry in answered.items():
        if key not in own_keys or not entry["pieces"]:
            continue
        for piece in entry["pieces"]:
            if piece["title"] not in titles:
                titles.append(piece["title"])
    if not titles:
        return None
    shown = "; ".join(f'"{t}"' for t in titles[:2])
    more = f" and {len(titles) - 2} more" if len(titles) > 2 else ""
    return f"your published pieces answering questions about it: {shown}{more}"
