"""Reading directing time: `DIRECTING_TIME_SPEC.md` §2 (sessions), §4 (the routes), decision 4 (the Collaborator).

**A directing session is derived when read, never stored.** Each prompt covers `[occurred_at, end]`, where `end` is the
agent's last line on it (`agent_until`) capped at T after the prompt (decision 2). A prompt joins the current session
when it comes within T of the session's end so far (decision 1, T = 20 min), which is the prompt-to-prompt gap when the
agent answers quickly, and the person's own idle gap when it worked for a while: they were on call until it finished.

**Two sources:** Claude Code prompts (`directing_events`, phases A–B) and the Collaborator: each agent run the person
started is a prompt at `created_at`, its work ending at `completed_at` (decision 4). Agent-spawned runs are not the
person's and are left out. Genesis has no per-message times, so it is not a source.

**The `directing_minutes` shadow (decision 5) is this module's arithmetic, not a stored column.** Every input is kept
(events, agent runs), so the value beside any past `focus_quality` row in `score_history` can be computed for that
date at any time, backfilled prompts included. Nothing in the score reads it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

GAP = timedelta(minutes=20)  # T, decision 1
MAX_RANGE_DAYS = 92
COLLABORATOR = "collaborator"


@dataclass(frozen=True)
class Prompt:
    at: datetime
    until: Optional[datetime]
    project: str
    source: str


@dataclass
class DirectingSession:
    start: datetime
    end: datetime
    prompts: int = 0
    projects: set = field(default_factory=set)
    sources: set = field(default_factory=set)

    @property
    def minutes(self) -> float:
        return round((self.end - self.start).total_seconds() / 60, 1)

    def as_dict(self) -> dict:
        return {
            "start": self.start.isoformat(), "end": self.end.isoformat(), "minutes": self.minutes,
            "prompts": self.prompts, "projects": sorted(self.projects), "sources": sorted(self.sources),
        }


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def prompt_end(prompt: Prompt, gap: timedelta = GAP) -> datetime:
    """The end of the agent's work on one prompt, capped at T (decision 2)."""
    if prompt.until is None or prompt.until <= prompt.at:
        return prompt.at
    return min(prompt.until, prompt.at + gap)


def derive_sessions(prompts: Iterable[Prompt], gap: timedelta = GAP) -> list[DirectingSession]:
    sessions: list[DirectingSession] = []
    current: Optional[DirectingSession] = None
    for prompt in sorted(prompts, key=lambda p: p.at):
        end = prompt_end(prompt, gap)
        if current is None or prompt.at - current.end > gap:
            current = DirectingSession(start=prompt.at, end=end)
            sessions.append(current)
        current.end = max(current.end, end)
        current.prompts += 1
        current.projects.add(prompt.project)
        current.sources.add(prompt.source)
    return sessions


def load_prompts(db: Session, user_id: str, start: datetime, end: datetime) -> list[Prompt]:
    """Both sources' prompts for one user with `start <= at < end`."""
    from AINDY.db.models import AgentRun

    from apps.automation.directing import DirectingEvent

    owner = uuid.UUID(str(user_id))
    prompts = [
        Prompt(at=_utc(row.occurred_at), until=_utc(row.agent_until), project=row.project or "", source=row.source)
        for row in (
            db.query(DirectingEvent)
            .filter(DirectingEvent.user_id == owner, DirectingEvent.occurred_at >= start,
                    DirectingEvent.occurred_at < end)
            .all()
        )
    ]
    prompts.extend(
        Prompt(at=_utc(run.created_at), until=_utc(run.completed_at), project=COLLABORATOR, source=COLLABORATOR)
        for run in (
            db.query(AgentRun)
            .filter(AgentRun.user_id == owner, AgentRun.parent_run_id.is_(None),
                    AgentRun.spawned_by_agent_id.is_(None), AgentRun.created_at >= start, AgentRun.created_at < end)
            .all()
        )
        if run.created_at is not None
    )
    return prompts


def sessions_between(db: Session, user_id: str, start: datetime, end: datetime) -> list[DirectingSession]:
    """Sessions that start in `[start, end)`. Reads T before `start` so a session already running is not cut."""
    prompts = load_prompts(db, user_id, start - GAP * 3, end)
    return [s for s in derive_sessions(prompts) if start <= s.start < end]


def resolve_zone(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown time zone {name!r}")


def watcher_minutes_by_day(db: Session, user_id: str, start: datetime, end: datetime, zone: ZoneInfo) -> dict:
    """The watcher's tracked minutes per local day: `session_ended` durations, by when the session ended."""
    from apps.automation.models import WatcherSignal

    totals: dict[date, float] = {}
    for stamp, seconds in (
        db.query(WatcherSignal.signal_timestamp, WatcherSignal.duration_seconds)
        .filter(WatcherSignal.user_id == uuid.UUID(str(user_id)), WatcherSignal.signal_type == "session_ended",
                WatcherSignal.signal_timestamp >= start, WatcherSignal.signal_timestamp < end)
        .all()
    ):
        day = _utc(stamp).astimezone(zone).date()
        totals[day] = totals.get(day, 0.0) + float(seconds or 0) / 60
    return totals


def summary(db: Session, user_id: str, days: int, zone: ZoneInfo, now: Optional[datetime] = None) -> dict:
    """Directing minutes per local day beside the watcher's tracked minutes (§4): phase D's comparison."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(zone).date()
    first = today - timedelta(days=days - 1)
    start = datetime.combine(first, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)

    sessions = sessions_between(db, user_id, start, end)
    watcher = watcher_minutes_by_day(db, user_id, start, end, zone)
    rows = {first + timedelta(days=n): {"directing_minutes": 0.0, "sessions": 0, "prompts": 0}
            for n in range(days)}
    for session in sessions:
        row = rows.get(session.start.astimezone(zone).date())
        if row is not None:
            row["directing_minutes"] += session.minutes
            row["sessions"] += 1
            row["prompts"] += session.prompts
    daily = [
        {"date": day.isoformat(), "directing_minutes": round(row["directing_minutes"], 1), "sessions": row["sessions"],
         "prompts": row["prompts"], "watcher_minutes": round(watcher.get(day, 0.0), 1)}
        for day, row in sorted(rows.items())
    ]
    return {
        "days": days,
        "time_zone": zone.key,
        "daily": daily,
        "totals": {
            "directing_minutes": round(sum(d["directing_minutes"] for d in daily), 1),
            "sessions": sum(d["sessions"] for d in daily),
            "prompts": sum(d["prompts"] for d in daily),
            "watcher_minutes": round(sum(d["watcher_minutes"] for d in daily), 1),
        },
        "gap_minutes": int(GAP.total_seconds() // 60),
        "in_score": False,
    }
