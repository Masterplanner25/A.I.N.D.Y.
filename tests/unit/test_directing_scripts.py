"""DIRECTING_TIME_SPEC phase B: the laptop-side ingester, hook and backfill (§3, §6)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.app_profile

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import directing_backfill as backfill  # noqa: E402
import directing_hook as hook  # noqa: E402
import directing_ingest as ingest  # noqa: E402

SESSION = "c7166330-6ae4-48e9-a604-5b34dd896722"
SECRET = "private words the person typed"


def _user(text, uid, ts):
    return json.dumps({"type": "user", "uuid": uid, "sessionId": SESSION, "timestamp": ts,
                       "message": {"role": "user", "content": text}})


def _assistant(ts):
    return json.dumps({"type": "assistant", "uuid": f"a-{ts}", "sessionId": SESSION, "timestamp": ts,
                       "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}})


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "projects"
    for project, prefix in (("C--dev-repo", "r"), ("C--dev-private", "p")):
        folder = root / project
        folder.mkdir(parents=True)
        (folder / f"{SESSION}.jsonl").write_text("\n".join([
            _user(SECRET, f"{prefix}1", "2026-11-17T01:00:00.000Z"),
            _assistant("2026-11-17T01:04:00.000Z"),
            _user(SECRET, f"{prefix}2", "2026-11-17T02:00:00.000Z"),
            _assistant("2026-11-17T02:01:00.000Z"),
        ]) + "\n", encoding="utf-8")
        # A subagent's file sits deeper and is a sidechain: never walked.
        sub = folder / SESSION / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-1.jsonl").write_text(_user("subagent", f"{prefix}s", "2026-11-17T01:30:00Z") + "\n")
    home = tmp_path / "aindy"
    home.mkdir()
    (home / "watcher_key").write_text("aindy_test_watcher_key\n")
    return root, home


@pytest.fixture
def sent(monkeypatch):
    """Capture what would be posted, as the api would answer."""
    batches: list[dict] = []

    class _Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        batches.append({"url": request.full_url, "headers": dict(request.header_items()), "body": body,
                        "timeout": timeout})
        return _Response(json.dumps({"accepted": len(body["events"]), "duplicates": 0, "extended": 0,
                                     "rejected": 0}).encode("utf-8"))

    monkeypatch.setattr(ingest.urllib.request, "urlopen", fake_urlopen)
    return batches


# ── the ingester ──────────────────────────────────────────────────────────────────────


def test_the_parser_is_loaded_from_its_file_not_through_apps():
    assert ingest.parser().SOURCE == "claude_code"
    assert ingest._PARSER_PATH.is_file()


def test_a_tail_gives_whole_lines_and_correct_agent_until(projects):
    root, _ = projects
    path = root / "C--dev-repo" / f"{SESSION}.jsonl"
    whole = ingest.events_for(path)
    size = path.stat().st_size
    second_prompt_at = path.read_bytes().index(b'"r2"')
    tail = ingest.events_for(path, tail_bytes=size - second_prompt_at + 200)
    assert [e["source_event_id"] for e in tail] == ["r2"]
    assert tail[0] == whole[1]
    assert whole[0]["agent_until"] == "2026-11-17T01:04:00.000Z"


def test_post_refuses_a_non_loopback_url_and_an_event_with_text(sent):
    event = {"source": "claude_code", "project": "p", "agent_session_id": "s", "source_event_id": "e",
             "occurred_at": "2026-11-17T01:00:00Z", "agent_until": None}
    with pytest.raises(ValueError, match="this laptop only"):
        ingest.post_events([event], api_url="https://example.com", key="k", timeout=1)
    with pytest.raises(ValueError, match="refusing"):
        ingest.post_events([dict(event, content=SECRET)], api_url="http://127.0.0.1:8000", key="k", timeout=1)
    assert sent == []


def test_post_batches_by_500_with_the_watcher_key(sent):
    events = [{"source": "claude_code", "project": "p", "agent_session_id": "s", "source_event_id": str(n),
               "occurred_at": "2026-11-17T01:00:00Z", "agent_until": None} for n in range(1001)]
    counts = ingest.post_events(events, api_url="http://127.0.0.1:8000", key="kk", timeout=1)
    assert [len(b["body"]["events"]) for b in sent] == [500, 500, 1]
    assert counts["accepted"] == 1001
    assert sent[0]["url"] == "http://127.0.0.1:8000/apps/directing/events"
    assert sent[0]["headers"]["X-platform-key"] == "kk"


def test_config_defaults_and_ignore_list(tmp_path):
    assert ingest.load_config(tmp_path) == {"ignore_projects": set(), "api_url": "http://127.0.0.1:8000"}
    (tmp_path / "directing.json").write_text(json.dumps({"ignore_projects": ["C--dev-private"]}))
    assert ingest.load_config(tmp_path)["ignore_projects"] == {"C--dev-private"}
    (tmp_path / "directing.json").write_text("not json")
    assert ingest.load_config(tmp_path)["ignore_projects"] == set()


# ── the hook ──────────────────────────────────────────────────────────────────────────


def test_the_hook_posts_the_tail_and_logs_no_text(projects, sent):
    root, home = projects
    path = root / "C--dev-repo" / f"{SESSION}.jsonl"
    fields = hook.run(hook.transcript_path(json.dumps({"transcript_path": str(path), "prompt": SECRET})), home=home)
    assert fields["accepted"] == 2 and fields["project"] == "C--dev-repo"
    assert SECRET not in json.dumps(sent)
    assert sent[0]["timeout"] == hook.POST_TIMEOUT_S
    log = (home / "directing_hook.log").read_text()
    assert "accepted=2" in log and SECRET not in log


def test_the_hook_sends_nothing_for_an_ignored_project_or_without_a_key(projects, sent):
    root, home = projects
    (home / "directing.json").write_text(json.dumps({"ignore_projects": ["C--dev-private"]}))
    private = root / "C--dev-private" / f"{SESSION}.jsonl"
    assert hook.run(str(private), home=home)["skipped"] == "ignored_project"
    (home / "watcher_key").unlink()
    repo = root / "C--dev-repo" / f"{SESSION}.jsonl"
    assert hook.run(str(repo), home=home)["skipped"] == "no_key"
    assert sent == []


@pytest.mark.parametrize("stdin", ["", "not json", json.dumps({"transcript_path": "/nowhere.jsonl"}), "[]"])
def test_the_hook_never_raises_on_bad_input(stdin, tmp_path, sent):
    fields = hook.run(hook.transcript_path(stdin), home=tmp_path)
    assert fields.get("skipped") == "no_transcript"


def test_the_hook_survives_an_api_that_is_down(projects, monkeypatch):
    root, home = projects

    def down(*args, **kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(ingest.urllib.request, "urlopen", down)
    path = root / "C--dev-repo" / f"{SESSION}.jsonl"
    assert hook.run(str(path), home=home)["error"] == "ConnectionRefusedError"


def test_the_hook_only_spawns_a_worker_with_the_path_never_the_prompt(monkeypatch, capsys):
    started = []
    monkeypatch.setattr(hook.subprocess, "Popen", lambda args, **kw: started.append((args, kw)))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript_path": "C:/t/s.jsonl", "prompt": SECRET})))
    assert hook.main([]) == 0
    (args, kwargs), = started
    assert args[-2:] == ["--worker", "C:/t/s.jsonl"] and "-I" in args
    assert SECRET not in json.dumps(args)
    assert kwargs["stdout"] is hook.subprocess.DEVNULL and kwargs["stdin"] is hook.subprocess.DEVNULL
    assert capsys.readouterr().out == ""


def test_the_hook_exits_0_when_everything_fails(monkeypatch, capsys):
    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(hook.subprocess, "Popen", boom)
    monkeypatch.setattr(hook, "run", boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"transcript_path": "C:/t/s.jsonl"})))
    assert hook.main([]) == 0
    assert hook.main(["--worker", "C:/t/s.jsonl"]) == 0
    assert capsys.readouterr().out == ""


# ── the backfill ──────────────────────────────────────────────────────────────────────


def test_the_backfill_is_a_dry_run_by_default(projects, sent, capsys):
    root, home = projects
    assert backfill.main([], root=root, home=home) == 0
    out = capsys.readouterr().out
    assert "4 prompt(s) across 2 project(s)" in out and "dry run" in out
    assert sent == []


def test_the_backfill_posts_with_yes_honours_since_and_the_ignore_list(projects, sent, capsys):
    root, home = projects
    (home / "directing.json").write_text(json.dumps({"ignore_projects": ["C--dev-private"]}))
    assert backfill.main(["--since", "2026-11-17", "--yes"], root=root, home=home) == 0
    ids = [e["source_event_id"] for b in sent for e in b["body"]["events"]]
    assert ids == ["r1", "r2"]  # no "p*" (ignored), no "rs" (subagent)
    assert "ignored (directing.json): 2 prompt(s) in C--dev-private" in capsys.readouterr().out
    sent.clear()
    assert backfill.main(["--since", "2026-11-18", "--yes"], root=root, home=home) == 0
    assert sent == []
