"""What A.I.N.D.Y. contains, read from the code: ``docs/verification/INVENTORY.md``.

Owner, 2026-10-25: an inventory first, then an audit of it. A hand-written inventory drifts the week
it is written (CLAUDE.md's syscall count went stale twice), so this one is generated. It boots the
app profile as CI does and reads the registries: domains, routes, syscalls, agent tools, jobs, flows,
Nodus workflows, tables and flags, each credited to the domain whose module registered it.

Two columns exist for the audit:
- **client** — whether any client code calls a route (`docs/verification/client_routes.json`, written
  by `client/src/test/client-routes-manifest.test.js`, since most client paths are built in JS);
- **rows** (``--live`` only) — how many rows each table holds on a real database. A route nothing calls
  and a table nothing fills are how the dead twins were found.

    python scripts/inventory.py            # write docs/verification/INVENTORY.md
    python scripts/inventory.py --check    # CI: exit 1 when the committed file is stale
    python scripts/inventory.py --live     # print row counts per table from DATABASE_URL (not committed)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "verification" / "INVENTORY.md"
CLIENT_ROUTES = ROOT / "docs" / "verification" / "client_routes.json"
COMPOSE = ROOT / "docker-compose.prod.yml"
SHARED = "_shared"
RUNTIME = "(runtime)"

_BOOT_ENV = {
    "DATABASE_URL": "sqlite://", "MONGO_URL": "", "AINDY_ALLOW_SQLITE": "1",
    "OPENAI_API_KEY": "sk-test-placeholder", "DEEPSEEK_API_KEY": "ds-test-placeholder",
    "SECRET_KEY": "apps-integration-secret", "AINDY_API_KEY": "apps-integration-api-key",
    "PERMISSION_SECRET": "apps-integration-permission-secret",
    "AINDY_SKIP_MONGO_PING": "1", "SKIP_MONGO_PING": "1",
}


def _domain(module: str | None) -> str:
    """``apps.<domain>.…`` → domain; ``apps._shared`` → _shared; anything else is the runtime's."""
    parts = (module or "").split(".")
    if len(parts) >= 2 and parts[0] == "apps":
        return parts[1]
    return RUNTIME


def _module_of(obj) -> str | None:
    seen = 0
    while hasattr(obj, "__wrapped__") and seen < 5:  # past decorators and runtime wrappers
        obj = obj.__wrapped__
        seen += 1
    return getattr(obj, "__module__", None)


def boot():
    """The app profile, as `check_api_reference.py` boots it. Returns the FastAPI app."""
    sys.path.insert(0, str(ROOT))
    for key, value in _BOOT_ENV.items():
        os.environ.setdefault(key, value)
    logging.disable(logging.CRITICAL)
    from fastapi.testclient import TestClient

    import AINDY.main as main

    client = TestClient(main.app, raise_server_exceptions=False)
    client.get("/api/version")
    import AINDY.platform_layer.registry as registry

    registry.register_flows()  # app flow graphs register lazily, on first use; the runtime's own loader
    return main.app, client.get("/openapi.json").json()


# ── Collection ──────────────────────────────────────────────────────────────────────────


def _routes(spec: dict) -> list[dict]:
    """Every /apps route, credited by the module of the router that registered it."""
    import AINDY.platform_layer.registry as registry

    documented = {(method.upper(), path) for path, ops in spec.get("paths", {}).items()
                  if path.startswith("/apps/") for method in ops}
    routers = list(registry.get_routers()) + list(registry.get_legacy_root_routers())
    out, placed = [], set()
    for item in routers:
        router = item[0] if isinstance(item, tuple) else item
        for route in getattr(router, "routes", []):
            for method in sorted(getattr(route, "methods", None) or []):
                full = "/apps" + route.path
                key = (method, full)
                if key in documented and key not in placed:
                    placed.add(key)
                    out.append({"method": method, "path": full, "domain": _domain(_module_of(route.endpoint))})
    for method, path in sorted(documented - placed):
        # Not from any app router: the runtime mounts some of its own under /apps (memory, coordination).
        out.append({"method": method, "path": path, "domain": RUNTIME})
    return sorted(out, key=lambda r: (r["path"], r["method"]))


def _client_called(routes: list[dict]) -> None:
    paths = json.loads(CLIENT_ROUTES.read_text(encoding="utf-8"))["paths"] if CLIENT_ROUTES.exists() else []
    patterns = []
    for route in routes:
        template = route["path"].rstrip("/")
        regex = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$"
        patterns.append((route, re.compile(regex)))
    for route, regex in patterns:
        route["client"] = any(regex.match(p) for p in paths)


def _syscalls() -> list[dict]:
    from AINDY.kernel.syscall_registry import SYSCALL_REGISTRY

    return sorted(({"name": name, "capability": entry.capability, "domain": _domain(_module_of(entry.handler))}
                   for name, entry in SYSCALL_REGISTRY.items()), key=lambda s: s["name"])


def _tools() -> list[dict]:
    from AINDY.agents.tool_registry import TOOL_REGISTRY

    out = []
    for name, meta in TOOL_REGISTRY.items():
        fn = next((meta.get(k) for k in ("fn", "handler", "func", "callable") if callable(meta.get(k))), None)
        out.append({"name": name, "risk": meta.get("risk") or "", "domain": _domain(_module_of(fn))})
    return sorted(out, key=lambda t: t["name"])


def _scheduled() -> list[dict]:
    import AINDY.platform_layer.registry as registry

    out = []
    for job in registry.get_scheduled_jobs():
        kwargs = job.get("trigger_kwargs") or {}
        when = ", ".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        out.append({"id": job["id"], "when": f"{job.get('trigger')} {when}".strip(),
                    "domain": _domain(_module_of(job.get("handler")))})
    return sorted(out, key=lambda j: j["id"])


def _jobs() -> list[dict]:
    import AINDY.platform_layer.registry as registry

    return sorted(({"name": name, "domain": _domain(_module_of(handler))} for name, handler in registry.iter_jobs()),
                  key=lambda j: j["name"])


def _flows() -> list[dict]:
    """Python flow graphs, credited by the domain of their nodes."""
    from AINDY.runtime.flow_engine import FLOW_REGISTRY, NODE_REGISTRY

    out = []
    for name, flow in FLOW_REGISTRY.items():
        names: set[str] = set()
        if isinstance(flow, dict):
            names.add(flow.get("start"))
            names.update(flow.get("end") or [])
            for source, targets in (flow.get("edges") or {}).items():
                names.add(source)
                names.update(t if isinstance(t, str) else (t or {}).get("to") for t in (targets or []))
        names.discard(None)
        domains = {_domain(_module_of(NODE_REGISTRY.get(n))) for n in names} - {RUNTIME}
        out.append({"name": name, "nodes": len(names), "domain": sorted(domains)[0] if domains else RUNTIME})
    return sorted(out, key=lambda f: f["name"])


def _nodus() -> list[dict]:
    return sorted(({"name": p.stem, "path": p.relative_to(ROOT).as_posix(), "domain": p.parent.parent.name}
                   for p in (ROOT / "apps").glob("*/nodus/*.nd")), key=lambda n: n["name"])


def _tables() -> list[dict]:
    from AINDY.db.database import Base

    out = {}
    for mapper in Base.registry.mappers:
        table = getattr(mapper, "local_table", None)
        if table is not None and table.name not in out:
            out[table.name] = {"name": table.name, "domain": _domain(mapper.class_.__module__)}
    return sorted(out.values(), key=lambda t: t["name"])


def _compose_flags() -> dict[str, str]:
    text = COMPOSE.read_text(encoding="utf-8") if COMPOSE.exists() else ""
    return {m.group(1): m.group(2) for m in re.finditer(r'^\s+(AINDY_[A-Z0-9_]+):\s*"\$\{\1:-([^}]*)\}"', text, re.M)}


def _flags() -> list[dict]:
    """AINDY_* names read under apps/, by domain, with what compose sets them to."""
    readers: dict[str, set[str]] = defaultdict(set)
    for path in (ROOT / "apps").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        domain = path.relative_to(ROOT / "apps").parts[0]
        for name in set(re.findall(r"""["'](AINDY_[A-Z0-9_]+)["']""", path.read_text(encoding="utf-8"))):
            readers[name].add(domain)
    compose = _compose_flags()
    names = sorted(set(readers) | set(compose))
    return [{"name": n, "read_by": sorted(readers.get(n, [])) or [RUNTIME],
             "compose": compose.get(n)} for n in names]


def _domains() -> list[dict]:
    import importlib

    from apps.bootstrap import APP_BOOTSTRAP_MODULES

    out = []
    for name, module_name in APP_BOOTSTRAP_MODULES.items():
        module = importlib.import_module(module_name)
        out.append({"name": name, "core": bool(getattr(module, "IS_CORE_DOMAIN", False)),
                    "depends_on": list(getattr(module, "APP_DEPENDS_ON", []) or [])})
    return sorted(out, key=lambda d: d["name"])


def collect() -> dict:
    _, spec = boot()
    routes = _routes(spec)
    _client_called(routes)
    return {"domains": _domains(), "routes": routes, "syscalls": _syscalls(), "tools": _tools(),
            "scheduled": _scheduled(), "jobs": _jobs(), "flows": _flows(), "nodus": _nodus(),
            "tables": _tables(), "flags": _flags()}


# ── Rendering ───────────────────────────────────────────────────────────────────────────


def _ours(items: list[dict]) -> list[dict]:
    return [i for i in items if i["domain"] != RUNTIME]


def render(inv: dict) -> str:
    domains = [d["name"] for d in inv["domains"]]
    by = {key: defaultdict(list) for key in ("routes", "syscalls", "tools", "scheduled", "jobs", "flows", "nodus", "tables")}
    for key in by:
        for item in inv[key]:
            by[key][item["domain"]].append(item)
    routes = inv["routes"]
    L = [
        "---",
        'title: "Inventory — what A.I.N.D.Y. contains"',
        'last_verified: "{last_verified}"',
        'api_version: "1.0"',
        "status: current",
        'owner: "app-team"',
        "---",
        "",
        "# Inventory — what A.I.N.D.Y. contains",
        "",
        "**Generated by `scripts/inventory.py` from the code. Do not edit by hand;** rerun the script.",
        "CI fails when this file is stale. It lists what exists; whether each thing works and belongs is",
        "the audit's question. Live row counts are not here (they change): `python scripts/inventory.py --live`.",
        "",
        "## Totals",
        "",
        "| | ours | runtime's |",
        "|---|---|---|",
        f"| Domains | {len(domains)} ({sum(d['core'] for d in inv['domains'])} core) | |",
        f"| `/apps` routes | {len(_ours(routes))} ({sum(1 for r in _ours(routes) if r['client'])} called by the client, "
        f"{sum(1 for r in _ours(routes) if not r['client'])} not) | {len(routes) - len(_ours(routes))} (mounted under `/apps`) |",
    ]
    for key, label in (("syscalls", "Syscalls"), ("tools", "Agent tools"), ("scheduled", "Scheduled jobs"),
                       ("jobs", "Registered jobs"), ("flows", "Python flow graphs"), ("tables", "Tables")):
        ours = len(_ours(inv[key]))
        L.append(f"| {label} | {ours} | {len(inv[key]) - ours} |")
    L.append(f"| Nodus workflows (`.nd`) | {len(inv['nodus'])} | |")
    L.append(f"| `AINDY_*` flags read by our code | {sum(1 for f in inv['flags'] if f['read_by'] != [RUNTIME])} | |")
    L += ["", "## Domains", "", "| Domain | Core | Declared imports | Routes | Not called | Syscalls | Tools | Sched. jobs | Jobs | Flows | `.nd` | Tables |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in inv["domains"]:
        n = d["name"]
        rs = by["routes"][n]
        L.append(f"| {n} | {'yes' if d['core'] else ''} | {', '.join(d['depends_on'])} | {len(rs)} | "
                 f"{sum(1 for r in rs if not r['client'])} | {len(by['syscalls'][n])} | {len(by['tools'][n])} | "
                 f"{len(by['scheduled'][n])} | {len(by['jobs'][n])} | {len(by['flows'][n])} | {len(by['nodus'][n])} | "
                 f"{len(by['tables'][n])} |")
    for extra in (SHARED, RUNTIME):
        if any(by[k].get(extra) for k in by):
            L.append(f"| {extra} | | | {len(by['routes'][extra])} | {sum(1 for r in by['routes'][extra] if not r['client'])} | "
                     f"{len(by['syscalls'][extra])} | {len(by['tools'][extra])} | {len(by['scheduled'][extra])} | "
                     f"{len(by['jobs'][extra])} | {len(by['flows'][extra])} | {len(by['nodus'][extra])} | {len(by['tables'][extra])} |")

    for d in [*inv["domains"], {"name": SHARED}, {"name": RUNTIME}]:
        n = d["name"]
        if not any(by[k].get(n) for k in by):
            continue
        if n == RUNTIME:
            # Only what the runtime mounts on our surface; its syscalls and tables are counted above.
            by = {**by, **{k: {RUNTIME: []} for k in by if k != "routes"}}
            L += ["", "## The runtime's routes under /apps", ""]
        else:
            L += ["", f"## {n}", ""]
        if by["routes"][n]:
            L += [f"**Routes ({len(by['routes'][n])}).** — = no client code calls it.", ""]
            L += [f"- {'' if r['client'] else '— '}`{r['method']} {r['path']}`" for r in by["routes"][n]]
            L.append("")
        for key, label, fmt in (
            ("syscalls", "Syscalls", lambda s: f"`{s['name']}` ({s['capability']})"),
            ("tools", "Agent tools", lambda t: f"`{t['name']}`" + (f" (risk {t['risk']})" if t["risk"] else "")),
            ("scheduled", "Scheduled jobs", lambda j: f"`{j['id']}` ({j['when']})"),
            ("jobs", "Registered jobs", lambda j: f"`{j['name']}`"),
            ("flows", "Python flow graphs", lambda f: f"`{f['name']}` ({f['nodes']} nodes)"),
            ("nodus", "Nodus workflows", lambda w: f"`{w['path']}`"),
            ("tables", "Tables", lambda t: f"`{t['name']}`"),
        ):
            if by[key][n]:
                L.append(f"**{label} ({len(by[key][n])}):** " + ", ".join(fmt(i) for i in by[key][n]))
                L.append("")
        while L and L[-1] == "":
            L.pop()

    L += ["", "## Flags", "", "Every `AINDY_*` name our code reads, and every one compose sets. Compose's value is the",
          "default it passes when `.env` says nothing; blank means compose does not set it.", "",
          "| Flag | Read by | Compose |", "|---|---|---|"]
    for f in inv["flags"]:
        compose = "" if f["compose"] is None else (f"`{f['compose']}`" if f["compose"] else '`""`')
        L.append(f"| `{f['name']}` | {', '.join(f['read_by'])} | {compose} |")
    return "\n".join(L) + "\n"


# ── Live ────────────────────────────────────────────────────────────────────────────────


def live(inv: dict) -> str:
    """Row counts for our tables from DATABASE_URL. For the audit; never committed."""
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(os.environ["AINDY_INVENTORY_DATABASE_URL"])
    present = set(inspect(engine).get_table_names())
    lines = ["| Domain | Table | Rows |", "|---|---|---|"]
    with engine.connect() as conn:
        for table in _ours(inv["tables"]):
            rows = conn.execute(text(f'SELECT count(*) FROM "{table["name"]}"')).scalar() if table["name"] in present else "missing"
            lines.append(f"| {table['domain']} | `{table['name']}` | {rows} |")
    return "\n".join(lines) + "\n"


def _undated(text: str) -> str:
    return re.sub(r'^last_verified: ".*"$', "last_verified:", text, flags=re.M)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed inventory is stale")
    parser.add_argument("--live", action="store_true",
                        help="print row counts from AINDY_INVENTORY_DATABASE_URL instead of writing the file")
    args = parser.parse_args(argv)
    if args.live and not os.environ.get("AINDY_INVENTORY_DATABASE_URL"):
        parser.error("--live reads AINDY_INVENTORY_DATABASE_URL (the boot itself uses an in-memory database)")
    inv = collect()
    if args.live:
        print(live(inv))
        return 0
    body = render(inv)
    current = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else ""
    if args.check:
        if _undated(current) != _undated(body):
            print(f"{OUT.relative_to(ROOT)} is stale: run `python scripts/inventory.py` and commit it.")
            return 1
        print(f"{OUT.relative_to(ROOT)} OK.")
        return 0
    # The date moves only when the content does, so an unchanged inventory never goes stale on a date.
    kept = re.search(r'^last_verified: "([0-9-]+)"$', current, re.M)
    date = kept.group(1) if kept and _undated(current) == _undated(body) else dt.date.today().isoformat()
    OUT.write_text(body.replace("{last_verified}", date, 1), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
