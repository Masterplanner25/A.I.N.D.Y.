#!/usr/bin/env python
"""Backfill a published back-catalogue into rippletrace drop points.

RSS/Atom feeds are *windows*, not archives — Medium returns its 10 most recent posts,
dev.to 12, Substack 20. Registering a feed is therefore a permanent supply of *future*
publications and says nothing about anything older. Measured 2026-09-06: 42 drop points
from feeds against 143 dev.to articles and 73+ Substack posts actually published.

This script closes that gap for the two platforms that expose a real archive API. It is a
CATCH-UP, not a source: the registered feeds already handle everything published from now
on, so this is expected to run once per platform and then not again.

    python scripts/backfill_content_archive.py --user-id <uuid> --devto masterplanner25
    python scripts/backfill_content_archive.py --user-id <uuid> --substack masterplanner25 --apply

Dry-run by default. Nothing is written without ``--apply``.

── Why these two platforms and not the other two ──────────────────────────────────────
    dev.to     /api/articles?username=…&per_page=100&page=N   public, paginated, no key
    Substack   /api/v1/archive?limit=50&offset=N              public, paginated, no key
    Medium     archive page 403, publication sitemap 403      no route that is not a fight
    YouTube    RSS caps at 15; uploads playlist also 15       needs the Data API and a key

Medium's *global* sitemap does return 200, but it is date-partitioned across all of Medium
(`sitemap/posts/2015/posts-2015-05-06.xml`), so locating one author's posts means walking
the entire index. That is not a back-catalogue route, it is a crawl.

── ★ Publication dates are mandatory, not cosmetic ────────────────────────────────────
``upsert_drop_point`` leaves ``date_dropped`` NULL rather than defaulting to now, and its
own comment explains why: echo detection rejects search results that predate the drop
point, so an ingestion-time stamp on a 2025 article makes essentially the whole web look
like prior art and detection silently finds nothing forever.

A backfill is exactly where that goes wrong, because every row is old. Both APIs supply a
real date (``published_at`` / ``post_date``) and this script refuses to ingest a record
without one — a NULL is recoverable, a wrong "today" is not.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

# Both hosts rate-limit, and both answer a burst with 403 rather than 429 — observed on
# 2026-09-06 while probing, from the same IP that had just succeeded. Pacing is therefore
# not politeness, it is the difference between a complete backfill and a truncated one that
# looks complete.
REQUEST_DELAY_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "AINDY-RippleTrace/1.0 (+archive-backfill)"


@dataclass
class ArchiveEntry:
    url: str
    title: str
    summary: str
    published_at: datetime
    tags: list[str]


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.load(response)


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


# ── platform adapters ──────────────────────────────────────────────────────────────────
# Each yields ArchiveEntry and owns only its pagination shape. Deliberately small: a
# platform adapter is a thing that rots, so the less of the pipeline it touches the better.

def devto_entries(username: str) -> Iterator[ArchiveEntry]:
    page = 1
    while True:
        batch = _get_json(
            f"https://dev.to/api/articles?username={username}&per_page=100&page={page}"
        )
        if not batch:
            return
        for item in batch:
            # `published_at` is the article's own date; `published_timestamp` moves when a
            # post is edited, so it is the wrong one for "when did this enter the world".
            published = _parse_date(item.get("published_at"))
            if published is None:
                continue
            yield ArchiveEntry(
                url=item.get("url") or "",
                title=item.get("title") or "",
                summary=item.get("description") or "",
                published_at=published,
                tags=list(item.get("tag_list") or []),
            )
        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)


def substack_entries(publication: str) -> Iterator[ArchiveEntry]:
    offset = 0
    while True:
        batch = _get_json(
            f"https://{publication}.substack.com/api/v1/archive"
            f"?sort=new&limit=50&offset={offset}"
        )
        if not batch:
            return
        for item in batch:
            published = _parse_date(item.get("post_date"))
            if published is None:
                continue
            yield ArchiveEntry(
                url=item.get("canonical_url") or "",
                title=item.get("title") or "",
                summary=item.get("subtitle") or item.get("description") or "",
                published_at=published,
                tags=[],
            )
        offset += 50
        time.sleep(REQUEST_DELAY_SECONDS)


ADAPTERS: dict[str, Callable[[str], Iterator[ArchiveEntry]]] = {
    "devto": devto_entries,
    "substack": substack_entries,
}


def _collect(platform: str, handle: str) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    try:
        for entry in ADAPTERS[platform](handle):
            if entry.url and entry.title:
                entries.append(entry)
    except urllib.error.HTTPError as exc:
        # Partial is reported, not discarded: a 403 partway through means rate limiting,
        # and the rows already collected are real. Re-running is safe (upsert), so the
        # useful behaviour is to write what we have and say where it stopped.
        print(f"  ! {platform}: stopped after {len(entries)} at HTTP {exc.code}", file=sys.stderr)
    return entries


def main() -> int:
    # NOT `description=__doc__`: the module docstring contains box-drawing characters, and
    # argparse prints the description on `--help`, which raises UnicodeEncodeError on a
    # Windows cp1252 console. The docstring stays rich for readers; --help stays ASCII.
    parser = argparse.ArgumentParser(
        description="Backfill a published back-catalogue into rippletrace drop points."
    )
    parser.add_argument("--user-id", required=True, help="owning user's UUID")
    parser.add_argument("--devto", help="dev.to username")
    parser.add_argument("--substack", help="substack publication subdomain")
    parser.add_argument(
        "--apply", action="store_true",
        help="write to the database; without it the script only reports",
    )
    args = parser.parse_args()

    targets = [(name, handle) for name, handle in
               (("devto", args.devto), ("substack", args.substack)) if handle]
    if not targets:
        parser.error("give at least one of --devto / --substack")

    collected: list[ArchiveEntry] = []
    for platform, handle in targets:
        print(f"fetching {platform}:{handle} ...")
        entries = _collect(platform, handle)
        print(f"  {len(entries)} entries with a usable publication date")
        collected.extend(entries)

    if not collected:
        print("nothing to ingest")
        return 0

    oldest = min(e.published_at for e in collected)
    newest = max(e.published_at for e in collected)
    print(f"\n{len(collected)} entries, {oldest.date()} to {newest.date()}")

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply to ingest.")
        for entry in collected[:5]:
            print(f"  {entry.published_at.date()}  {entry.title[:64]}")
        if len(collected) > 5:
            print(f"  ... and {len(collected) - 5} more")
        return 0

    # Imported here so a dry run needs no database and no app bootstrap.
    #
    # The bootstrap is not optional despite only one app's table being written:
    # `drop_points.user_id` carries a foreign key to `users`, which is registered by a
    # different app. Importing the rippletrace model alone leaves that table absent from
    # `Base.metadata` and SQLAlchemy raises `NoReferencedTableError` when it resolves the
    # FK -- a failure that reads as a broken model rather than an incomplete registry.
    import apps.bootstrap

    apps.bootstrap.bootstrap()

    from AINDY.db.database import SessionLocal
    from apps.rippletrace.services.content_ingest import upsert_drop_point

    db = SessionLocal()
    created = updated = 0
    try:
        for entry in collected:
            _row, was_created = upsert_drop_point(
                db,
                user_id=args.user_id,
                url=entry.url,
                title=entry.title,
                summary=entry.summary,
                tags=entry.tags,
                published_at=entry.published_at,
            )
            if was_created:
                created += 1
            else:
                updated += 1
        db.commit()
    finally:
        db.close()

    print(f"\ncreated {created}, updated {updated}")
    print(
        "Detection orders by mentions_checked_at ASC NULLS FIRST, so these join the front "
        "of the queue at 10 per 6-hour sweep."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
