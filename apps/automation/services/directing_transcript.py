"""Directing events from a Claude Code transcript (`DIRECTING_TIME_SPEC.md` §2, §3).

A transcript is `~/.claude/projects/<project>/<session>.jsonl`, one JSON object per line. Only a line the person typed
is a directing event. Most `type: "user"` lines are not: tool results, task notifications, local-command echoes,
compaction summaries, skill loads (measured 2026-11-16: 749 typed of about 10,500).

Pure stdlib, no app or runtime imports: the hook and the backfill run this on the laptop, outside the api.
**No prompt text ever leaves this module**: an event carries times, ids and the project folder name only (§6).
"""
from __future__ import annotations

import json
from typing import Iterable, Optional

SOURCE = "claude_code"

# A string prompt that starts with one of these was written by Claude Code, not typed.
_NOT_TYPED_PREFIXES = (
    "<task-notification>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<local-command-caveat>",
    "<system-reminder>",
    "[Cross-session delivery notice]",
    "[Request interrupted",
)


def is_typed_prompt(entry: dict) -> bool:
    """Is this transcript line a prompt the person typed?"""
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return False
    if entry.get("isMeta") or entry.get("isSidechain") or entry.get("isCompactSummary"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content.lstrip()
        return bool(text) and not text.startswith(_NOT_TYPED_PREFIXES)
    if isinstance(content, list):
        kinds = {block.get("type") for block in content if isinstance(block, dict)}
        if "tool_result" in kinds or "text" not in kinds:
            return False
        first = next((b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"), "")
        return not first.lstrip().startswith(_NOT_TYPED_PREFIXES)
    return False


def events_from_lines(lines: Iterable[str], project: str) -> list[dict]:
    """The directing events in one transcript, oldest first.

    Each event's `agent_until` is the last timestamp before the next typed prompt: the end of the agent's work on that
    instruction (decision 2). For the last prompt it is the file's last timestamp so far, and a later run moves it on.
    """
    events: list[dict] = []
    current: Optional[dict] = None
    for raw in lines:
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        stamp = entry.get("timestamp")
        if is_typed_prompt(entry):
            uuid, session = entry.get("uuid"), entry.get("sessionId")
            if not (uuid and session and stamp):
                continue
            current = {
                "source": SOURCE,
                "project": project,
                "agent_session_id": str(session)[:64],
                "source_event_id": str(uuid)[:64],
                "occurred_at": stamp,
                "agent_until": None,
            }
            events.append(current)
        elif (current is not None and is_agent_work(entry) and isinstance(stamp, str)
              and stamp > (current["agent_until"] or current["occurred_at"])):
            current["agent_until"] = stamp
    return events


def is_agent_work(entry: dict) -> bool:
    """Is this line the agent working: its own message, or a tool's result coming back to it?

    Claude Code also writes bookkeeping lines with timestamps: `api-request` as the person submits, `system`
    `away_summary` while they are away, `turn_duration`, `pr-link`, `attachment`. Counting those would stretch every
    `agent_until` to the next prompt (measured 2026-11-16), so they are not the agent's work.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("type") == "assistant":
        return True
    content = (entry.get("message") or {}).get("content")
    return (entry.get("type") == "user" and isinstance(content, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content))


def events_from_file(path: str, project: Optional[str] = None) -> list[dict]:
    """The directing events in the transcript at `path`; `project` defaults to its folder name."""
    import os

    folder = project or os.path.basename(os.path.dirname(os.path.abspath(path)))
    with open(path, encoding="utf-8", errors="replace") as handle:
        return events_from_lines(handle, folder)
