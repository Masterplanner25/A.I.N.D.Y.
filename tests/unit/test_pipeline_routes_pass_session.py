"""Every pipeline call site hands the pipeline the request session — ROUTE-PIPELINE-NO-SESSION-1.

`execute_with_pipeline*` reads the request session from `metadata["db"]`. Without it the runtime's
`_requires_route_side_effects` is False, `_safe_emit_event` writes no `execution.started` /
`execution.completed`, `_safe_require_eu` attaches no execution unit, and the tenant quota check
is skipped — the route answers, and leaves no trace in the execution ledger.

Found 2026-09-19 while fixing `ROUTE-NAME-EVENT-SOURCE-1`: 69 of 235 direct call sites, plus 25
more behind a wrapper-of-a-wrapper the first scan missed — all 44 RippleTrace routes (with no
`user_id` either, and a hand-built envelope of `eu_id=None, trace_id=None` over a body the
`raw_json_adapter` had already finished), all 27 legacy RippleTrace surfaces, the 5 score
routes, 3 social reads, `authorship.reclaim`. `system_events` held zero rows with a rippletrace
source, ever. Twenty router files passed a session on every call; these did not.

This test walks every call to the pipeline — directly, or through any app wrapper that reaches
it, transitively — and asserts a session is handed over at each site. A wrapper counts as
passing one only if it forwards `metadata` containing `db`, unconditionally or from a `db`
parameter the caller supplies.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.app_profile

APPS = pathlib.Path(__file__).resolve().parents[2] / "apps"
PIPELINE = {"execute_with_pipeline", "execute_with_pipeline_sync"}


def _call_name(call: ast.Call) -> str:
    return getattr(call.func, "attr", None) or getattr(call.func, "id", None) or ""


def _dict_has_db(node) -> bool:
    return isinstance(node, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "db" for k in node.keys)


def _metadata_carries_db(call: ast.Call, fn) -> str:
    """'yes' | 'no' | 'param' (forwards a `db` parameter, so the caller must supply it)."""
    md = next((kw.value for kw in call.keywords if kw.arg == "metadata"), None)
    if md is None:
        return "no"
    if _dict_has_db(md):
        return "yes"
    if isinstance(md, ast.IfExp):  # {"db": db} if db is not None else None
        return "param" if _dict_has_db(md.body) or _dict_has_db(md.orelse) else "no"
    if isinstance(md, ast.Name):
        # metadata = {...}; metadata["db"] = db  — assembled in the function body
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == md.id for t in n.targets):
                if _dict_has_db(n.value):
                    return "yes"
            if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == md.id
                and isinstance(t.slice, ast.Constant) and t.slice.value == "db"
                for t in n.targets
            ):
                return "param"
    return "no"


def _scan():
    """Returns (wrappers, sites). wrappers: name -> 'yes'|'no'|'param'. sites: list of dicts."""
    functions = {}  # name -> (fn node, file)
    for path in APPS.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.setdefault(fn.name, []).append((fn, path))

    # wrappers: functions that call the pipeline (or another wrapper) with a non-literal route name
    wrappers: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for name, defs in functions.items():
            if name in wrappers:
                continue
            for fn, _path in defs:
                for call in ast.walk(fn):
                    if not isinstance(call, ast.Call):
                        continue
                    cname = _call_name(call)
                    if cname in PIPELINE:
                        route = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "route_name"), None)
                        if not isinstance(route, ast.Constant):
                            wrappers[name] = _metadata_carries_db(call, fn)
                            changed = True
                    elif cname in wrappers and cname != name:
                        route = call.args[1] if len(call.args) > 1 else None
                        if not isinstance(route, ast.Constant):
                            inner = wrappers[cname]
                            forwards_db = any(kw.arg == "db" for kw in call.keywords)
                            if inner == "yes":
                                wrappers[name] = "yes"
                            elif inner == "param" and forwards_db:
                                wrappers[name] = "param"  # still needs the outer caller to supply db
                            else:
                                wrappers[name] = "no"
                            changed = True

    sites = []
    for name, defs in functions.items():
        for fn, path in defs:
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                cname = _call_name(call)
                route = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "route_name"), None)
                if not isinstance(route, ast.Constant):
                    continue
                if cname in PIPELINE:
                    ok = _metadata_carries_db(call, fn) == "yes"
                elif cname in wrappers:
                    verdict = wrappers[cname]
                    ok = verdict == "yes" or (verdict == "param" and any(kw.arg == "db" for kw in call.keywords))
                else:
                    continue
                sites.append({"route": route.value, "where": f"{path.relative_to(APPS.parent)}:{call.lineno}", "ok": ok, "via": cname})
    return wrappers, sites


def test_the_scan_sees_the_whole_surface():
    wrappers, sites = _scan()
    assert len(sites) > 250, f"only {len(sites)} pipeline call sites found — did the call shape change?"
    assert "_wrap_legacy" in wrappers and "_execute_agent" in wrappers
    routes = {s["route"] for s in sites}
    assert {"agent.run.create", "rippletrace_record_citation", "rippletrace.legacy.top_drop_points", "scores_get_me"} <= routes


def test_every_pipeline_call_site_passes_a_session():
    _wrappers, sites = _scan()
    missing = sorted(f'{s["route"]} ({s["where"]}, via {s["via"]})' for s in sites if not s["ok"])
    assert not missing, (
        f"{len(missing)} pipeline call site(s) hand the pipeline no session — those routes write no "
        f"execution.started/completed, attach no execution unit and skip the quota check:\n  " + "\n  ".join(missing)
    )
