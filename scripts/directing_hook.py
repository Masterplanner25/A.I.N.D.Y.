"""Claude Code `UserPromptSubmit` hook: post this session's new directing events (`DIRECTING_TIME_SPEC.md` §3.1).

Installed in the user-level `~/.claude/settings.json`, so it runs in every repo:

    "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "timeout": 3,
        "command": "\"C:/dev/aindy-apps-monolith/venv/Scripts/python.exe\" -I C:/dev/aindy-apps-monolith/scripts/directing_hook.py"}]}]}

**It cannot break or slow Claude Code:** a `UserPromptSubmit` hook holds the prompt until it returns, and a post takes
0.7-2 s (measured 2026-11-18). So the hook only starts a detached worker (`--worker <transcript path>`) and exits 0 at
once, printing nothing. The worker does the reading and posting, with a 10 s timeout. An api that is down, a missing
key or an odd transcript means nothing is sent; the next prompt's hook, or the daily backfill, picks the events up
(they are keyed on the line's `uuid`). The worker gets the transcript's path only, never the prompt.

It reads only the transcript's last megabyte: every prompt in it gets a correct `agent_until`, which is what moves
on between prompts. It sends times and ids only, never the prompt (the hook's stdin carries the prompt; this never
reads that field).

One line per run goes to `~/.aindy/directing_hook.log` (times and counts, no text). `newest_age_s` is how old the newest
prompt in the file was when the hook ran: near 0 means the prompt being submitted was already written (§3's ordering
question); minutes means it lands with the next prompt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TAIL_BYTES = 1_000_000
POST_TIMEOUT_S = 10.0
LOG_MAX_BYTES = 256_000


def _log(home: Path, fields: dict) -> None:
    try:
        path = home / "directing_hook.log"
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            path.replace(home / "directing_hook.log.1")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(stamp + " " + " ".join(f"{k}={v}" for k, v in fields.items()) + "\n")
    except Exception:
        pass


def _age_seconds(stamp: str) -> int:
    try:
        then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - then).total_seconds())
    except (TypeError, ValueError):
        return -1


def transcript_path(stdin_text: str) -> str:
    """The `transcript_path` from the hook's stdin; "" if there is none. Reads no other field."""
    try:
        payload = json.loads(stdin_text or "{}")
    except ValueError:
        return ""
    return str(payload.get("transcript_path") or "") if isinstance(payload, dict) else ""


def run(path: str, *, home: Path | None = None) -> dict:
    """The worker: ingest one transcript's tail; answers what it logged. Never raises."""
    started = time.monotonic()
    fields: dict = {}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import directing_ingest as ingest

        home = home or ingest.AINDY_DIR
        transcript = Path(path)
        if not transcript.name.endswith(".jsonl") or not transcript.is_file():
            fields["skipped"] = "no_transcript"
            return fields
        config = ingest.load_config(home)
        fields["project"] = transcript.parent.name
        if transcript.parent.name in config["ignore_projects"]:
            fields["skipped"] = "ignored_project"
            return fields
        key = ingest.load_key(home)
        if not key:
            fields["skipped"] = "no_key"
            return fields
        events = ingest.events_for(transcript, tail_bytes=TAIL_BYTES)
        fields["events"] = len(events)
        if events:
            fields["newest_age_s"] = _age_seconds(events[-1]["occurred_at"])
            counts = ingest.post_events(events, api_url=config["api_url"], key=key, timeout=POST_TIMEOUT_S)
            fields.update(counts)
    except Exception as exc:  # the api down, a refusal, a bad stdin: never the person's problem
        fields["error"] = type(exc).__name__
        status = getattr(exc, "code", None)
        if status:
            fields["status"] = status
    finally:
        fields["ms"] = int((time.monotonic() - started) * 1000)
        if home is not None:
            _log(home, fields)
    return fields


def spawn_worker(path: str) -> None:
    """Start `--worker <path>` detached from Claude Code, with no console and nothing inherited."""
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(
        [sys.executable, "-I", str(Path(__file__).resolve()), "--worker", path],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags, start_new_session=(os.name != "nt"), close_fds=True,
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) == 2 and argv[0] == "--worker":
            run(argv[1])
        else:
            path = transcript_path(sys.stdin.read(1_000_000))
            if path:
                spawn_worker(path)
    except BaseException:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
