"""OFF_LAPTOP_DEPLOYMENT_SPEC phase C: `scripts/deploy_stack.py`, `publish-image.yml`, and compose's AINDY_IMAGE.

The properties: a failed pull changes nothing on the host; the deployed image is written to `.env` (so a later plain
`up` keeps it) without disturbing any other line; counters are read before the recreate; and the workflow publishes
only from main, with the job's own token.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.app_profile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import backup_stack as bs  # noqa: E402
import deploy_stack as ds  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


# ── .env ───────────────────────────────────────────────────────────────────────────────────


def test_set_env_replaces_one_line_and_keeps_the_rest(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(b"SECRET_KEY=abc\r\nAINDY_IMAGE=old:1\r\n# a comment\r\nOPENAI_API_KEY=sk\r\n")
    assert ds.set_env(env, "AINDY_IMAGE", "new:2") == "old:1"
    assert env.read_bytes() == b"SECRET_KEY=abc\r\nAINDY_IMAGE=new:2\r\n# a comment\r\nOPENAI_API_KEY=sk\r\n"


def test_set_env_appends_and_keeps_a_bom(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(b"\xef\xbb\xbfSECRET_KEY=abc\n")
    assert ds.set_env(env, "AINDY_IMAGE", "img:1") is None
    assert env.read_bytes() == b"\xef\xbb\xbfSECRET_KEY=abc\nAINDY_IMAGE=img:1\n"
    assert ds.read_env(env) == {"SECRET_KEY": "abc", "AINDY_IMAGE": "img:1"}


def test_the_api_address_comes_from_the_bind_setting():
    assert ds.api_url({}) == "http://127.0.0.1:8000"
    assert ds.api_url({"AINDY_BIND_ADDR": "100.64.0.5"}) == "http://100.64.0.5:8000"


# ── what is deployed ───────────────────────────────────────────────────────────────────────


def test_a_full_sha_is_taken_as_given_and_a_ref_goes_through_git(monkeypatch):
    assert ds.resolve_sha(SHA) == SHA
    monkeypatch.setattr(ds, "git", lambda *a: SHA if a[-1] == "main^{commit}" else None)
    assert ds.resolve_sha("main") == SHA
    with pytest.raises(bs.StackError, match="cannot resolve"):
        ds.resolve_sha("nope")


def test_counters_keep_only_the_window_lines():
    metrics = ("# HELP aindy_payload_identity_mismatch_total x\n"
               "# TYPE aindy_payload_identity_mismatch_total counter\n"
               'aindy_payload_identity_mismatch_total{transport="mcp"} 0.0\n'
               'aindy_effect_gate_outcomes_total{outcome="reserved"} 43.0\n'
               'aindy_effect_gate_outcomes_created{outcome="reserved"} 1.79e+09\n'
               'aindy_llm_key_source_total{key_source="server",provider="openai"} 193.0\n'
               "http_requests_total 9.0\n")
    assert ds.counters(metrics) == ['aindy_payload_identity_mismatch_total{transport="mcp"} 0.0',
                                    'aindy_effect_gate_outcomes_total{outcome="reserved"} 43.0',
                                    'aindy_llm_key_source_total{key_source="server",provider="openai"} 193.0']


def test_compose_names_both_files_and_every_profile():
    cmd = ds.compose("up", "-d", "--no-build", "api")
    assert cmd[:2] == ["docker", "compose"]
    assert [Path(c).name for c in cmd if c.endswith(".yml")] == list(ds.COMPOSE_FILES)
    assert [cmd[i + 1] for i, c in enumerate(cmd) if c == "--profile"] == ["full", "mail", "public-mcp"]


# ── the order ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A host whose docker calls are recorded; ROOT points at a scratch .env."""
    (tmp_path / ".env").write_text("SECRET_KEY=abc\n", encoding="utf-8")
    monkeypatch.setattr(ds, "ROOT", tmp_path)
    monkeypatch.setattr(ds, "git", lambda *a: SHA)
    monkeypatch.setenv("AINDY_DEPLOY_LOG", str(tmp_path / "deploys.jsonl"))
    calls = []

    def run(cmd, **k):
        calls.append(cmd)
        return type("R", (), {"stdout": b"", "stderr": b"", "returncode": 0})()

    monkeypatch.setattr(bs, "run", run)
    monkeypatch.setattr(bs, "container", lambda s, p=bs.PROJECT, required=True: "cid-" + s)
    monkeypatch.setattr(bs, "image_of", lambda cid: "aindy-apps-monolith-api:latest")
    monkeypatch.setattr(ds, "running_mode", lambda cid: host_mode["mode"])
    monkeypatch.setattr(bs, "backup", lambda *a, **k: calls.append(["backup"]))
    monkeypatch.setattr(ds, "get", lambda url, timeout=10: "aindy_effect_gate_outcomes_total 1.0\n"
                        if url.endswith("/metrics/") else json.dumps({"runtime": {"boot_profile": "default-apps",
                                                                                  "app_plugin_count": 16}}))
    monkeypatch.setattr(ds, "wait_healthy", lambda **k: (calls.append(["wait"]), "cid-api")[1])
    monkeypatch.setattr(ds, "confirm", lambda cid, env, project=bs.PROJECT: {"runtime": "2.41.0", "boot_profile": "default-apps",
                                                                        "app_plugin_count": 16, "heads": {}})
    return tmp_path, calls


host_mode = {"mode": "instance"}


@pytest.fixture(autouse=True)
def _instance_by_default():
    host_mode["mode"] = "instance"


def test_pull_counters_backup_env_recreate_in_that_order(host):
    root, calls = host
    record = ds.deploy(SHA)
    steps = [c[0] if c[0] in ("backup", "wait") else " ".join(c[:3]) for c in calls]
    assert steps[0] == f"docker pull {ds.REPOSITORY}:{SHA}"
    assert steps.index("backup") < next(i for i, s in enumerate(steps) if s.startswith("docker compose"))
    assert steps[-1] == "wait"
    assert ds.read_env(root / ".env")["AINDY_IMAGE"] == f"{ds.REPOSITORY}:{SHA}"
    assert record["counters"] == ["aindy_effect_gate_outcomes_total 1.0"]
    assert record["previous_image"] == "aindy-apps-monolith-api:latest"
    assert json.loads((root / "deploys.jsonl").read_text(encoding="utf-8"))["sha"] == SHA


def test_a_failed_pull_changes_nothing(host, monkeypatch):
    root, calls = host

    def run(cmd, **k):
        calls.append(cmd)
        raise bs.StackError("pulling failed: manifest unknown")

    monkeypatch.setattr(bs, "run", run)
    assert ds.main([SHA]) == 1
    assert len(calls) == 1 and calls[0][:2] == ["docker", "pull"]
    assert "AINDY_IMAGE" not in ds.read_env(root / ".env")


def test_no_backup_skips_only_the_backup(host):
    _, calls = host
    ds.deploy(SHA, backup=False)
    assert ["backup"] not in calls and ["wait"] in calls


# ── compose and the workflow ───────────────────────────────────────────────────────────────


def test_api_and_mcp_run_the_image_named_by_aindy_image():
    services = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))["services"]
    for name in ("api", "mcp"):
        assert services[name]["image"] == "${AINDY_IMAGE:-aindy-apps-monolith-api:latest}", name


def test_the_workflow_publishes_from_main_only_with_its_own_token():
    text = (ROOT / ".github" / "workflows" / "publish-image.yml").read_text(encoding="utf-8")
    flow = yaml.safe_load(text)
    on = flow[True]  # YAML reads the bare key `on` as a boolean
    assert on["push"]["branches"] == ["main"]
    assert flow["permissions"] == {"contents": "read"}
    steps = {s.get("name"): s for s in flow["jobs"]["publish"]["steps"]}
    assert steps["Push"]["if"] == "env.PUSH == 'true'" and steps["Log in to the registry"]["if"] == "env.PUSH == 'true'"
    assert flow["jobs"]["publish"]["env"]["PUSH"] == "${{ github.event_name != 'pull_request' }}"
    assert "secrets." in text and set(__import__("re").findall(r"secrets\.(\w+)", text)) == {"GITHUB_TOKEN"}
    for step in flow["jobs"]["publish"]["steps"]:
        if "uses" in step:
            assert "@" in step["uses"] and len(step["uses"].split("@")[1].split()[0]) == 40, step["uses"]
    assert ds.REPOSITORY.endswith("/aindy-api") and "aindy-api" in text


# ── the mode is kept ───────────────────────────────────────────────────────────────────────


def _up(calls):
    return next(c for c in calls if c[:2] == ["docker", "compose"])


def test_a_dev_stack_is_deployed_in_dev_mode_without_the_tunnel(host):
    _, calls = host
    host_mode["mode"] = "dev"
    record = ds.deploy(SHA)
    up = _up(calls)
    assert any(c.endswith(ds.DEV_FILE) for c in up)
    assert [up[i + 1] for i, c in enumerate(up) if c == "--profile"] == ["full", "mail"]
    assert record["mode"] == "dev"


def test_an_instance_is_deployed_as_the_instance(host):
    _, calls = host
    up = _up(calls) if ds.deploy(SHA) else None
    assert not any(c.endswith(ds.DEV_FILE) for c in up) and "public-mcp" in up


def test_with_no_api_running_the_mode_must_be_said(host, monkeypatch):
    root, calls = host
    monkeypatch.setattr(bs, "container", lambda s, p=bs.PROJECT, required=True: None if s == "api" else "cid-" + s)
    assert ds.main([SHA]) == 1 and calls == []
    assert "AINDY_IMAGE" not in ds.read_env(root / ".env")


def test_dev_mode_refuses_the_public_tunnel(host):
    with pytest.raises(bs.StackError, match="public-mcp"):
        ds.deploy(SHA, mode="dev", profiles=("full", "mail", "public-mcp"))


def test_an_api_that_comes_up_in_the_wrong_mode_fails_the_deploy(host, monkeypatch):
    seen = iter(["dev", "instance"])  # running before; what came up after
    monkeypatch.setattr(ds, "running_mode", lambda cid: next(seen))
    with pytest.raises(bs.StackError, match="came up as instance, not dev"):
        ds.deploy(SHA)
