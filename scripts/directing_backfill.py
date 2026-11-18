"""Backfill directing events from every Claude Code transcript (`DIRECTING_TIME_SPEC.md` §3.2).

    python scripts/directing_backfill.py                      # dry run: what would be sent, per project
    python scripts/directing_backfill.py --since 2026-10-10 --yes
    python scripts/directing_backfill.py --days 3 --yes --wait 900   # the watcher's sign-in task, daily

**A dry run is the default**; `--yes` posts. It walks `~/.claude/projects/<project>/<session>.jsonl` (Claude Code keeps
about 30 days), skips projects in `~/.aindy/directing.json`'s `ignore_projects`, and posts with the person's watcher
key. Idempotent with the hook: a prompt already sent is a duplicate, and a later reading moves its `agent_until` on.
Sends times and ids only, never a prompt's text.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import directing_ingest as ingest  # noqa: E402


def collect(root: Path, since: str | None, ignore: set[str]) -> tuple[list[dict], Counter, Counter]:
    """(events to send, events per project, events skipped per ignored project)."""
    events: list[dict] = []
    per_project: Counter = Counter()
    ignored: Counter = Counter()
    for path in ingest.transcripts(root):
        found = ingest.events_for(path)
        if since:
            found = [e for e in found if e["occurred_at"] >= since]
        if not found:
            continue
        if path.parent.name in ignore:
            ignored[path.parent.name] += len(found)
            continue
        events.extend(found)
        per_project[path.parent.name] += len(found)
    events.sort(key=lambda e: e["occurred_at"])
    return events, per_project, ignored


def wait_for_api(api_url: str, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        try:
            with urllib.request.urlopen(api_url.rstrip("/") + "/api/version", timeout=5) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(15)


def main(argv: list[str] | None = None, *, root: Path | None = None, home: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--since", help="only prompts on or after this date (YYYY-MM-DD, UTC)")
    window.add_argument("--days", type=int, help="only prompts from the last N days")
    parser.add_argument("--yes", action="store_true", help="post the events (default: dry run)")
    parser.add_argument("--dry-run", action="store_true", help="the default; say it explicitly if you like")
    parser.add_argument("--wait", type=int, default=0, metavar="SECONDS",
                        help="with --yes, wait up to this long for the api to answer first (sign-in)")
    args = parser.parse_args(argv)

    home = home or ingest.AINDY_DIR
    root = root or ingest.PROJECTS_DIR
    config = ingest.load_config(home)
    since = args.since
    if args.days is not None:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    if since:
        try:
            datetime.strptime(since, "%Y-%m-%d")
        except ValueError:
            parser.error("--since takes YYYY-MM-DD")

    events, per_project, ignored = collect(root, since, config["ignore_projects"])
    print(f"{len(events)} prompt(s) across {len(per_project)} project(s)" + (f" since {since}" if since else ""))
    for project, count in per_project.most_common():
        print(f"  {count:6d}  {project}")
    if ignored:
        print(f"ignored (directing.json): {sum(ignored.values())} prompt(s) in {', '.join(sorted(ignored))}")

    if not args.yes:
        print("dry run: nothing sent. Run again with --yes to post.")
        return 0
    if not events:
        return 0
    key = ingest.load_key(home)
    if not key:
        print("no watcher key: set AINDY_WATCHER_KEY or write ~/.aindy/watcher_key", file=sys.stderr)
        return 2
    if args.wait and not wait_for_api(config["api_url"], args.wait):
        print(f"the api at {config['api_url']} did not answer within {args.wait}s; nothing sent", file=sys.stderr)
        return 3
    counts = ingest.post_events(events, api_url=config["api_url"], key=key, timeout=60)
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
