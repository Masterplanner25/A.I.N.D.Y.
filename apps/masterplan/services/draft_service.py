"""Drafts: what the agent writes for the owner, written from their own work, and kept as documents.

Run 0aa01e33 (2026-09-30) asked for a marketing plan "using my published AI Search Optimization work".
Recall returned six of the owner's own pieces, and the plan never used them: the planner had no tool
for prose and borrowed ARM's code generator, passed it a one-paragraph brief instead of the recalled
text, and the result was generic GEO advice. Then the owner asked where the output goes, and the
answer was a step result, a memory node and a task, none of them a document.

`content.draft` takes a brief and the sources by step reference, writes from the owner's own pieces
first (cited inline as [S1], [S2] …), and saves a `WorkDraft` the owner reads in Collaborator.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.masterplan.work_model import Work, WorkDraft

logger = logging.getLogger(__name__)

#: The drafting model and its budget. `AINDY_DRAFT_MODEL` overrides.
DRAFT_MODEL = "gpt-4o"
DRAFT_MAX_TOKENS = 3_000
#: Source text sent with a brief, at most, and per source.
SOURCES_MAX_CHARS = 24_000
SOURCE_MAX_CHARS = 4_000
SOURCES_MAX = 12
BODY_MAX_CHARS = 100_000

_SYSTEM = """You write documents for one person: plans, outlines, article drafts.

You are given a BRIEF and numbered SOURCES. Sources marked OWN WORK are the person's own published
writing: build on them first. Use their arguments, terms, methods and examples, and write in their
voice where it shows. Use other sources second, for outside facts.

Cite a source inline as [S1], [S2] wherever you use it. Never attribute to the person anything their
OWN WORK sources do not say. Do not invent statistics, results or quotes. When the sources do not cover
part of the brief, say so plainly rather than filling the gap with generic advice.

Output markdown: the first line is the title as '# Title', then the document. Do not add a sources
list at the end; it is appended for you."""


def _uid(user_id: Any):
    uid = parse_user_id(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="user_id is required")
    return uid


def _refuse(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": "draft_refused", "message": message})


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def normalize_sources(raw: Any) -> list[dict]:
    """Whatever the planner hands over, as `{title, url, platform, kind, text}` blocks.

    Accepts recalled memory nodes (a list, or memory.recall's whole `{nodes: [...]}` result), a
    research result's text (title / url / snippet blocks), or plain strings. A piece cross-posted to
    two platforms is one source, not two."""
    from apps.masterplan.services.market_service import sources_evidence

    # Two step references arrive as a list of results: flatten them, and a whole recall result
    # ({count, nodes}) into its nodes.
    items: list = []
    pending = [raw]
    while pending:
        value = pending.pop(0)
        if isinstance(value, list):
            pending[:0] = value
        elif isinstance(value, dict) and isinstance(value.get("nodes"), list):
            pending[:0] = value["nodes"]
        elif isinstance(value, (dict, str)):
            items.append(value)

    blocks: list[dict] = []
    seen: set[str] = set()

    def add(title: str, url: str | None, platform: str | None, kind: str, text: str) -> None:
        key = _norm(title) or _norm(text[:120])
        if not text.strip() or key in seen:
            return
        seen.add(key)
        blocks.append({"title": title.strip()[:300] or "(untitled)", "url": url, "platform": platform,
                       "kind": kind, "text": text.strip()[:SOURCE_MAX_CHARS]})

    for item in items:
        if isinstance(item, dict):
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            content = str(item.get("content") or item.get("text") or "")
            own = item.get("source") == "published_work" or "published_work" in (item.get("tags") or [])
            title = str(extra.get("title") or item.get("title") or content.split("\n", 1)[0])
            # A published chunk's first line is its header ("Title (DEV, 2025-03-03; part 1 of 5)").
            body = content.split("\n\n", 1)[1] if own and "\n\n" in content else content
            add(title, extra.get("url") or item.get("url"), extra.get("platform"), "own" if own else "other", body)
        elif isinstance(item, str):
            parsed = sources_evidence(item, limit=SOURCES_MAX)
            if parsed:
                for entry in parsed:
                    head, _, rest = entry["claim"].partition(": ")
                    add(head, entry["source_url"], None, "other", rest or head)
            else:
                add(item.split("\n", 1)[0][:120], None, None, "other", item)
        if len(blocks) >= SOURCES_MAX:
            break

    # Fit the total budget, the owner's own work first.
    blocks.sort(key=lambda b: b["kind"] != "own")
    kept, total = [], 0
    for block in blocks:
        if total + len(block["text"]) > SOURCES_MAX_CHARS:
            continue
        kept.append(block)
        total += len(block["text"])
    return kept


def _render_sources(blocks: list[dict]) -> str:
    lines = []
    for i, b in enumerate(blocks, start=1):
        label = "OWN WORK" if b["kind"] == "own" else "OTHER"
        where = ", ".join(p for p in (b.get("platform"), b.get("url")) if p)
        lines.append(f"[S{i}] {label}: {b['title']}{f' ({where})' if where else ''}\n{b['text']}")
    return "\n\n".join(lines) or "(none given)"


def _draft_model() -> str:
    import os

    return (os.getenv("AINDY_DRAFT_MODEL") or "").strip() or DRAFT_MODEL


def _complete(brief: str, sources_text: str) -> str:
    from AINDY.config import settings
    from AINDY.platform_layer.external_call_service import perform_external_call
    from AINDY.platform_layer.openai_client import chat_completion, get_openai_client

    model = _draft_model()
    completion = perform_external_call(
        service_name="openai",
        endpoint="chat.completions.create",
        model=model,
        method="openai.chat",
        extra={"purpose": "content_draft"},
        operation=lambda: chat_completion(
            get_openai_client(),
            model=model,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": f"BRIEF\n{brief}\n\nSOURCES\n{sources_text}"}],
            timeout=max(float(settings.OPENAI_CHAT_TIMEOUT_SECONDS or 0), 120.0),
            temperature=0.4,
            max_tokens=DRAFT_MAX_TOKENS,
        ),
    )
    return (completion.choices[0].message.content or "").strip()


def write_draft(db: Session, user_id: Any, *, brief: str, sources: Any = None, title: str | None = None,
                work: str | None = None, complete=None) -> dict:
    """Write a draft from the brief and its sources, save it, and return it with what it cited."""
    uid = _uid(user_id)
    brief = (brief or "").strip()
    if not brief:
        raise ValueError("content.draft needs a brief: what to write, for whom, and why")
    blocks = normalize_sources(sources)
    text = (complete or _complete)(brief, _render_sources(blocks))
    if not text:
        raise RuntimeError("the drafting model returned nothing")

    heading = re.match(r"^#\s+(.+)$", text.splitlines()[0]) if text else None
    final_title = (title or (heading.group(1) if heading else "") or brief[:80]).strip()[:300]
    cited = sorted({int(n) for n in re.findall(r"\[S(\d+)\]", text) if 0 < int(n) <= len(blocks)})
    used = [blocks[n - 1] for n in cited]
    if used:
        text += "\n\n## Sources\n\n" + "\n".join(
            f"- [S{n}] {blocks[n - 1]['title']}" + (f" — {blocks[n - 1]['url']}" if blocks[n - 1].get("url") else "")
            for n in cited
        )

    work_id = None
    if work:
        target = _norm(work)
        match = next((w for w in db.query(Work).filter(Work.user_id == uid).all() if _norm(w.name) == target), None)
        work_id = match.id if match else None

    draft = WorkDraft(
        user_id=uid, title=final_title, brief=brief, body=text[:BODY_MAX_CHARS], work_id=work_id,
        sources=[{k: b.get(k) for k in ("title", "url", "platform", "kind")} for b in used], model=_draft_model(),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return {
        "draft_id": draft.id,
        "title": draft.title,
        "body": draft.body,
        "sources_used": [{"title": b["title"], "url": b.get("url"), "own": b["kind"] == "own"} for b in used],
    }


# ── The owner's side: read, edit, delete ──────────────────────────────────────────────────


def serialize_draft(draft: WorkDraft, *, body: bool = True) -> dict:
    out = {
        "id": draft.id, "title": draft.title, "brief": draft.brief, "run_id": draft.run_id,
        "work_id": draft.work_id, "sources": draft.sources or [], "model": draft.model,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        "words": len((draft.body or "").split()),
    }
    if body:
        out["body"] = draft.body
    return out


def _owned(db: Session, uid, draft_id: str) -> WorkDraft:
    draft = db.query(WorkDraft).filter(WorkDraft.id == draft_id, WorkDraft.user_id == uid).first()
    if draft is None:
        raise _refuse(404, "draft not found")
    return draft


def list_drafts(db: Session, user_id: Any) -> dict:
    uid = _uid(user_id)
    drafts = db.query(WorkDraft).filter(WorkDraft.user_id == uid).order_by(WorkDraft.created_at.desc()).all()
    return {"drafts": [serialize_draft(d, body=False) for d in drafts]}


def get_draft(db: Session, user_id: Any, draft_id: str) -> dict:
    return serialize_draft(_owned(db, _uid(user_id), draft_id))


def update_draft(db: Session, user_id: Any, draft_id: str, data: dict) -> dict:
    """The owner edits the title or the text."""
    draft = _owned(db, _uid(user_id), draft_id)
    if "title" in data:
        title = str(data.get("title") or "").strip()
        if not title:
            raise _refuse(422, "a draft needs a title")
        draft.title = title[:300]
    if "body" in data:
        body = str(data.get("body") or "")
        if not body.strip():
            raise _refuse(422, "a draft needs text; delete it instead")
        draft.body = body[:BODY_MAX_CHARS]
    db.commit()
    db.refresh(draft)
    return serialize_draft(draft)


def delete_draft(db: Session, user_id: Any, draft_id: str) -> dict:
    draft = _owned(db, _uid(user_id), draft_id)
    db.delete(draft)
    db.commit()
    return {"deleted": True, "id": draft_id}


def attach_run(*, user_id: Any, run_id: str, since, db: Session) -> int:
    """Stamp the drafts a run wrote with the run's id, when it completes. Tools are not handed their
    run, so drafts are matched to it afterwards: the owner's unattached drafts since the run began."""
    uid = parse_user_id(user_id)
    if uid is None or not run_id:
        return 0
    query = db.query(WorkDraft).filter(WorkDraft.user_id == uid, WorkDraft.run_id.is_(None))
    if since is not None:
        query = query.filter(WorkDraft.created_at >= since)
    count = 0
    for draft in query.all():
        draft.run_id = str(run_id)
        count += 1
    return count
