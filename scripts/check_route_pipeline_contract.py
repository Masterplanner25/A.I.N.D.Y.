#!/usr/bin/env python
"""Fail if a managed route raises HTTPException before it enters the execution pipeline.

Why this needs a guard rather than review
-----------------------------------------
The runtime wraps every route mounted under ``/apps`` and cannot distinguish a
deliberate ``HTTPException`` from a route that bypassed the pipeline. Anything raised
before ``request.state.execution_context`` exists is re-raised as
``RouteExecutionViolation``, so the client receives::

    {"error": "internal_error", "message": "Internal server error"}

instead of the status and reason the route intended. The code reads correctly — it only
misbehaves through the wrapper — which is why this survived multiple reviews.

Four handoff defects traced back to it: the MasterPlan detail 500 (a JSON-serialization
error hidden behind an opaque 500), Genesis lock's missing-draft 400, and every
validation error in the Genesis router. A search-feedback 422 and five freelance
"Idempotency-Key required" 400s were all being served as 500s too.

What counts as a violation
--------------------------
A ``raise HTTPException`` in a route function's own body (not a nested handler) that
appears **before** the call that enters the pipeline. A raise *after* that call is fine:
the context exists by then, so the guard passes it through — ``tasks.start`` relies on
exactly that to return its 404.

Pipeline entry is resolved through module-level helpers (``_execute_genesis``,
``_execute_tasks``, ...), matching how the runtime's own analyser resolves it.

The fix is always the same: move the check inside the handler closure.
"""

from __future__ import annotations

import ast
import pathlib
import sys

HTTP_VERBS = {"get", "post", "put", "patch", "delete"}
PIPELINE_CALLS = {"execute_with_pipeline", "execute_with_pipeline_sync"}
ROUTES_GLOB = "routes/*.py"
APPS_ROOT = pathlib.Path("apps")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _is_route(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in fn.decorator_list:
        call = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(call, ast.Attribute) and call.attr in HTTP_VERBS:
            value = call.value
            if isinstance(value, ast.Name) and "router" in value.id.lower():
                return True
    return False


def _pipeline_entering_names(tree: ast.Module) -> set[str]:
    """Pipeline calls plus any module-level helper that reaches one."""
    entering = set(PIPELINE_CALLS)
    for _ in range(3):  # transitive closure; depth 3 is far beyond observed nesting
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _called_names(node) & entering:
                    entering.add(node.name)
    return entering


def _violations_in(path: pathlib.Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:  # pragma: no cover - a syntax error fails elsewhere
        return [f"{path}: could not parse ({exc})"]

    entering = _pipeline_entering_names(tree)
    found: list[str] = []

    for fn in [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_route(node)
    ]:
        nested = {
            n
            for child in ast.walk(fn)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not fn
            for n in ast.walk(child)
        }
        entry_lines = [
            node.lineno
            for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and node not in nested
            and (
                (isinstance(node.func, ast.Name) and node.func.id in entering)
                or (isinstance(node.func, ast.Attribute) and node.func.attr in entering)
            )
        ]
        first_entry = min(entry_lines) if entry_lines else sys.maxsize

        for node in ast.walk(fn):
            if not isinstance(node, ast.Raise) or node in nested:
                continue
            if node.lineno >= first_entry:
                continue
            exc = node.exc
            name = exc.func if isinstance(exc, ast.Call) else exc
            if isinstance(name, ast.Name) and name.id == "HTTPException":
                found.append(
                    f"{path}:{node.lineno}  {fn.name}()  {lines[node.lineno - 1].strip()[:80]}"
                )
    return found


def main() -> int:
    if not APPS_ROOT.is_dir():
        print("apps/ not found — run from the repo root", file=sys.stderr)
        return 2

    violations: list[str] = []
    scanned = 0
    for path in sorted(APPS_ROOT.rglob(ROUTES_GLOB)):
        scanned += 1
        violations.extend(_violations_in(path))

    if violations:
        print(f"{len(violations)} pre-pipeline HTTPException raise(s) found:\n")
        for violation in violations:
            print(f"  {violation}")
        print(
            "\nRaised before pipeline entry, these reach the client as an opaque 500 "
            "because the runtime's route guard rewrites them as RouteExecutionViolation."
            "\nMove each check inside the handler closure passed to the pipeline."
        )
        return 1

    print(f"Route pipeline contract OK - {scanned} router modules scanned, 0 violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
