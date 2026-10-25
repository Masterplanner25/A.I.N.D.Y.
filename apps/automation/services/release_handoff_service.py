"""Release handoff — `RELEASE_HANDOFF_SPEC.md`, phase 1: follow and notify.

The owner prepares a release up to the tag, then hands it off. From there A.I.N.D.Y. follows the tag's
`publish.yml` run, tells the owner when it reaches the approval gate, follows it through PyPI, the wheel
check and the GitHub Release, and records the outcome where the algorithm sees it (§5): a completed
task, a memory note, `release.<stage>` events, and the next task (the adoption).

No model is involved. Every stage is a fact read from GitHub each minute (`release_handoff_watch`),
so a missed tick or a restart loses nothing: the next tick reads the same truth. The owner approves on
GitHub or, with `AINDY_GITHUB_APPROVE_TOKEN` set, from the Collaborator card (§7.3, phase 3); either way
the stage moves only when the next tick reads GitHub's own facts.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from AINDY.platform_layer.user_ids import parse_user_id
from apps.automation.release_handoff import RELEASE_STAGES, RELEASE_TERMINAL, ReleaseHandoff
from apps.automation.services.github_actions import (
    APPROVE_TOKEN_ENV,
    TOKEN_ENV,
    GitHubActions,
    GitHubUnavailable,
    approve_token,
)
from apps.automation.services.github_actions import token as github_token
from apps.automation.services.release_reply import SentMailbox, email_reply_enabled, reply_code

logger = logging.getLogger(__name__)

TICK_INTERVAL_MINUTES = 1
#: Decision 4: the one repository with a gate. `AINDY_RELEASE_REPOS` (comma-separated) widens it.
DEFAULT_REPOS = ("Masterplanner25/aindy-runtime",)
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?$")
GATE_ENVIRONMENT = "production"
#: The `publish.yml` jobs the stages are read from, by the start of their display names (§1).
JOBS = {
    "testpypi": "Publish to TestPyPI",
    "pypi": "Publish to PyPI",
    "wheel": "Boot the published wheel",
    "release": "Create GitHub Release",
}
FAILED_CONCLUSIONS = ("failure", "timed_out", "cancelled", "startup_failure", "action_required")
NOTIFY_STAGES = ("at_gate", "done", "failed")
#: Where a decision made through A.I.N.D.Y. came from: the Collaborator card, or (phase 3b) an email reply.
DECISION_CHANNELS = ("collaborator", "email")
DECISION_STATES = ("approved", "rejected")

_tick_lock = threading.Lock()


def allowed_repos() -> tuple[str, ...]:
    raw = os.getenv("AINDY_RELEASE_REPOS") or ""
    repos = tuple(r.strip() for r in raw.split(",") if r.strip())
    return repos or DEFAULT_REPOS


def _minutes_setting(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name) or default))
    except ValueError:
        return default


def no_run_minutes() -> int:
    return _minutes_setting("AINDY_RELEASE_NO_RUN_MINUTES", 30)


def stall_minutes() -> int:
    return _minutes_setting("AINDY_RELEASE_STALL_MINUTES", 180)


def _uid(user_id: Any):
    uid = parse_user_id(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="user_id is required")
    return uid


def _refuse(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": "release_refused", "message": message})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = int(round(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min {secs} s" if minutes else f"{secs} s"


def project_name(repo: str) -> str:
    return repo.rsplit("/", 1)[-1]


# ── Reading GitHub: a run, its jobs, its gate and its approvals become stages ────────────────


def _job(jobs: list[dict], role: str) -> dict | None:
    prefix = JOBS[role]
    return next((j for j in jobs if str(j.get("name") or "").startswith(prefix)), None)


def _gate_decision(approvals: list[dict]) -> dict | None:
    for approval in approvals:
        if GATE_ENVIRONMENT in {e.get("name") for e in approval.get("environments") or []}:
            return approval
    return None


def observe(run: dict | None, jobs: list[dict], pending: list[dict], approvals: list[dict]) -> dict:
    """What GitHub says, as stages. Pure: the same responses always give the same answer.

    Returns `{events: [(stage, at, detail)], failure, approved_by, approved_at, gate_wait_seconds}`;
    `events` is in §3's order and holds every stage the run has reached, not only new ones.
    """
    out: dict[str, Any] = {"events": [], "failure": None, "approved_by": None, "approved_at": None,
                           "gate_wait_seconds": None}
    if not run:
        return out
    events = out["events"]
    events.append(("running", _ts(run.get("run_started_at") or run.get("created_at")),
                   {"run_id": str(run.get("id")), "url": run.get("html_url")}))

    testpypi, pypi, wheel, release = (_job(jobs, role) for role in ("testpypi", "pypi", "wheel", "release"))
    gate_open = any((d.get("environment") or {}).get("name") == GATE_ENVIRONMENT for d in pending)
    pypi_started = bool(pypi and pypi.get("status") in ("in_progress", "completed") and pypi.get("started_at"))
    decision = _gate_decision(approvals)

    gate_at = None
    if gate_open or pypi_started or (decision and decision.get("state") == "rejected"):
        gate_at = _ts((testpypi or {}).get("completed_at"))
        events.append(("at_gate", gate_at, {"environment": GATE_ENVIRONMENT}))

    if decision and decision.get("state") == "rejected":
        out["failure"] = {"reason": "rejected", "job": JOBS["pypi"], "conclusion": "rejected",
                          "by": (decision.get("user") or {}).get("login"), "url": run.get("html_url")}
        return out

    if pypi_started and not gate_open:
        approved_at = _ts(pypi.get("started_at"))
        by = (decision or {}).get("user", {}).get("login") if decision else None
        out["approved_by"], out["approved_at"] = by, approved_at
        if gate_at and approved_at:
            out["gate_wait_seconds"] = (approved_at - gate_at).total_seconds()
        events.append(("approved", approved_at, {"by": by}))

    if pypi and pypi.get("conclusion") == "success":
        events.append(("published", _ts(pypi.get("completed_at")), {"job": pypi.get("name")}))

    finished = [j for j in (wheel, release) if j and j.get("conclusion") == "success"]
    run_succeeded = run.get("status") == "completed" and run.get("conclusion") == "success"
    if len(finished) == 2 or run_succeeded:
        ends = [_ts(j.get("completed_at")) for j in finished] or [_ts(run.get("updated_at"))]
        events.append(("done", max(t for t in ends if t) if any(ends) else None,
                       {"jobs": [j.get("name") for j in finished]}))
        return out

    if run.get("conclusion") == "cancelled":
        out["failure"] = {"reason": "cancelled", "job": None, "conclusion": "cancelled", "url": run.get("html_url")}
        return out
    for job in jobs:
        if job.get("conclusion") in FAILED_CONCLUSIONS:
            out["failure"] = {"reason": "job_failed", "job": job.get("name"), "conclusion": job.get("conclusion"),
                              "url": job.get("html_url") or run.get("html_url")}
            return out
    if run.get("status") == "completed" and run.get("conclusion") not in (None, "success"):
        out["failure"] = {"reason": f"run_{run.get('conclusion')}", "job": None,
                          "conclusion": run.get("conclusion"), "url": run.get("html_url")}
    return out


# ── The record ─────────────────────────────────────────────────────────────────────────────


def _enter(handoff: ReleaseHandoff, stage: str, at: datetime | None, detail: dict | None) -> None:
    at = _aware(at) or _now()
    handoff.stage = stage
    handoff.stage_at = at
    handoff.history = [*(handoff.history or []), {"stage": stage, "at": _iso(at), "detail": detail or {}}]
    if stage in RELEASE_TERMINAL:
        handoff.finished_at = _now()


def _stage_time(handoff: ReleaseHandoff, stage: str) -> datetime | None:
    for entry in handoff.history or []:
        if entry.get("stage") == stage:
            return _ts(entry.get("at"))
    return None


def decision(handoff: ReleaseHandoff) -> dict | None:
    """The decision A.I.N.D.Y. sent to GitHub for this handoff, if it sent one (§7.3)."""
    return next((e for e in handoff.history or [] if e.get("stage") == "decision"), None)


def gate_wait_seconds(handoff: ReleaseHandoff) -> float | None:
    gate, approved = _stage_time(handoff, "at_gate"), _stage_time(handoff, "approved")
    return (approved - gate).total_seconds() if gate and approved else None


def serialize(handoff: ReleaseHandoff) -> dict:
    return {
        "id": handoff.id,
        "repo": handoff.repo,
        "tag": handoff.tag,
        "version": handoff.version,
        "run_id": handoff.run_id,
        "run_url": handoff.run_url,
        "stage": handoff.stage,
        "stage_at": _iso(handoff.stage_at),
        "history": list(handoff.history or []),
        "approved_by": handoff.approved_by,
        "approved_at": _iso(handoff.approved_at),
        "gate_wait_seconds": gate_wait_seconds(handoff),
        "decision": decision(handoff),
        # The card shows Approve and Reject only when this is true.
        "can_decide": handoff.stage == "at_gate" and bool(approve_token()) and decision(handoff) is None,
        "failure": handoff.failure,
        "notified": handoff.notified or {},
        "task_id": handoff.task_id,
        "task_name": handoff.task_name,
        "adoption_task_id": handoff.adoption_task_id,
        "memory_node_id": handoff.memory_node_id,
        "created_at": _iso(handoff.created_at),
        "finished_at": _iso(handoff.finished_at),
    }


# ── The algorithm's records: tasks and a memory note, through the owners' syscalls ──────────


def _dispatch(db: Session, user_id: Any, name: str, payload: dict, capability: str) -> dict:
    from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

    ctx = SyscallContext(execution_unit_id=str(uuid.uuid4()), user_id=str(user_id),
                         capabilities=[capability], trace_id="", metadata={"_db": db})
    result = get_dispatcher().dispatch(name, payload, ctx)
    if result.get("status") != "success":
        raise RuntimeError(result.get("error") or f"{name} failed")
    return result.get("data") or {}


def release_task_name(repo: str, version: str) -> str:
    return f"Release {project_name(repo)} {version}"


def adoption_task_name(repo: str, version: str) -> str:
    return f"Adopt {project_name(repo)} {version} in A.I.N.D.Y."


def handoff_doc(version: str) -> str:
    return f"docs/upgrades/APP_HANDOFF_v{version}.md"


def _open_release_task(db: Session, handoff: ReleaseHandoff) -> None:
    """The task the release completes (§5). A re-handoff of a tag that failed reuses its open task."""
    previous = (db.query(ReleaseHandoff)
                .filter(ReleaseHandoff.user_id == handoff.user_id, ReleaseHandoff.repo == handoff.repo,
                        ReleaseHandoff.tag == handoff.tag, ReleaseHandoff.task_name.isnot(None),
                        ReleaseHandoff.id != handoff.id)
                .order_by(ReleaseHandoff.created_at.desc()).first())
    name = release_task_name(handoff.repo, handoff.version)
    if previous is not None:
        handoff.task_id, handoff.task_name = previous.task_id, previous.task_name
    else:
        created = _dispatch(db, handoff.user_id, "sys.v1.task.create",
                            {"name": name, "category": "release", "priority": "high"}, "task.create")
        handoff.task_id, handoff.task_name = created.get("task_id"), created.get("task_name") or name
    # Started now, so `time_spent` at completion is the handoff to done, in seconds.
    _dispatch(db, handoff.user_id, "sys.v1.task.start", {"task_name": handoff.task_name}, "task.start")


def outcome_note(handoff: ReleaseHandoff) -> str:
    project = project_name(handoff.repo)
    lines = [f"{project} {handoff.version} was released through a release handoff."]
    times = {stage: _stage_time(handoff, stage) for stage in RELEASE_STAGES}
    if times["at_gate"] and times["running"]:
        lines.append(f"The run reached the approval gate {_duration((times['at_gate'] - times['running']).total_seconds())} "
                     "after it started.")
    wait = gate_wait_seconds(handoff)
    if handoff.approved_by or wait is not None:
        made = decision(handoff)
        via = (f", approved from A.I.N.D.Y. by {'email' if made.get('via') == 'email' else 'the Collaborator card'}"
               if made and made.get("state") == "approved" else "")
        lines.append(f"Approved by {handoff.approved_by or 'unknown'} after waiting {_duration(wait)} at the gate{via}.")
    if times["published"]:
        lines.append(f"Published to PyPI at {_iso(times['published'])}.")
    if times["done"]:
        lines.append(f"Wheel verified and GitHub Release created at {_iso(times['done'])}.")
    created = _aware(handoff.created_at)
    # Only when the handoff came first: a run handed off after it finished has no handoff-to-done time.
    if created and times["done"] and times["done"] > created:
        lines.append(f"Handoff to done: {_duration((times['done'] - created).total_seconds())}.")
    if handoff.run_url:
        lines.append(f"Run: {handoff.run_url}")
    lines.append(f"Next: adopt it in A.I.N.D.Y. ({handoff_doc(handoff.version)} in {handoff.repo}).")
    return "\n".join(lines)


def record_outcome(db: Session, handoff: ReleaseHandoff) -> None:
    """§5 at `done`: the release task completes, a memory note of the outcome, the adoption task.

    Each record is independent: one failing is logged and the others are still written.
    """
    if handoff.task_name:
        try:
            _dispatch(db, handoff.user_id, "sys.v1.task.complete_full", {"task_name": handoff.task_name},
                      "task.complete_full")
        except Exception as exc:
            logger.warning("[release] completing %s failed: %s", handoff.task_name, exc)
    if not handoff.memory_node_id:
        try:
            data = _dispatch(db, handoff.user_id, "sys.v1.memory.write", {
                "content": outcome_note(handoff),
                "tags": ["release", f"release:{project_name(handoff.repo)}", f"release:{handoff.version}"],
                "node_type": "outcome",
                "source": "release_handoff",
            }, "memory.write")
            node = data.get("node") if isinstance(data, dict) else None
            handoff.memory_node_id = str(node.get("id")) if isinstance(node, dict) and node.get("id") else None
        except Exception as exc:
            logger.warning("[release] memory note for %s failed: %s", handoff.tag, exc)
    if not handoff.adoption_task_id:
        try:
            created = _dispatch(db, handoff.user_id, "sys.v1.task.create", {
                "name": adoption_task_name(handoff.repo, handoff.version), "category": "release", "priority": "high",
            }, "task.create")
            handoff.adoption_task_id = created.get("task_id")
        except Exception as exc:
            logger.warning("[release] adoption task for %s failed: %s", handoff.tag, exc)


def _emit(db: Session, handoff: ReleaseHandoff, stage: str) -> None:
    from AINDY.core.system_event_service import emit_system_event

    emit_system_event(db=db, event_type=f"release.{stage}", user_id=handoff.user_id, source="release_handoff",
                      payload={"handoff_id": handoff.id, "repo": handoff.repo, "tag": handoff.tag,
                               "version": handoff.version, "run_id": handoff.run_id, "stage": stage,
                               "failure": handoff.failure if stage == "failed" else None})


# ── Notifications (§6): email, once per stage ─────────────────────────────────────────────


def _recipient(db: Session, handoff: ReleaseHandoff) -> str | None:
    override = (os.getenv("AINDY_RELEASE_NOTIFY_TO") or "").strip()
    if override:
        return override
    from AINDY.db.models.user import User

    user = db.query(User).filter(User.id == handoff.user_id).first()
    return getattr(user, "email", None)


def message(handoff: ReleaseHandoff, stage: str) -> tuple[str, str]:
    project = f"{project_name(handoff.repo)} {handoff.version}"
    link = handoff.run_url or f"https://github.com/{handoff.repo}/actions"
    if stage == "at_gate":
        started, gate = _stage_time(handoff, "running"), _stage_time(handoff, "at_gate")
        reached = f" ({_duration((gate - started).total_seconds())} after the run started)" if started and gate else ""
        # Phase 3b: the code in the subject is what binds a reply to this handoff (`release_reply`).
        replies = email_reply_enabled()
        return ((f"[{reply_code(handoff.id)}] " if replies else "") + f"{project} is waiting for your approval",
                f"{project} reached the approval gate at {_iso(gate) or 'just now'}{reached}.\n\n"
                + ("To decide it from here, reply to this email with APPROVE or REJECT as the first word.\n"
                   if replies else "")
                + f"Approve or reject it on GitHub: {link}\n"
                + ("Or decide it on A.I.N.D.Y.'s Collaborator card.\n" if approve_token() else "") + "\n"
                "A.I.N.D.Y. sees the decision within a minute and follows the release to the end.")
    if stage == "done":
        return (f"{project} is published",
                f"{outcome_note(handoff)}\n\nThe task \"{adoption_task_name(handoff.repo, handoff.version)}\" "
                "is waiting for you.")
    failure = handoff.failure or {}
    what = {"no_run": "no publish run was found for the tag",
            "stalled": "the run has not moved for a long time",
            "rejected": f"the approval gate was rejected{' by ' + failure['by'] if failure.get('by') else ''}",
            "cancelled": "the run was cancelled"}.get(failure.get("reason"))
    if what is None:
        job = failure.get("job") or "the run"
        what = f"{job} ended {failure.get('conclusion') or 'unsuccessfully'}"
    return (f"{project} release stopped: {what}",
            f"The release handoff for {project} stopped: {what}.\n\n"
            f"Details: {failure.get('url') or link}\n\n"
            "Nothing retries on its own. The release task stays open; hand the tag off again once it is fixed.")


def notify(db: Session, handoff: ReleaseHandoff, stage: str,
           send: Callable[..., dict] | None = None) -> dict | None:
    if stage not in NOTIFY_STAGES or stage in (handoff.notified or {}):
        return None
    if send is None:
        from AINDY.platform_layer.email_channel import send_email as send
    to = _recipient(db, handoff)
    subject, body = message(handoff, stage)
    if to:
        result = send(to=to, subject=subject, body=body, db=db, user_id=str(handoff.user_id))
    else:
        result = {"success": False, "route": None, "error": "no recipient: the user has no email"}
    entry = {"success": bool(result.get("success")), "route": result.get("route"), "error": result.get("error"),
             "at": _iso(_now()), "subject": subject}
    # Recorded either way: one notification per stage, a failed send is not retried every minute.
    handoff.notified = {**(handoff.notified or {}), stage: entry}
    if not entry["success"]:
        logger.warning("[release] %s notification for %s not delivered: %s", stage, handoff.tag, entry["error"])
    return entry


# ── Handoff, list, and the watcher ─────────────────────────────────────────────────────────


def start_handoff(db: Session, user_id: Any, repo: str, tag: str) -> dict:
    uid = _uid(user_id)
    repo, tag = (repo or "").strip(), (tag or "").strip()
    if repo not in allowed_repos():
        raise _refuse(422, f"repo must be one of: {', '.join(allowed_repos())}")
    if not TAG_RE.match(tag):
        raise _refuse(422, "tag must look like v2.28.0")
    if not github_token():
        # Refused here rather than accepted and left at `requested`: without a token no tick can read the run.
        raise _refuse(503, f"{TOKEN_ENV} is not set, so A.I.N.D.Y. cannot follow the run")
    active = (db.query(ReleaseHandoff)
              .filter(ReleaseHandoff.user_id == uid, ReleaseHandoff.repo == repo, ReleaseHandoff.tag == tag,
                      ReleaseHandoff.stage.notin_(RELEASE_TERMINAL)).first())
    if active is not None:
        raise _refuse(409, f"{tag} is already handed off and at {active.stage}")
    released = (db.query(ReleaseHandoff)
                .filter(ReleaseHandoff.user_id == uid, ReleaseHandoff.repo == repo, ReleaseHandoff.tag == tag,
                        ReleaseHandoff.stage == "done").first())
    if released is not None:
        # Found live 2026-10-15: a second handoff of a released tag wrote a second adoption task.
        raise _refuse(409, f"{tag} is already released; its adoption task is waiting")
    handoff = ReleaseHandoff(user_id=uid, repo=repo, tag=tag, version=tag[1:], stage="requested",
                             stage_at=_now(), history=[], notified={})
    _enter(handoff, "requested", handoff.stage_at, {"by": "owner"})
    db.add(handoff)
    db.flush()
    try:
        _open_release_task(db, handoff)
    except Exception as exc:  # the handoff stands without its task; the outcome note still records it
        logger.warning("[release] release task for %s not created: %s", tag, exc)
    db.commit()
    db.refresh(handoff)
    try:
        _emit(db, handoff, "requested")
    except Exception as exc:
        logger.warning("[release] release.requested event failed: %s", exc)
    return serialize(handoff)


def decide(db: Session, user_id: Any, handoff_id: str, state: str, *, via: str = "collaborator",
           comment: str | None = None, github: GitHubActions | None = None) -> dict:
    """Approve or reject the gate as the owner (§7.3). GitHub records the decision: this sends it once
    and writes one history entry, and the stage moves only when the next tick reads it back.

    Refused, with nothing sent: 404 for another user's handoff, 503 without the approve token, 409 when
    the handoff is not at the gate, was already decided here, or GitHub no longer has `production`
    pending (decided on GitHub, or two decisions raced).
    """
    uid = _uid(user_id)
    if state not in DECISION_STATES:
        raise _refuse(422, f"state must be one of: {', '.join(DECISION_STATES)}")
    if via not in DECISION_CHANNELS:
        raise _refuse(422, f"via must be one of: {', '.join(DECISION_CHANNELS)}")
    handoff = (db.query(ReleaseHandoff)
               .filter(ReleaseHandoff.id == str(handoff_id), ReleaseHandoff.user_id == uid).first())
    if handoff is None:
        raise _refuse(404, "no such handoff")
    if not approve_token():
        raise _refuse(503, f"{APPROVE_TOKEN_ENV} is not set, so A.I.N.D.Y. cannot decide the gate")
    if handoff.stage != "at_gate" or not handoff.run_id:
        raise _refuse(409, f"{handoff.tag} is not waiting at the gate (it is at {handoff.stage})")
    if decision(handoff) is not None:
        raise _refuse(409, f"{handoff.tag} was already decided from A.I.N.D.Y.")
    github = github or GitHubActions(db=db, user_id=uid)
    try:
        # Re-read right before the POST: the owner may have clicked on GitHub since the last tick.
        pending = github.pending_deployments(handoff.repo, handoff.run_id)
    except GitHubUnavailable as exc:
        raise _refuse(502, str(exc)) from exc
    gate = [(d.get("environment") or {}).get("id") for d in pending
            if (d.get("environment") or {}).get("name") == GATE_ENVIRONMENT]
    if not gate or gate[0] is None:
        raise _refuse(409, "GitHub says the gate was already decided")
    note = f"{'Approved' if state == 'approved' else 'Rejected'} from A.I.N.D.Y. ({via})"
    if comment and comment.strip():
        note = f"{note}: {comment.strip()[:500]}"
    try:
        github.review(handoff.repo, handoff.run_id, gate[:1], state, note)
    except GitHubUnavailable as exc:
        raise _refuse(502, str(exc)) from exc
    handoff.history = [*(handoff.history or []),
                       {"stage": "decision", "state": state, "via": via, "at": _iso(_now())}]
    db.commit()
    db.refresh(handoff)
    return serialize(handoff)


def list_handoffs(db: Session, user_id: Any, *, active_only: bool = False, limit: int = 10) -> dict:
    uid = _uid(user_id)
    query = db.query(ReleaseHandoff).filter(ReleaseHandoff.user_id == uid)
    if active_only:
        query = query.filter(ReleaseHandoff.stage.notin_(RELEASE_TERMINAL))
    rows = query.order_by(ReleaseHandoff.created_at.desc()).limit(max(1, min(50, int(limit)))).all()
    return {"handoffs": [serialize(r) for r in rows], "repos": list(allowed_repos())}


def advance(db: Session, handoff: ReleaseHandoff, github: GitHubActions, *, now: datetime | None = None) -> list[str]:
    """Move one handoff forward to what GitHub says now. Returns the stages entered (in order).

    Idempotent: stages only move forward, so the same responses read twice change nothing.
    """
    now = now or _now()
    if handoff.stage in RELEASE_TERMINAL:
        return []
    if not handoff.run_id:
        run = github.find_run(handoff.repo, handoff.tag)
        if run is None:
            if now - _aware(handoff.created_at or handoff.stage_at) > timedelta(minutes=no_run_minutes()):
                handoff.failure = {"reason": "no_run", "job": None, "conclusion": None, "url": None}
                _enter(handoff, "failed", now, handoff.failure)
                return ["failed"]
            return []
        handoff.run_id, handoff.run_url = str(run.get("id")), run.get("html_url")
    else:
        run = github.get_run(handoff.repo, handoff.run_id)
    jobs = github.jobs(handoff.repo, handoff.run_id)
    pending = github.pending_deployments(handoff.repo, handoff.run_id)
    approvals = github.approvals(handoff.repo, handoff.run_id)
    seen = observe(run, jobs, pending, approvals)

    entered: list[str] = []
    position = RELEASE_STAGES.index(handoff.stage)
    for stage, at, detail in seen["events"]:
        if RELEASE_STAGES.index(stage) > position:
            _enter(handoff, stage, at, detail)
            entered.append(stage)
            position = RELEASE_STAGES.index(stage)
    if seen["approved_by"] and not handoff.approved_by:
        handoff.approved_by = seen["approved_by"]
    if seen["approved_at"] and not handoff.approved_at:
        handoff.approved_at = seen["approved_at"]
    if handoff.stage == "done":
        return entered
    if seen["failure"]:
        handoff.failure = seen["failure"]
        _enter(handoff, "failed", now, seen["failure"])
        entered.append("failed")
    elif not entered and now - _aware(handoff.stage_at) > timedelta(minutes=stall_minutes()):
        handoff.failure = {"reason": "stalled", "job": None, "conclusion": None, "url": handoff.run_url,
                           "stage": handoff.stage}
        _enter(handoff, "failed", now, handoff.failure)
        entered.append("failed")
    return entered


def process(db: Session, handoff: ReleaseHandoff, github: GitHubActions, *, now: datetime | None = None,
            send: Callable[..., dict] | None = None, mailbox: SentMailbox | None = None) -> list[str]:
    """One handoff, one tick: advance, commit, then the side effects of each stage entered, then (with a
    mailbox) the owner's reply to the gate email, if there is one."""
    entered = advance(db, handoff, github, now=now)
    db.commit()
    for stage in entered:
        try:
            _emit(db, handoff, stage)
        except Exception as exc:
            logger.warning("[release] release.%s event failed: %s", stage, exc)
    if "done" in entered:
        record_outcome(db, handoff)
    # The gate is announced only while the run is still waiting there: a handoff of a run already past
    # it (or one that passed it between two ticks) has nothing to ask of the owner.
    last = entered[-1] if entered else None
    if last in NOTIFY_STAGES:
        notify(db, handoff, last, send=send)
    db.commit()
    if mailbox is not None and handoff.stage == "at_gate":
        from apps.automation.services.release_reply import check_replies

        try:
            check_replies(db, handoff, mailbox, github=github, send=send)
        except Exception as exc:  # the mailbox is a second way to decide; GitHub and the card still work
            db.rollback()
            logger.warning("[release] %s: reading replies failed this tick: %s", handoff.tag, exc)
    return entered


def release_handoff_watch() -> dict:
    """Scheduled job body (every minute): advance each open handoff. Its own session; non-blocking guard."""
    if not _tick_lock.acquire(blocking=False):
        return {"skipped": True}
    from AINDY.db.database import SessionLocal

    db = SessionLocal()
    summary: dict[str, Any] = {"handoffs": 0, "moved": 0, "skipped": False}
    # Connects only if a handoff is at the gate awaiting a reply; one login per tick at most.
    mailbox = SentMailbox() if email_reply_enabled() else None
    try:
        open_rows = (db.query(ReleaseHandoff).filter(ReleaseHandoff.stage.notin_(RELEASE_TERMINAL))
                     .order_by(ReleaseHandoff.created_at.asc()).all())
        for handoff in open_rows:
            summary["handoffs"] += 1
            try:
                entered = process(db, handoff, GitHubActions(db=db, user_id=handoff.user_id), mailbox=mailbox)
                summary["moved"] += len(entered)
            except GitHubUnavailable as exc:
                db.rollback()
                logger.warning("[release] %s: GitHub unavailable this tick: %s", handoff.tag, exc)
            except Exception as exc:
                db.rollback()
                logger.warning("[release] %s: tick failed: %s", handoff.tag, exc)
    finally:
        if mailbox is not None:
            mailbox.close()
        db.close()
        _tick_lock.release()
    return summary
