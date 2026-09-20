"""Turn a handler's return value into plain data BEFORE the pipeline commits the request session.

`execute_with_pipeline*` runs the handler and then, with the request session in
`metadata["db"]`, commits it (the execution events ride the handler's transaction — runtime
2.21.0, `EVENT-OUTBOX-1`). SQLAlchemy's `expire_on_commit` then empties every loaded instance,
so a handler that returned ORM rows hands the JSON encoder 214 `{}`s — and each attribute the
encoder touches is a lazy refresh on a session in a post-commit state, which is how
`GET /apps/rippletrace/drop_points` wedged the api for a quarter of an hour on 2026-09-20
(`ROUTE-PIPELINE-ORM-RETURN-1`). Nothing about that was visible while the routes passed no
session: no commit, no expiry, the rows serialised by accident.

A handler returns data. Where a service still hands back ORM instances, wrap the handler:

    return await execute_with_pipeline(request, name, materialized(handler), user_id=..., metadata={"db": db})

`materialize` walks lists / tuples / dicts and converts every SQLAlchemy instance to a dict of
its **column attributes only** — the loaded columns, read while the session is live. It never
follows relationships (that is a lazy load, the thing this exists to prevent), and it leaves
everything that is not an ORM instance untouched.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import NoInspectionAvailable


def _is_orm_instance(value: Any) -> bool:
    if isinstance(value, type):
        return False  # a mapped CLASS inspects too; only instances are rows
    try:
        return sa_inspect(value, raiseerr=False) is not None and hasattr(value, "__table__")
    except NoInspectionAvailable:
        return False


def _row_to_dict(row: Any) -> dict[str, Any]:
    state = sa_inspect(row)
    return {attr.key: getattr(row, attr.key) for attr in state.mapper.column_attrs}


def materialize(value: Any) -> Any:
    """Plain data for anything the encoder would otherwise read off a live session."""
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return value
    if _is_orm_instance(value):
        return _row_to_dict(value)
    if isinstance(value, Mapping):
        return {k: materialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [materialize(v) for v in value]
    return value


def materialized(handler: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """The same handler, returning plain data."""

    def _run(ctx):
        return materialize(handler(ctx))

    _run.__name__ = getattr(handler, "__name__", "handler")
    return _run
