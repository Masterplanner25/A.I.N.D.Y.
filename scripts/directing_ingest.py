"""The laptop side of directing time (`docs/specs/DIRECTING_TIME_SPEC.md` §3): one ingester, two triggers.

`scripts/directing_hook.py` (Claude Code's `UserPromptSubmit`) and `scripts/directing_backfill.py` both read a
transcript with the phase A parser and post the events to `POST /apps/directing/events`. Events are keyed on the line's
`uuid`, so the two overlap safely and a run after an outage fills the gap.

Stdlib only, and it imports nothing from `apps` or the runtime: the parser is loaded from its file, so this runs under
any Python 3.9+ without the repo installed.

**Never sends text** (§6): an event is `{source, project, agent_session_id, source_event_id, occurred_at, agent_until}`,
and `post_events` refuses anything else. **Never leaves the laptop**: the api URL must be loopback.

Config: `~/.aindy/directing.json`, optional, `{"ignore_projects": ["C--dev-private"], "api_url": "http://127.0.0.1:8000"}`.
Key: the person's watcher key (decision 6, FR-70), `AINDY_WATCHER_KEY` or `~/.aindy/watcher_key`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import urllib.request
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

ROUTE = "/apps/directing/events"
BATCH = 500  # the route's MAX_BATCH
EVENT_KEYS = frozenset({"source", "project", "agent_session_id", "source_event_id", "occurred_at", "agent_until"})
DEFAULT_API_URL = "http://127.0.0.1:8000"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
PROJECTS_DIR = Path.home() / ".claude" / "projects"
AINDY_DIR = Path.home() / ".aindy"

_PARSER_PATH = Path(__file__).resolve().parent.parent / "apps" / "automation" / "services" / "directing_transcript.py"
_parser = None


def parser():
    """The phase A parser (`directing_transcript.py`), loaded from its file, not through the `apps` package."""
    global _parser
    if _parser is None:
        spec = importlib.util.spec_from_file_location("directing_transcript", _PARSER_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _parser = module
    return _parser


def load_config(home: Path = AINDY_DIR) -> dict:
    try:
        data = json.loads((home / "directing.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    ignore = data.get("ignore_projects") if isinstance(data, dict) else None
    api_url = data.get("api_url") if isinstance(data, dict) else None
    return {
        "ignore_projects": {str(p) for p in ignore} if isinstance(ignore, list) else set(),
        "api_url": api_url if isinstance(api_url, str) and api_url else DEFAULT_API_URL,
    }


def load_key(home: Path = AINDY_DIR) -> Optional[str]:
    key = os.environ.get("AINDY_WATCHER_KEY", "").strip()
    if key:
        return key
    try:
        return (home / "watcher_key").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def is_loopback(api_url: str) -> bool:
    parsed = urlparse(api_url)
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "") in LOOPBACK


def read_tail_lines(path: Path, max_bytes: int) -> list[str]:
    """The file's last `max_bytes`, as whole lines (a cut first line is dropped)."""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - max_bytes)
        handle.seek(start)
        data = handle.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if start > 0 and lines else lines


def events_for(path: Path, *, tail_bytes: Optional[int] = None, ignore: Iterable[str] = ()) -> list[dict]:
    """The directing events in one transcript (or its tail), nothing for an ignored project.

    A tail is safe: an event is anchored on its prompt line, and its `agent_until` comes from the lines after it, which
    the tail always holds.
    """
    project = path.parent.name
    if project in set(ignore):
        return []
    p = parser()
    if tail_bytes is None:
        return p.events_from_file(str(path), project)
    return p.events_from_lines(read_tail_lines(path, tail_bytes), project)


def post_events(events: list[dict], *, api_url: str, key: str, timeout: float) -> dict:
    """Post in batches of 500; answers the summed counts. Raises on a refusal or an unreachable api."""
    if not is_loopback(api_url):
        raise ValueError(f"directing events go to this laptop only, not {api_url!r}")
    totals = {"accepted": 0, "duplicates": 0, "extended": 0, "rejected": 0}
    for start in range(0, len(events), BATCH):
        batch = events[start:start + BATCH]
        for event in batch:
            if set(event) != EVENT_KEYS:
                raise ValueError(f"an event carries {sorted(set(event) ^ EVENT_KEYS)}; refusing to send it")
        request = urllib.request.Request(
            api_url.rstrip("/") + ROUTE,
            data=json.dumps({"events": batch}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Platform-Key": key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
        body = body.get("data", body) if isinstance(body, dict) else {}
        for name in totals:
            totals[name] += int(body.get(name) or 0)
    return totals


def transcripts(root: Path = PROJECTS_DIR) -> list[Path]:
    """Every session transcript: `<root>/<project>/<session>.jsonl`. Subagent files (deeper) are sidechains."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*/*.jsonl") if p.is_file())
