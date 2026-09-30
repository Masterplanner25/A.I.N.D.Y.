"""No path of ours needs recall to see a memory write that has not been committed.

Soak register row 1, `AINDY_MEMORY_RECALL_OWN_SESSION` (on this stack since 2026-09-23). With it on,
recall reads through its own session, so a write the caller has made and not yet committed is no
longer visible to it: the flag's one behaviour change. Audited 2026-09-30 across the nine places our
apps recall (`RUNTIME_2_24_0_UPGRADE.md` §8). Eight recall before they write, or never write. The
ninth, task completion, writes a note and then recalls, and is safe twice over: under a request the
note is queued until the handler returns, and it is an `outcome` note while the recall asks for
`decision` notes. Agent plans that write in one step and recall in a later one are safe because
each tool step commits its own write. These tests hold those facts in place.
"""
from __future__ import annotations

import ast
import inspect

import pytest

pytestmark = pytest.mark.app_profile


def _recall_node_types(fn) -> list[str]:
    """The `node_type` each `get_context(..., metadata={...})` call inside `fn` asks for."""
    tree = ast.parse(inspect.getsource(fn).lstrip())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "get_context":
            for kw in node.keywords:
                if kw.arg == "metadata" and isinstance(kw.value, ast.Dict):
                    for key, value in zip(kw.value.keys, kw.value.values):
                        if isinstance(key, ast.Constant) and key.value == "node_type":
                            found.append(value.value)
    return found


def test_task_completion_never_recalls_the_note_it_just_wrote():
    from apps.tasks.memory_policy import POLICIES
    from apps.tasks.services.task_service import orchestrate_task_completion

    written = POLICIES["task_completed"]["node_type"]
    recalled = _recall_node_types(orchestrate_task_completion)
    assert recalled, "orchestrate_task_completion no longer recalls; re-audit this file's premise"
    assert written not in recalled, (
        f"task completion now recalls {recalled} after writing a {written!r} note in the same "
        "transaction; with AINDY_MEMORY_RECALL_OWN_SESSION on, that note is invisible to the recall"
    )


@pytest.mark.parametrize("tool", ["memory_write", "memory_recall"])
def test_agent_memory_steps_dispatch_without_the_callers_session(tool, monkeypatch):
    """Without a caller session the runtime's handler opens its own and commits it, so a
    `memory.write` step is committed before a later `memory.recall` step reads."""
    from apps.agent.agents import tools

    seen = {}

    def fake_invoke(name, payload, *, user_id, capability, db=None):
        seen["db"] = db
        return {"node_id": "n", "results": []}

    monkeypatch.setattr(tools, "invoke_tool_syscall", fake_invoke)
    getattr(tools, tool)({"query": "q", "content": "c"}, "user-1", object())
    assert seen["db"] is None
