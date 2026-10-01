"""content.draft — the agent writes from the owner's own work, and the result is a document.

Run 0aa01e33 (2026-09-30): recall returned six of the owner's AI Search pieces and the plan used none
of them (no prose tool, so ARM's code generator, handed a one-line brief). Then the owner asked where
the output goes. The properties: sources arrive in whatever shape a step reference gives, the owner's
own work first and a cross-post counted once; the draft cites what it used and lists it; it is saved
as the owner's document, editable and deletable by them only; and it is stamped with the run.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from apps.masterplan.services import draft_service as ds
from apps.masterplan.services import work_service as ws
from apps.masterplan.work_model import WorkDraft

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
OTHER = uuid.uuid4()


def _node(title, platform, text, part=1):
    return {
        "content": f"{title} ({platform}, 2025-03-03; part {part} of 5)\n\n{text}",
        "source": "published_work",
        "tags": ["published_work", platform.lower()],
        "extra": {"title": title, "url": f"https://{platform.lower()}.example/{part}", "platform": platform},
    }


RECALL = {"count": 3, "nodes": [
    _node("2025 ChatGPT Case Study: AI Search Optimization", "DEV", "AI models now replace search."),
    _node("2025 ChatGPT Case Study: AI Search Optimization", "Medium", "AI models now replace search."),  # cross-post
    {"content": "flow executed", "source": "system_event:flow", "extra": {}},
]}
RESEARCH = "GEO best practices\nhttps://example.com/geo\nStructure answers for engines."


# ── sources ───────────────────────────────────────────────────────────────────────────────


def test_a_whole_recall_result_and_research_text_together_become_sources_own_work_first():
    blocks = ds.normalize_sources([RESEARCH, RECALL])
    assert [b["kind"] for b in blocks][:1] == ["own"]
    titles = [b["title"] for b in blocks]
    assert titles.count("2025 ChatGPT Case Study: AI Search Optimization") == 1  # a cross-post is one source
    own = blocks[0]
    assert own["text"] == "AI models now replace search."  # the chunk header is not the text
    assert "GEO best practices" in titles


def test_no_sources_is_allowed_and_says_so():
    assert ds.normalize_sources(None) == []
    assert ds._render_sources([]) == "(none given)"


# ── writing ───────────────────────────────────────────────────────────────────────────────


def _complete(brief, sources_text):
    assert "[S1] OWN WORK: 2025 ChatGPT Case Study: AI Search Optimization" in sources_text
    return "# A Plan for Nodus\n\nBuild on the series [S1], not generic advice."


def test_a_draft_is_saved_as_the_owners_document_citing_what_it_used(db_session):
    ws.create_work(db_session, USER, {"name": "Nodus", "summary": "The orchestration language."})
    out = ds.write_draft(db_session, USER, brief="A marketing plan for Nodus", sources=RECALL,
                         work="nodus", complete=_complete)

    assert out["title"] == "A Plan for Nodus"
    assert out["sources_used"] == [{"title": "2025 ChatGPT Case Study: AI Search Optimization",
                                    "url": "https://dev.example/1", "own": True}]
    assert out["body"].endswith("## Sources\n\n- [S1] 2025 ChatGPT Case Study: AI Search Optimization — https://dev.example/1")
    row = db_session.query(WorkDraft).one()
    assert (row.user_id, row.brief, row.work_id is not None) == (USER, "A marketing plan for Nodus", True)


def test_a_brief_is_required():
    with pytest.raises(ValueError):
        ds.write_draft(None, USER, brief="  ", complete=_complete)


def test_only_the_owner_reads_edits_and_deletes(db_session):
    draft_id = ds.write_draft(db_session, USER, brief="b", sources=RECALL, complete=_complete)["draft_id"]
    for fn in (lambda: ds.get_draft(db_session, OTHER, draft_id),
               lambda: ds.update_draft(db_session, OTHER, draft_id, {"body": "x"}),
               lambda: ds.delete_draft(db_session, OTHER, draft_id)):
        with pytest.raises(HTTPException) as exc:
            fn()
        assert exc.value.status_code == 404
    assert ds.update_draft(db_session, USER, draft_id, {"body": "Edited."})["body"] == "Edited."
    assert [d["id"] for d in ds.list_drafts(db_session, USER)["drafts"]] == [draft_id]
    assert "body" not in ds.list_drafts(db_session, USER)["drafts"][0]
    ds.delete_draft(db_session, USER, draft_id)
    assert ds.list_drafts(db_session, USER)["drafts"] == []


def test_a_run_stamps_the_drafts_it_wrote(db_session):
    before = datetime.now(timezone.utc)
    draft_id = ds.write_draft(db_session, USER, brief="b", complete=lambda brief, src: "# Plan\n\nText.")["draft_id"]
    assert ds.attach_run(user_id=USER, run_id="run-9", since=None, db=db_session) == 1
    db_session.commit()
    assert db_session.get(WorkDraft, draft_id).run_id == "run-9"
    assert ds.attach_run(user_id=USER, run_id="run-10", since=before, db=db_session) == 0  # already stamped


# ── the tools the planner sees ────────────────────────────────────────────────────────────


def test_prose_goes_to_content_draft_and_recall_no_longer_calls_its_results_telemetry():
    from AINDY.agents.tool_registry import TOOL_REGISTRY
    import apps.agent.agents.tools as agent_tools
    import apps.arm.agents.tools as arm_tools
    import apps.masterplan.agents.tools as masterplan_tools

    for module in (agent_tools, arm_tools, masterplan_tools):
        module.register()
    recall = TOOL_REGISTRY["memory.recall"]["description"]
    assert "telemetry" not in recall and "published_work" in recall and "content.draft" in recall
    assert "content.draft" in TOOL_REGISTRY["arm.generate"]["description"]
    assert "tags" in TOOL_REGISTRY["memory.recall"]["args_schema"]["properties"]


def test_a_draft_is_told_the_owners_own_definition_of_success(db_session):
    """The Nodus plan (2026-09-30) closed on industry metrics: nothing held the owner's own."""
    work = ws.create_work(db_session, USER, {"name": "AI Search Optimization", "summary": "Entity work.",
                                             "kind": "practice"})
    ws.update_work(db_session, USER, work["id"], {"success_criteria": "Resolution, not rankings."})
    seen = {}

    def complete(brief, context):
        seen["context"] = context
        return "# Plan\n\nMeasured by resolution."

    ds.write_draft(db_session, USER, brief="A plan", sources=RECALL, complete=complete)
    assert context_has(seen["context"], "THE PERSON'S OWN DEFINITION OF SUCCESS",
                       "- AI Search Optimization: Resolution, not rankings.")
    assert "industry metrics" in ds._SYSTEM


def context_has(text, *parts):
    return all(part in text for part in parts)
