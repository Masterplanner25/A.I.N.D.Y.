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


def test_a_draft_about_a_work_is_given_what_the_owner_confirmed_and_denied(db_session):
    """Run 34f5871d (2026-10-14): a Nodus piece said Nodus "functions within" aindy-runtime, which the
    owner had denied. The drafter was given the Work's name and none of what it says."""
    from apps.masterplan.services import resolution_review as rr

    nodus = ws.create_work(db_session, USER, {"name": "Nodus", "summary": "An orchestration DSL\nand embedded runtime."})
    runtime = ws.create_work(db_session, USER, {"name": "aindy-runtime", "summary": "An execution substrate."})
    ws.add_link(db_session, USER, runtime["id"], to_work_id=nodus["id"], relation="built_on")
    ws.add_presence(db_session, USER, nodus["id"], {"platform": "GitHub", "url": "https://github.com/x/Nodus"})
    rr.decide_claim(db_session, USER, work_id=nodus["id"], claim="Nodus is the layer underneath aindy-runtime.",
                    decision="true")
    rr.decide_claim(db_session, USER, work_id=nodus["id"], claim="The runtime is the engine and Nodus is what it executes.",
                    decision="false")
    seen = {}

    def complete(brief, context):
        seen["context"] = context
        return "# Nodus\n\nText."

    ds.write_draft(db_session, USER, brief="Disambiguate Nodus", sources=RECALL, work="nodus", complete=complete)
    assert context_has(seen["context"],
                       "THE PERSON'S OWN FACTS ABOUT Nodus",
                       "- What it is (project): An orchestration DSL and embedded runtime.",
                       "- Connection: aindy-runtime built on Nodus",
                       "- On GitHub: https://github.com/x/Nodus",
                       "- Confirmed: Nodus is the layer underneath aindy-runtime.",
                       "NEVER SAY (denied by the person)\n- The runtime is the engine and Nodus is what it executes.")
    assert "never contradict" in ds._SYSTEM and "NEVER SAY" in ds._SYSTEM

    ds.write_draft(db_session, USER, brief="Something else", sources=RECALL, complete=complete)
    assert "OWN FACTS" not in seen["context"]  # no Work named: nothing added


def test_the_planner_is_told_to_pass_research_too_and_to_name_the_work():
    from AINDY.agents.tool_registry import TOOL_REGISTRY
    import apps.masterplan.agents.tools as masterplan_tools

    masterplan_tools.register()
    description = TOOL_REGISTRY["content.draft"]["description"]
    assert "BOTH as a list" in description and "`work`" in description


def test_a_draft_about_a_work_is_told_what_the_engines_brought_up_under_its_name(db_session):
    """Run 191bc9b8 (2026-10-14) described "Nodus Software" as general software solutions; the check had
    the engine saying it is a package manager for AI-agent tooling. The owner: disambiguate from what
    is specific to the language and from what actually comes up when searching Nodus."""
    from apps.masterplan.work_model import ResolutionAnswer, ResolutionRun

    nodus = ws.create_work(db_session, USER, {"name": "Nodus", "summary": "An orchestration DSL."})
    key = f"direct:{nodus['id']}"
    run = ResolutionRun(user_id=USER, scope="core", status="done", engines=["perplexity", "openai"],
                        questions=[{"key": key, "kind": "direct", "subject": nodus["id"], "text": "What is Nodus?"},
                                   {"key": "direct:other", "kind": "direct", "subject": "other", "text": "What is X?"}],
                        calls={})
    db_session.add(run)
    db_session.flush()
    db_session.add_all([
        ResolutionAnswer(run_id=run.id, user_id=USER, question_key=key, engine="perplexity",
                         answer="Nodus software: a package manager for AI-agent tooling. " + "x" * 8000,
                         scores={"resolution": "wrong", "other_entities": ["Nodus software", "Nodus Payments"]}),
        ResolutionAnswer(run_id=run.id, user_id=USER, question_key=key, engine="openai", answer="",
                         error="timeout"),
        ResolutionAnswer(run_id=run.id, user_id=USER, question_key="direct:other", engine="openai",
                         answer="About X.", scores={"resolution": "resolved", "other_entities": []}),
    ])
    db_session.commit()
    seen = {}

    def complete(brief, context):
        seen["context"] = context
        return "# Nodus\n\nText."

    ds.write_draft(db_session, USER, brief="Disambiguate Nodus", work="Nodus", complete=complete)
    context = seen["context"]
    assert context_has(context, "WHAT AI SEARCH ENGINES SAID WHEN ASKED ABOUT IT",
                       '- perplexity, asked "What is Nodus?": wrong; brought up Nodus software; Nodus Payments',
                       "a package manager for AI-agent tooling")
    assert "About X." not in context and "timeout" not in context  # another Work's answer; a failed call
    assert len(context) < 7_500  # each answer is cut, not sent whole
    system = " ".join(ds._SYSTEM.split())
    assert "Not to be confused with" in system and "never from general knowledge" in system
    assert "other names it goes by" in system


def test_a_shared_name_is_not_a_failure_the_draft_aims_to_be_listed_and_resolve_in_context():
    """Owner, 2026-10-14: "a bare Nodus or bare my name shouldn't directly resolve. I'm not the only
    Shawn Knight in the world, nor is Nodus the only thing named Nodus." """
    system = " ".join(ds._SYSTEM.split())
    assert "A shared name is not a failure" in system
    assert "one of the meanings an engine lists for the name" in system


def test_a_reasoning_model_is_sent_what_it_accepts(monkeypatch):
    """gpt-5.5 refuses `max_tokens` and any temperature but 1 (probed 2026-10-14)."""
    monkeypatch.delenv("AINDY_DRAFT_REASONING_EFFORT", raising=False)
    assert ds.DRAFT_MODEL == "gpt-5.5"
    assert ds._sampling("gpt-5.5") == {"max_completion_tokens": ds.DRAFT_REASONING_MAX_TOKENS,
                                       "reasoning_effort": "low"}
    assert ds._sampling("gpt-4o") == {"temperature": 0.4, "max_tokens": ds.DRAFT_MAX_TOKENS}
    monkeypatch.setenv("AINDY_DRAFT_REASONING_EFFORT", "medium")
    assert ds._sampling("o3")["reasoning_effort"] == "medium"
