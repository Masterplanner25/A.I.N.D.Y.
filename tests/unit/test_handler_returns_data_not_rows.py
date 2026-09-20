"""A pipeline handler returns data, not ORM rows — ROUTE-PIPELINE-ORM-RETURN-1.

With the request session in `metadata["db"]` (#393), the pipeline commits it after the handler.
`expire_on_commit` then empties every loaded instance, and a handler that returned ORM rows hands
the JSON encoder empty dicts: `GET /apps/rippletrace/drop_points` served 214 `{}`s and the page
showed "unknown" on every row (2026-09-20). Each attribute the encoder touched after that was a
lazy refresh on a post-commit session — the api wedged for a quarter of an hour.

`apps/_shared/serialization.materialize` converts rows to dicts of their column attributes while
the session is live; `materialized(handler)` applies it before the pipeline can commit. Every
RippleTrace route and the legacy surface's wrapper go through it. This file reproduces the
failure on a real (SQLite) session so the guard is against the mechanism, not the symptom.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from apps._shared.serialization import materialize, materialized

pytestmark = pytest.mark.app_profile

_Base = declarative_base()


class _Row(_Base):
    __tablename__ = "probe_rows"
    id = Column(Integer, primary_key=True)
    platform = Column(String(32))
    title = Column(String(64))


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=True)
    s = Session()
    s.add_all([_Row(id=1, platform="DEV", title="one"), _Row(id=2, platform="Substack", title="two")])
    s.commit()
    yield s
    s.close()


def test_the_failure_is_real_on_a_committed_session(session):
    """What #393 exposed: rows returned raw, then the pipeline's commit, then the encoder."""
    rows = session.query(_Row).all()
    session.commit()  # the pipeline's post-handler commit
    encoded = jsonable_encoder(rows)
    assert encoded == [{}, {}], encoded  # exactly what the page received


def test_materialize_reads_the_rows_while_the_session_is_live(session):
    rows = session.query(_Row).all()
    data = materialize(rows)  # inside the handler, before any commit
    session.commit()
    assert data == [
        {"id": 1, "platform": "DEV", "title": "one"},
        {"id": 2, "platform": "Substack", "title": "two"},
    ]
    assert jsonable_encoder(data) == data


def test_materialized_wraps_a_handler_and_walks_containers(session):
    def handler(_ctx):
        row = session.get(_Row, 1)
        return {"drop_point": row, "pings": [row, row], "count": 1, "note": None}

    out = materialized(handler)(None)
    session.commit()
    assert out["drop_point"] == {"id": 1, "platform": "DEV", "title": "one"}
    assert out["pings"] == [out["drop_point"], out["drop_point"]]
    assert out["count"] == 1 and out["note"] is None


def test_materialize_leaves_non_rows_alone():
    class Plain:
        pass

    p = Plain()
    assert materialize(p) is p
    assert materialize(_Row) is _Row  # a mapped CLASS is not a row
    assert materialize("x") == "x" and materialize(3) == 3
    assert materialize({"a": (1, 2)}) == {"a": [1, 2]}


def test_every_rippletrace_pipeline_handler_is_materialized():
    """The 44 RippleTrace routes hand raw service results to the pipeline; each must go through
    `materialized(...)`. The legacy surface does it once, in `_run_legacy`."""
    root = pathlib.Path(__file__).resolve().parents[2] / "apps" / "rippletrace" / "routes"
    src = (root / "rippletrace_router.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    bare, wrapped = [], 0
    for call in ast.walk(tree):
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "execute_with_pipeline":
            h = call.args[2] if len(call.args) > 2 else next((k.value for k in call.keywords if k.arg == "handler"), None)
            if isinstance(h, ast.Call) and getattr(h.func, "id", None) == "materialized":
                wrapped += 1
            else:
                bare.append(call.args[1].value if len(call.args) > 1 and isinstance(call.args[1], ast.Constant) else call.lineno)
    assert not bare, f"rippletrace routes handing raw handler results to the pipeline: {bare}"
    assert wrapped >= 40, wrapped
    legacy = (root / "legacy_surface_router.py").read_text(encoding="utf-8")
    assert "handler=materialized(handler)" in legacy
