"""Dev mode (OFF_LAPTOP_DEPLOYMENT_SPEC §5, decision 6; phase D).

A stack that is not the instance (the laptop once the server holds the data, a server during the parallel run) runs
with `docker-compose.dev.yml`: AINDY_ENVIRONMENT=dev, mail to mailpit, no GitHub or ngrok tokens, no durable agent
continuation. The properties here:

- every scheduled job declares its side through `schedule_job(..., outward=...)`; none calls
  `register_scheduled_job` directly, so a new job cannot forget;
- the outward list is pinned: moving a job across is a decision, made here on purpose;
- an outward job skips in dev mode and runs otherwise, and stays importable by its own name;
- the overlay sets what the spec says it sets.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
import yaml

from apps._shared import environment as env

pytestmark = pytest.mark.app_profile

ROOT = Path(__file__).resolve().parents[2]

#: Decision 6, proposed 2026-11-25: spends money, sends mail, calls GitHub, or fetches new data from the web that the
#: instance would then act on (poll -> archive, share drafts, answers).
OUTWARD = {
    "release_handoff_watch": "GitHub reads and approvals, mail",
    "owner_notices_tick": "mail, a provider probe",
    "masterplan_resolution_weekly": "starts a paid Resolution Check",
    "masterplan_resolution_tick": "paid engine and judge calls",
    "rippletrace_poll_content_sources": "fetches the owner's feeds; new pieces feed the jobs below",
    "rippletrace_archive_published_work": "fetches pieces, embeddings",
    "rippletrace_share_drafts": "model calls",
    "rippletrace_piece_answers": "model calls",
    "rippletrace_detect_mentions": "paid search",
}
INWARD = {
    "daily_infinity_score_recalculation", "daily_eta_recalculation", "task_reminder_check", "task_recurrence_check",
    "background_lease_heartbeat", "wait_recovery_poll", "resume_watchdog",
}


def _register_job_calls():
    """Every schedule_job / register_scheduled_job call under apps/, with its job id and outward keyword."""
    calls = []
    for path in (ROOT / "apps").rglob("*.py"):
        if path.name == "environment.py" and path.parent.name == "_shared":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in ("schedule_job", "register_scheduled_job"):
                    job = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
                    outward = next((k.value for k in node.keywords if k.arg == "outward"), None)
                    calls.append((path.relative_to(ROOT).as_posix(), name, job, outward))
    return calls


def test_every_job_declares_its_side_and_none_registers_directly():
    calls = _register_job_calls()
    assert [c for c in calls if c[1] == "register_scheduled_job"] == [], "use apps._shared.environment.schedule_job"
    for path, _, job, outward in calls:
        assert isinstance(outward, ast.Constant) and isinstance(outward.value, bool), (path, job)


def test_the_outward_list_is_the_decided_one():
    sides = {job: outward.value for _, _, job, outward in _register_job_calls()}
    assert {j for j, o in sides.items() if o} == set(OUTWARD)
    assert {j for j, o in sides.items() if not o} == INWARD


def test_registration_refuses_a_side_its_function_contradicts(monkeypatch):
    monkeypatch.setattr("AINDY.platform_layer.registry.register_scheduled_job", lambda *a, **k: None)

    def plain():
        return None

    with pytest.raises(ValueError, match="lacks @outward_job"):
        env.schedule_job("j", plain, outward=True)
    with pytest.raises(ValueError, match="carries @outward_job"):
        env.schedule_job("j", env.outward_job(plain), outward=False)
    env.schedule_job("j", env.outward_job(plain), outward=True)
    assert env.JOB_SIDES["j"] is True


def test_an_outward_job_skips_in_dev_mode_only(monkeypatch):
    ran = []
    job = env.outward_job(lambda: ran.append(1) or {"done": 1})
    monkeypatch.setenv("AINDY_ENVIRONMENT", "dev")
    assert job() == {"skipped": True, "reason": "dev_mode"} and ran == []
    for value in ("", "prod", "development"):
        monkeypatch.setenv("AINDY_ENVIRONMENT", value)
        assert job() == {"done": 1}
    monkeypatch.delenv("AINDY_ENVIRONMENT")
    assert job() == {"done": 1} and ran == [1, 1, 1, 1]


@pytest.mark.parametrize("module, name", [
    ("apps.automation.services.release_handoff_service", "release_handoff_watch"),
    ("apps.automation.services.owner_notices", "owner_notices_tick"),
    ("apps.masterplan.services.resolution_review", "weekly_resolution_checks"),
    ("apps.masterplan.services.resolution_service", "resolution_tick"),
    ("apps.rippletrace.services.content_ingest", "poll_due_sources"),
    ("apps.rippletrace.services.content_archive", "archive_published_work"),
    ("apps.rippletrace.services.share_nodus", "write_share_drafts"),
    ("apps.rippletrace.services.answers_nodus", "write_piece_answers"),
    ("apps.rippletrace.services.ripple_detection", "detect_due_mentions"),
])
def test_each_outward_function_is_guarded_and_importable_by_name(module, name, monkeypatch):
    # The runtime can run a job in a subprocess that imports it by module and name: that must be the guarded one.
    fn = getattr(importlib.import_module(module), name)
    assert env.is_outward(fn) and fn.__name__ == name and fn.__module__ == module
    monkeypatch.setenv("AINDY_ENVIRONMENT", "dev")
    assert fn() == {"skipped": True, "reason": "dev_mode"}


def test_the_dev_overlay_turns_off_what_the_spec_says():
    overlay = yaml.safe_load((ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8"))
    for service in ("api", "mcp"):
        e = overlay["services"][service]["environment"]
        assert e["AINDY_ENVIRONMENT"] == "dev"
        assert (e["AINDY_SMTP_HOST"], e["AINDY_SMTP_PORT"], e["AINDY_SMTP_STARTTLS"]) == ("mailpit", "1025", "false")
        assert e["AINDY_SMTP_PASSWORD"] == "" and e["AINDY_GITHUB_TOKEN"] == "" == e["AINDY_GITHUB_APPROVE_TOKEN"]
        assert e["AINDY_DURABLE_CONTINUATION"] == "false"
    assert overlay["services"]["mcp-tunnel"]["environment"]["NGROK_AUTHTOKEN"] == ""
