"""SCHEMA-DEFAULT-PARITY-1 — a fresh deploy and a migrated deploy must build the same defaults.

Two things build the app schema and both must agree:

* ``scripts/deploy_bootstrap.py`` on a FRESH database: ``Base.metadata.create_all`` from the
  models, then ``alembic stamp head``. The DB gets whatever ``server_default=`` the model declares.
* ``alembic upgrade head`` on an EXISTING database: the migrations. The DB gets whatever
  ``server_default=`` the migration declares.

A column declared with ``default=`` on the model and ``server_default=`` in the migration lands
with a DB-level default on a migrated deploy and NONE on a fresh one. ORM inserts never notice —
SQLAlchemy fills ``default=`` client-side — but a raw ``INSERT``, ``COPY``, a bulk loader, or the
deploy guard's own seed (which omits the column on purpose) fails on the fresh deploy only.
Nine such columns were found on 2026-09-13 by the guard's first real run; a full-history audit
on 2026-09-16 found **72** (`TECH_DEBT.md`).

This script points at a database built by ``alembic upgrade head`` from empty (the app chain is
self-contained: 160 revisions on 2026-09-16, it predates the runtime split and builds the runtime
tables it needs itself) and, for every app-owned table, compares the reflected column default and
nullability with the model's ``server_default`` / ``nullable``. Any disagreement is a failure —
whichever side is wrong, the fix is to make the model and the migration say the same thing in
the same PR (`docs/operations/MIGRATION_POLICY.md`).

Usage (the deploy-bootstrap guard runs this after building ``parity_scratch``)::

    DATABASE_URL=postgresql://.../parity_scratch python scripts/check_schema_default_parity.py

Exit 0 = parity. Exit 1 = mismatches, each printed as ``table.column | db=… | model=…``.
"""
from __future__ import annotations

import os
import re
import sys

from sqlalchemy import create_engine, inspect

_CAST = re.compile(r"::[a-z_ \[\]\"]+")
_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def normalise(value) -> str | None:
    """Reduce a default expression to a comparable token.

    ``'direct'::character varying`` → ``direct``; ``1.0`` and ``'1'`` → ``1``; ``now()`` and
    ``CURRENT_TIMESTAMP`` → ``now``; ``'[]'::jsonb`` → ``[]``; ``true``/``false`` as-is.
    """
    if value is None:
        return None
    s = _CAST.sub("", str(value)).strip()
    while s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    if s in ("now()", "CURRENT_TIMESTAMP", "now"):
        return "now"
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    if _NUM.match(s):
        f = float(s)
        return str(int(f)) if f == int(f) else str(f)
    return s.lower() if s.lower() in ("true", "false") else s


def model_default(col) -> str | None:
    sd = col.server_default
    if sd is None:
        return None
    arg = getattr(sd, "arg", sd)
    # sa.text("...") / func.now() / plain str
    text = getattr(arg, "text", None)
    if text is None:
        name = getattr(arg, "name", None)
        text = f"{name}()" if name else str(arg)
    return normalise(text)


def app_owned_tables(base):
    for mapper in base.registry.mappers:
        if mapper.class_.__module__.startswith("apps.") and mapper.local_table is not None:
            yield mapper.local_table


def main() -> int:
    os.environ.setdefault("AINDY_SKIP_MONGO_PING", "1")
    import AINDY.db.model_registry  # noqa: F401 — runtime models, so FKs resolve
    import AINDY.memory.memory_persistence  # noqa: F401
    import apps.bootstrap as apps_bootstrap

    apps_bootstrap.bootstrap_models()
    from AINDY.db.database import Base

    engine = create_engine(os.environ["DATABASE_URL"])
    insp = inspect(engine)
    db_tables = set(insp.get_table_names())

    problems: list[str] = []
    checked_tables = checked_columns = 0
    for table in sorted({t.name: t for t in app_owned_tables(Base)}.values(), key=lambda t: t.name):
        if table.name not in db_tables:
            problems.append(f"{table.name} | table missing from the migrated schema")
            continue
        checked_tables += 1
        db_cols = {c["name"]: c for c in insp.get_columns(table.name)}
        for col in table.columns:
            dbc = db_cols.get(col.name)
            if dbc is None:
                problems.append(f"{table.name}.{col.name} | column missing from the migrated schema")
                continue
            checked_columns += 1
            db_default = normalise(dbc.get("default"))
            if db_default and db_default.startswith("nextval(") and col.primary_key:
                db_default = None  # SERIAL pk — create_all emits the sequence too
            m_default = model_default(col)
            if db_default != m_default:
                problems.append(
                    f"{table.name}.{col.name} | default db={db_default!r} model={m_default!r}"
                    + ("" if col.server_default is not None else " (model has client default= only)")
                )
            if bool(dbc.get("nullable")) != bool(col.nullable):
                problems.append(
                    f"{table.name}.{col.name} | nullable db={bool(dbc.get('nullable'))} model={bool(col.nullable)}"
                )

    print(f"[parity] {checked_tables} app-owned tables, {checked_columns} columns checked")
    if problems:
        print(f"[parity] {len(problems)} mismatch(es) between the migrated schema and the models:")
        for p in problems:
            print("  " + p)
        print("[parity] fix: make the model's server_default=/nullable= and the migration agree, same PR "
              "(docs/operations/MIGRATION_POLICY.md)")
        return 1
    print("[parity] OK — a fresh deploy and a migrated deploy build the same defaults")
    return 0


if __name__ == "__main__":
    sys.exit(main())
