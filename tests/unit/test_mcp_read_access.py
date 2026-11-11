"""Read access for an outside AI over MCP: the owner's Works, scoped to the caller only.

Owner, 2026-10-14: the Infinity Algorithm is the product, and other AIs are access to its state. The
properties: an outside AI can read the Works and everything known about one; what it reads is the
CALLER's (the runtime refuses a payload `user_id` naming someone else, but an exposed syscall still reads
`ctx.user_id`); and the launcher exposes reads only.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import pathlib
import uuid

import pytest

from apps.masterplan.services import work_service as ws
from apps.masterplan.syscalls import syscall_handlers as sh
from AINDY.kernel.syscall_registry import SyscallContext

pytestmark = pytest.mark.app_profile

ROOT = pathlib.Path(__file__).resolve().parents[2]
OWNER = uuid.uuid4()
OTHER = uuid.uuid4()


def _ctx(db, user):
    return SyscallContext(execution_unit_id="eu", user_id=str(user), capabilities=[], trace_id="t",
                          metadata={"_db": db})


def _launcher():
    spec = importlib.util.spec_from_file_location("mcp_launcher", ROOT / "scripts" / "mcp_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_outside_ai_reads_the_callers_works_and_never_another_users(db_session):
    ws.create_work(db_session, OWNER, {"name": "Nodus", "summary": "An orchestration DSL."})
    ws.create_work(db_session, OTHER, {"name": "Secret", "summary": "Someone else's."})

    out = sh._handle_work_context({"user_id": str(OTHER)}, _ctx(db_session, OWNER))  # a payload id is ignored
    assert out["works"] == ["Nodus"] and "Secret" not in out["block"]
    assert "Nodus (project, creator, active): An orchestration DSL." in out["block"]


def test_one_works_facts_by_name_and_a_miss_lists_what_exists(db_session):
    ws.create_work(db_session, OWNER, {"name": "Nodus", "summary": "An orchestration DSL."})
    hit = sh._handle_work_facts({"work": "  nodus "}, _ctx(db_session, OWNER))
    assert hit["found"] and hit["work"] == "Nodus"
    assert "THE PERSON'S OWN FACTS ABOUT Nodus" in hit["facts"]
    miss = sh._handle_work_facts({"work": "Nodes"}, _ctx(db_session, OWNER))
    assert (miss["found"], miss["works"]) == (False, ["Nodus"])
    assert sh._handle_work_facts({"work": "Nodus"}, _ctx(db_session, OTHER))["found"] is False
    with pytest.raises(ValueError):
        sh._handle_work_facts({}, _ctx(db_session, OWNER))


def test_no_users_works_means_an_empty_answer_not_an_error(db_session):
    assert sh._handle_work_context({}, _ctx(db_session, uuid.uuid4())) == {"block": "", "works": []}


def test_every_app_syscall_the_launcher_exposes_is_registered_read_only_and_caller_scoped():
    from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

    sh.register_masterplan_syscall_handlers()
    ours = [name for name in _launcher().READ_ONLY_TOOLS if not name.startswith("sys.v1.memory.")]
    assert ours == ["sys.v1.work.context", "sys.v1.work.facts"]
    for name in ours:
        entry = SYSCALL_REGISTRY[name]
        # DEC-128 (2.35.0): without it the launcher refuses to start, naming the syscall.
        assert entry.read_only is True, f"{name} must be registered read_only=True"
        source = inspect.getsource(entry.handler)
        assert 'payload["user_id"]' not in source and "payload.get(\"user_id\")" not in source, (
            f"{name} reads user_id from the payload; over MCP that is whoever the outside AI names")


def test_an_inherited_tool_list_cannot_replace_the_launchers(monkeypatch):
    """Since 2.31.1 (DEC-112) any syscall named in the list is really callable, delete included."""
    import AINDY.platform_layer.mcp_server as runtime_server

    monkeypatch.setenv("AINDY_MCP_SERVER_TOOLS", "sys.v1.memory.delete")
    monkeypatch.delenv("AINDY_MCP_SERVER_ALLOW_WRITES", raising=False)
    monkeypatch.setattr(runtime_server, "serve_stdio", lambda: None)
    launcher = _launcher()
    launcher.main([])
    assert os.environ["AINDY_MCP_SERVER_TOOLS"] == ",".join(launcher.READ_ONLY_TOOLS)


def test_the_launcher_refuses_writes(monkeypatch):
    monkeypatch.setenv("AINDY_MCP_SERVER_ALLOW_WRITES", "true")
    with pytest.raises(SystemExit) as exc:
        _launcher().main([])
    assert "read-only" in str(exc.value)


def test_over_http_the_launcher_refuses_to_start_without_oauth(monkeypatch):
    """Without OAuth the runtime answers every HTTP caller as one configured user, and this server is public."""
    import AINDY.platform_layer.mcp_server as runtime_server

    monkeypatch.delenv("AINDY_MCP_OAUTH", raising=False)
    monkeypatch.delenv("AINDY_MCP_SERVER_ALLOW_WRITES", raising=False)
    monkeypatch.setattr(runtime_server, "serve_http", lambda **kw: pytest.fail("served without OAuth"))
    with pytest.raises(SystemExit) as exc:
        _launcher().main(["--transport", "http", "--host", "0.0.0.0"])
    assert "AINDY_MCP_OAUTH" in str(exc.value)


def test_over_http_with_oauth_it_serves_the_same_read_only_list(monkeypatch):
    import AINDY.platform_layer.mcp_server as runtime_server

    served = {}
    monkeypatch.setenv("AINDY_MCP_OAUTH", "on")
    monkeypatch.setenv("AINDY_MCP_SERVER_TOOLS", "sys.v1.memory.delete")
    monkeypatch.delenv("AINDY_MCP_SERVER_ALLOW_WRITES", raising=False)
    monkeypatch.setattr(runtime_server, "serve_http", lambda **kw: served.update(kw))
    launcher = _launcher()
    launcher.main(["--transport", "http", "--host", "0.0.0.0", "--port", "8080"])
    assert served == {"host": "0.0.0.0", "port": 8080}
    assert os.environ["AINDY_MCP_SERVER_TOOLS"] == ",".join(launcher.READ_ONLY_TOOLS)
