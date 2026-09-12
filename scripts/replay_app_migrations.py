#!/usr/bin/env python
"""Replay the newest app migrations against an EXISTING, populated database.

`TEST-INFRA-GAPS-1` item 2. There are 150+ app-owned revisions and CI has only ever exercised
the fresh-deploy path: `bootstrap-schema`, then `deploy_bootstrap.py`, which **stamps** head on
an empty database. That is the right guard for a fresh deploy (`APP-DEPLOY-1`), and it is not
the path a real deployment takes. A real deployment already has the tables, already has rows in
them, and runs `alembic upgrade head` — the one path nothing tested, so a revision that breaks
only on replay (a `NOT NULL` column added to a table with rows, a constraint that fails on
existing data, a downgrade that leaves something behind) reached production unchallenged.

★ What this does, on a database the fresh path has just built:

1. **Seed** a user, a plan, a task, a drop point and a ping — rows in the tables the recent
   revisions add columns to, so "the column arrived with a default the existing rows accept" is
   tested rather than assumed.
2. **Snapshot** the schema (tables, columns with types, indexes).
3. **Downgrade** the newest N revisions. Every one of them must reverse cleanly.
4. **Upgrade head** — the replay. This is the step production runs.
5. Assert the schema is **identical** to the snapshot, `alembic_version` is at head, and the
   seed rows survived with their values.

It is a round trip, not a fixture from production, so it proves the newest revisions are
reversible and replayable over rows — not that the database on the box matches any of it. That
is the bound, stated so the check is not read as more than it is.

Run against a THROWAWAY database only. It downgrades. `DATABASE_URL` is required and refuses
to look like the local stack's.

Usage:
    python scripts/replay_app_migrations.py --steps 16
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The compose stack's database. This script downgrades; it must never run there.
_REFUSED_FRAGMENTS = ("@postgres:", "@postgres/", "aindy:aindy@localhost:5432", "aindy:aindy@127.0.0.1:5432")


def _alembic(*args: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT,
        capture_output=True, text=True, env=os.environ.copy(),
    )
    if proc.returncode != 0:
        raise SystemExit(f"alembic {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout + proc.stderr


def _current(engine) -> str | None:
    with engine.connect() as c:
        rows = c.execute(text("select version_num from alembic_version")).fetchall()
    return rows[0][0] if rows else None


def _head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(Config(os.path.join(ROOT, "alembic.ini"))).get_heads()
    assert len(heads) == 1, f"expected a single app head, got {heads}"
    return heads[0]


def _walk_down(steps: int) -> list[str]:
    """The revisions the downgrade will pass through, newest first."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(os.path.join(ROOT, "alembic.ini")))
    rev = script.get_revision(_head())
    chain = []
    for _ in range(steps):
        if rev.down_revision is None:
            break
        chain.append(rev.revision)
        down = rev.down_revision
        rev = script.get_revision(down if isinstance(down, str) else down[0])
    return chain


def snapshot(engine) -> dict:
    insp = inspect(engine)
    out = {}
    for table in sorted(insp.get_table_names()):
        if table.startswith("alembic_version"):
            continue
        out[table] = {
            "columns": {
                c["name"]: {"type": str(c["type"]), "nullable": bool(c["nullable"])}
                for c in insp.get_columns(table)
            },
            "indexes": sorted(i["name"] for i in insp.get_indexes(table) if i.get("name")),
        }
    return out


SEED_USER = uuid.uuid4()
SEED_DROP = f"dp-replay-{uuid.uuid4()}"
SEED_PING = f"ping-replay-{uuid.uuid4()}"


def seed(engine) -> dict:
    """Rows in the tables the recent revisions touch. Minimal, and returns what to re-check."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with engine.begin() as c:
        c.execute(text(
            "insert into users (id, email, hashed_password, is_active, is_admin) "
            "values (:id, :email, 'x', true, false)"
        ), {"id": str(SEED_USER), "email": f"replay-{SEED_USER}@example.test"})
        plan_id = c.execute(text(
            "insert into master_plans (start_date, duration_years, target_date, user_id, status) "
            "values (:s, 1.0, :t, :u, 'locked') returning id"
        ), {"s": now, "t": now, "u": str(SEED_USER)}).scalar()
        task_id = c.execute(text(
            "insert into tasks (name, depends_on, user_id, masterplan_id, status, priority, duration) "
            "values ('replay task', '[]', :u, :p, 'completed', 'medium', 2.5) returning id"
        ), {"u": str(SEED_USER), "p": plan_id}).scalar()
        c.execute(text(
            "insert into drop_points (id, title, platform, url, date_dropped, user_id) "
            "values (:id, 'Replay drop point', 'Substack', 'https://example.test/replay', :d, :u)"
        ), {"id": SEED_DROP, "d": now, "u": str(SEED_USER)})
        c.execute(text(
            "insert into pings (id, drop_point_id, ping_type, source_platform, date_detected, "
            "external_url, user_id, strength, connection_type) "
            "values (:id, :dp, 'mention', 'example.test', :d, 'https://example.test/p', :u, 1.0, 'direct')"
        ), {"id": SEED_PING, "dp": SEED_DROP, "d": now, "u": str(SEED_USER)})
    return {"plan_id": plan_id, "task_id": task_id}


def verify_seed(engine, ids: dict) -> None:
    with engine.connect() as c:
        task = c.execute(text("select name, duration, status from tasks where id=:i"), {"i": ids["task_id"]}).first()
        assert task and task[0] == "replay task" and float(task[1]) == 2.5 and task[2] == "completed", task
        plan = c.execute(text("select status, phase from master_plans where id=:i"), {"i": ids["plan_id"]}).first()
        assert plan and plan[0] == "locked", plan
        ping = c.execute(text("select verification from pings where id=:i"), {"i": SEED_PING}).first()
        # pv1verify0001's server_default is what an existing row must receive on replay.
        assert ping and ping[0] == "unverified", ping
        dp = c.execute(text("select count(*) from drop_points where id=:i"), {"i": SEED_DROP}).scalar()
        assert dp == 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--steps", type=int, default=16, help="newest revisions to replay")
    args = parser.parse_args()

    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if any(fragment in url for fragment in _REFUSED_FRAGMENTS):
        print("refusing: DATABASE_URL looks like the local stack's database, and this script downgrades", file=sys.stderr)
        return 2

    engine = create_engine(url)
    head = _head()
    if _current(engine) != head:
        print(f"expected alembic_version at head {head}, found {_current(engine)} — run the fresh path first", file=sys.stderr)
        return 2

    chain = _walk_down(args.steps)
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(Config(os.path.join(ROOT, "alembic.ini")))
    last = script.get_revision(chain[-1])
    target = last.down_revision if isinstance(last.down_revision, str) else last.down_revision[0]

    ids = seed(engine)
    before = snapshot(engine)
    print(f"[replay] seeded rows; snapshot {len(before)} tables; head {head}; replaying {len(chain)} revisions")

    _alembic("downgrade", target)
    assert _current(engine) == target, f"downgrade did not land on {target}: {_current(engine)}"
    mid = snapshot(engine)
    removed = sorted(set(before) - set(mid))
    print(f"[replay] downgraded to {target}: {len(mid)} tables ({len(removed)} removed: {', '.join(removed)})")

    out = _alembic("upgrade", "head")
    ran = out.count("Running upgrade")
    assert _current(engine) == head, f"upgrade did not return to head: {_current(engine)}"
    after = snapshot(engine)

    diff = {t: (before.get(t), after.get(t)) for t in set(before) | set(after) if before.get(t) != after.get(t)}
    if diff:
        for table, (b, a) in sorted(diff.items()):
            bc = set((b or {}).get("columns", {}))
            ac = set((a or {}).get("columns", {}))
            print(f"[replay] DIFF {table}: columns -{sorted(bc - ac)} +{sorted(ac - bc)}; "
                  f"indexes ^{sorted(set((b or {}).get('indexes', [])) ^ set((a or {}).get('indexes', [])))}",
                  file=sys.stderr)
            for col in bc & ac:
                if b["columns"][col] != a["columns"][col]:
                    print(f"[replay]      {table}.{col}: {b['columns'][col]} -> {a['columns'][col]}", file=sys.stderr)
        print(json.dumps({"tables_before": len(before), "tables_after": len(after)}), file=sys.stderr)
        return 1

    verify_seed(engine, ids)
    print(f"[replay] OK: {ran} revisions replayed over populated tables; schema identical "
          f"({len(after)} tables); seed rows intact; alembic_version at {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
