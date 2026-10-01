"""The Resolution Check — `RESOLUTION_CHECK_SPEC.md`, phase A.

The owner's definition of success for AI Search Optimization, measured: *"if someone directly searches
for Masterplan Infinite Weave, does it bring back the right entity … how much can it say about the
entity that's actually correct … can it pick up on the connections between the entities."*

Ground truth is only what the owner confirmed: their Works (now including the person and the brand),
the links between them, and their presence across the web with the header or bio they wrote there
(§2.2, the owner's control). Questions are generated from that model, asked of three answer engines
with live web search, and each answer is judged: the judge reports facts, code computes the owner's
three scores (the rule that fixed the lead judge). A run is answered a few questions per scheduled tick,
so a check never holds the api.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.masterplan.work_model import ResolutionAnswer, ResolutionRun, Work, WorkLink, WorkPresence

logger = logging.getLogger(__name__)

SCOPES = ("core", "full")
CORE_PROJECTS = 3
CORE_LINKS = 3
#: Engine answers judged per scheduled tick: a tick stays well under a minute.
TICK_PAIRS = 6
TICK_INTERVAL_MINUTES = 1
JUDGE_MODEL = "gpt-4o"
CREATOR_ROLES = ("creator", "author")

_tick_lock = threading.Lock()


def _uid(user_id: Any):
    uid = parse_user_id(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="user_id is required")
    return uid


def _refuse(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": "resolution_refused", "message": message})


def _host(url: str | None) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


# ── Ground truth: only what the owner confirmed ───────────────────────────────────────────


def ground_truth(db: Session, uid) -> dict:
    """Entities (Works), their presence, and the connections between them. A person who is the owner
    is implicitly connected to every Work whose role is creator or author: that is what the role says."""
    works = db.query(Work).filter(Work.user_id == uid).order_by(Work.created_at.asc()).all()
    presence: dict[str, list[dict]] = {}
    for row in db.query(WorkPresence).filter(WorkPresence.user_id == uid).all():
        presence.setdefault(row.work_id, []).append(
            {"platform": row.platform, "url": row.url, "self_description": row.self_description})
    entities = {
        w.id: {"id": w.id, "name": w.name, "kind": w.kind, "role": w.role, "status": w.status,
               "summary": w.summary, "url": w.url, "presence": presence.get(w.id, [])}
        for w in works
    }
    names = {w.id: w.name for w in works}
    links = [
        {"key": f"link:{link.id}", "a": link.from_work_id, "b": link.to_work_id, "relation": link.relation,
         "text": f"{names[link.from_work_id]} {link.relation.replace('_', ' ')} {names[link.to_work_id]}"}
        for link in db.query(WorkLink).filter(WorkLink.user_id == uid).all()
        if link.from_work_id in names and link.to_work_id in names
    ]
    explicit = {(link["a"], link["b"]) for link in links}
    for person in (w for w in works if w.kind == "person"):
        for work in works:
            if work.kind in ("person",) or work.role not in CREATOR_ROLES or (person.id, work.id) in explicit:
                continue
            links.append({"key": f"implied:{person.id}:{work.id}", "a": person.id, "b": work.id,
                          "relation": "created", "text": f"{person.name} created {work.name}", "implied": True})
    hosts = {_host(p.get("url")) for e in entities.values() for p in e["presence"] if p.get("url")}
    hosts |= {_host(e["url"]) for e in entities.values() if e.get("url")}
    return {"entities": entities, "links": links, "own_hosts": sorted(h for h in hosts if h)}


# ── Questions, generated from the model (§2.1) ────────────────────────────────────────────


def build_questions(truth: dict, scope: str) -> list[dict]:
    entities = list(truth["entities"].values())
    people = [e for e in entities if e["kind"] == "person"]
    brands = [e for e in entities if e["kind"] == "brand"]
    others = [e for e in entities if e["kind"] not in ("person", "brand")]
    if scope == "core":
        projects = [e for e in others if e["kind"] in ("project", "product")]
        projects.sort(key=lambda e: e["status"] != "active")
        others = projects[:CORE_PROJECTS]

    questions: list[dict] = []
    for brand in brands:
        questions.append({"key": f"direct:{brand['id']}", "kind": "direct", "subject": brand["id"],
                          "text": f"What is {brand['name']}?"})
    for person in people:
        questions.append({"key": f"person-bare:{person['id']}", "kind": "person-bare", "subject": person["id"],
                          "text": f"Who is {person['name']}?"})
        created = next((truth["entities"][link["b"]] for link in truth["links"]
                        if link["a"] == person["id"] and link["relation"] == "created"
                        and truth["entities"][link["b"]]["kind"] == "brand"), None)
        context = f"the founder of {created['name']}" if created else "the creator of " + (
            others[0]["name"] if others else "their work")
        questions.append({"key": f"person-context:{person['id']}", "kind": "person-context", "subject": person["id"],
                          "text": f"Who is {person['name']}, {context}?"})
    for entity in others:
        questions.append({"key": f"direct:{entity['id']}", "kind": "direct", "subject": entity["id"],
                          "text": f"What is {entity['name']}?"})

    asked = {q["subject"] for q in questions}
    # One question per PAIR, checking every confirmed link between the two. The first live check
    # (2026-09-30) asked "How are Nodus and Aindy-runtime related?" twice, because the owner has
    # confirmed two links between them (part of, and built on).
    pairs: dict[frozenset, list[dict]] = {}
    for link in truth["links"]:
        if not link.get("implied"):
            pairs.setdefault(frozenset((link["a"], link["b"])), []).append(link)
    chosen = list(pairs.values())
    if scope == "core":
        chosen = [group for group in chosen if group[0]["a"] in asked and group[0]["b"] in asked][:CORE_LINKS]
    for group in chosen:
        first = group[0]
        a, b = truth["entities"][first["a"]], truth["entities"][first["b"]]
        questions.append({"key": f"pair:{first['a']}:{first['b']}", "kind": "relation", "subject": first["a"],
                          "links": [link["key"] for link in group],
                          "text": f"How are {a['name']} and {b['name']} related?"})
    return questions


# ── Judging: the judge reports facts, code scores ─────────────────────────────────────────

_JUDGE_PROMPT = """You check one AI search engine's answer about one entity against facts its owner confirmed.
Report facts; do not score.

about: "subject" if the answer is about the SUBJECT described by the confirmed facts; "other" if it is about
  a different entity with the same or a similar name; "mixed" if it blends the subject with other entities;
  "none" if it does not identify any entity.
other_entities: names of any other, different entities the answer brings in under the same name.
claims: every factual claim the answer makes about the subject, each as {"text", "status"} where status is
  "correct" (consistent with the confirmed facts), "incorrect" (contradicts them) or "unverifiable"
  (the confirmed facts neither support nor contradict it).
facts_stated: the ids (F1, F2 …) of confirmed facts the answer states or clearly conveys.
links_stated: the ids (L1, L2 …) of confirmed connections the answer states or clearly conveys.

Return ONLY a JSON object with those keys."""


def _facts_for(entity: dict) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", entity.get("summary") or "") if len(s.strip()) > 3]
    facts = [f"{entity['name']} is a {entity['kind']}."] + sentences
    for p in entity.get("presence") or []:
        if p.get("self_description"):
            facts.append(f"On {p['platform']} it describes itself: {p['self_description']}")
        elif p.get("url"):
            facts.append(f"It is on {p['platform']} at {p['url']}.")
    return facts


def _links_for(truth: dict, question: dict) -> list[dict]:
    if question["kind"] == "relation":
        keys = set(question.get("links") or [question.get("link")])
        return [link for link in truth["links"] if link["key"] in keys]
    return [link for link in truth["links"] if question["subject"] in (link["a"], link["b"])]


def _judge_model() -> str:
    import os

    return (os.getenv("AINDY_RESOLUTION_JUDGE_MODEL") or "").strip() or JUDGE_MODEL


def judge_answer(question: dict, answer: dict, truth: dict) -> dict:
    from AINDY.config import settings
    from AINDY.platform_layer.external_call_service import perform_external_call
    from AINDY.platform_layer.openai_client import chat_completion, get_openai_client

    subject = truth["entities"][question["subject"]]
    facts = _facts_for(subject)
    links = _links_for(truth, question)
    user = (
        f"QUESTION: {question['text']}\n\nSUBJECT: {subject['name']}\nCONFIRMED FACTS:\n"
        + "\n".join(f"F{i}: {f}" for i, f in enumerate(facts, start=1))
        + "\n\nCONFIRMED CONNECTIONS:\n" + ("\n".join(f"L{i}: {link['text']}" for i, link in enumerate(links, start=1)) or "(none)")
        + f"\n\nANSWER:\n{answer.get('answer') or ''}\n\nCITED: {', '.join(answer.get('citations') or []) or '(none)'}"
    )
    model = _judge_model()
    completion = perform_external_call(
        service_name="openai", endpoint="chat.completions.create", model=model, method="openai.chat",
        extra={"purpose": "resolution_judgement"},
        operation=lambda: chat_completion(
            get_openai_client(), model=model, temperature=0, timeout=settings.OPENAI_CHAT_TIMEOUT_SECONDS,
            messages=[{"role": "system", "content": _JUDGE_PROMPT}, {"role": "user", "content": user}]),
    )
    text = (completion.choices[0].message.content or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return {**json.loads(match.group(0) if match else text), "_facts": facts, "_links": [link["text"] for link in links]}


RESOLUTION_LABELS = {"subject": "resolved", "mixed": "mixed", "other": "wrong", "none": "unknown"}


def score(judgement: dict, citations: list[str], truth: dict) -> dict:
    """The owner's three criteria, as numbers, from the judge's facts (§3)."""
    facts = judgement.get("_facts") or []
    links = judgement.get("_links") or []
    claims = [c for c in judgement.get("claims") or [] if isinstance(c, dict)]
    count = {s: sum(1 for c in claims if c.get("status") == s) for s in ("correct", "incorrect", "unverifiable")}

    def ids(key: str, prefix: str, total: int) -> set[int]:
        out = set()
        for value in judgement.get(key) or []:
            m = re.fullmatch(rf"{prefix}(\d+)", str(value).strip())
            if m and 1 <= int(m.group(1)) <= total:
                out.add(int(m.group(1)))
        return out

    facts_stated = ids("facts_stated", "F", len(facts))
    links_stated = ids("links_stated", "L", len(links))
    own = set(truth.get("own_hosts") or [])
    own_cited = sorted({_host(c) for c in citations or [] if _host(c) in own})
    return {
        "resolution": RESOLUTION_LABELS.get(str(judgement.get("about") or "none"), "unknown"),
        "other_entities": [str(n) for n in judgement.get("other_entities") or []][:5],
        "claims_correct": count["correct"], "claims_incorrect": count["incorrect"],
        "claims_unverifiable": count["unverifiable"],
        "facts_covered": len(facts_stated), "facts_total": len(facts),
        "links_stated": len(links_stated), "links_total": len(links),
        "own_sources_cited": own_cited, "citations": len(citations or []),
    }


# ── Runs ──────────────────────────────────────────────────────────────────────────────────


def serialize_run(run: ResolutionRun, answers: list[ResolutionAnswer] | None = None) -> dict:
    questions = run.questions or []
    out = {
        "id": run.id, "scope": run.scope, "status": run.status, "engines": run.engines, "calls": run.calls or {},
        "error": run.error, "questions": questions,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "expected": len(questions) * len(run.engines or []),
    }
    if answers is not None:
        out["answered"] = len(answers)
        out["answers"] = [
            {"question_key": a.question_key, "engine": a.engine, "answer": a.answer, "citations": a.citations or [],
             "claims": (a.judgement or {}).get("claims") or [], "scores": a.scores, "error": a.error}
            for a in answers
        ]
    return out


def start_run(db: Session, user_id: Any, scope: str = "core") -> dict:
    from apps.masterplan.services.resolution_engines import configured_engines

    uid = _uid(user_id)
    if scope not in SCOPES:
        raise _refuse(422, f"scope must be one of: {', '.join(SCOPES)}")
    active = db.query(ResolutionRun).filter(ResolutionRun.user_id == uid,
                                            ResolutionRun.status.in_(("pending", "running"))).first()
    if active is not None:
        raise _refuse(409, "a check is already running; it finishes on its own in a few minutes")
    truth = ground_truth(db, uid)
    questions = build_questions(truth, scope)
    if not questions:
        raise _refuse(422, "nothing to check yet: add yourself (kind person) and your brand as Works")
    run = ResolutionRun(user_id=uid, scope=scope, status="pending", questions=questions,
                        engines=configured_engines(), calls={})
    db.add(run)
    db.commit()
    db.refresh(run)
    return serialize_run(run, [])


def get_run(db: Session, user_id: Any, run_id: str | None = None) -> dict | None:
    uid = _uid(user_id)
    query = db.query(ResolutionRun).filter(ResolutionRun.user_id == uid)
    run = (query.filter(ResolutionRun.id == run_id).first() if run_id
           else query.order_by(ResolutionRun.created_at.desc()).first())
    if run is None:
        if run_id:
            raise _refuse(404, "check not found")
        return None
    answers = db.query(ResolutionAnswer).filter(ResolutionAnswer.run_id == run.id).order_by(
        ResolutionAnswer.created_at.asc()).all()
    return serialize_run(run, answers)


def resolution_overview(db: Session, user_id: Any) -> dict:
    """The latest check, plus the owner's own self-descriptions side by side (the control)."""
    uid = _uid(user_id)
    truth = ground_truth(db, uid)
    self_descriptions = [
        {"work": e["name"], "kind": e["kind"], "platform": p["platform"], "url": p.get("url"),
         "self_description": p["self_description"]}
        for e in truth["entities"].values() if e["kind"] in ("person", "brand")
        for p in e["presence"] if p.get("self_description")
    ]
    return {"latest": get_run(db, uid), "self_descriptions": self_descriptions,
            "entities": {k: v["name"] for k, v in truth["entities"].items()}}


def process_run(db: Session, run: ResolutionRun, *, limit: int = TICK_PAIRS,
                ask: dict[str, Callable[[str], dict]] | None = None, judge=None) -> int:
    """Answer and judge up to `limit` outstanding (question, engine) pairs. Commits per answer."""
    from apps.masterplan.services.resolution_engines import ENGINES

    ask = ask or ENGINES
    judge = judge or judge_answer
    truth = ground_truth(db, run.user_id)
    done = {(a.question_key, a.engine) for a in db.query(ResolutionAnswer.question_key, ResolutionAnswer.engine)
            .filter(ResolutionAnswer.run_id == run.id)}
    pending = [(q, e) for q in run.questions or [] for e in run.engines or [] if (q["key"], e) not in done]
    run.status = "running"
    handled = 0
    for question, engine in pending[:limit]:
        calls = dict(run.calls or {})
        row = ResolutionAnswer(run_id=run.id, user_id=run.user_id, question_key=question["key"], engine=engine)
        try:
            answer = ask[engine](question["text"])
            calls[engine] = calls.get(engine, 0) + 1
            row.answer, row.citations = answer.get("answer"), answer.get("citations") or []
            if question["subject"] in truth["entities"]:
                judgement = judge(question, answer, truth)
                calls["judge"] = calls.get("judge", 0) + 1
                row.judgement = judgement
                row.scores = score(judgement, row.citations, truth)
        except Exception as exc:  # one engine or judgement failing must not stop the check
            row.error = str(exc)[:500]
            logger.warning("[resolution] %s / %s failed: %s", engine, question["key"], exc)
        run.calls = calls
        db.add(row)
        db.commit()
        handled += 1
    if len(pending) <= limit:
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    return handled


def resolution_tick() -> dict:
    """Scheduled job body: advance each open check by one batch. Its own session; non-blocking guard."""
    if not _tick_lock.acquire(blocking=False):
        return {"skipped": True}
    from AINDY.db.database import SessionLocal

    db = SessionLocal()
    summary = {"runs": 0, "answered": 0, "skipped": False}
    try:
        for run in db.query(ResolutionRun).filter(ResolutionRun.status.in_(("pending", "running"))).order_by(
                ResolutionRun.created_at.asc()).all():
            summary["answered"] += process_run(db, run)
            summary["runs"] += 1
    except Exception as exc:
        db.rollback()
        logger.warning("[resolution] tick failed: %s", exc)
        summary["error"] = str(exc)
    finally:
        db.close()
        _tick_lock.release()
    return summary
