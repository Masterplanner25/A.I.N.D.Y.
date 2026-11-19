---
title: "Runtime 2.38.0 adoption"
last_verified: "2026-11-18"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.38.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.38.0.md` (tag `v2.38.0`, #984). We come from 2.37.0, live since
2026-11-18 18:12:08Z. **One dependency move: SQLAlchemy 2.0.52 → 2.1.8 (DEC-134, #981).** **No schema step:** Alembic
stays `0022`, schema contract `2026-11-09`. No ui-kit or aindy-sdk release; no runtime route, scope or default changed.
No FR of ours moves (FR-14 and FR-70 were already closed here; FR-55 is now filed on the runtime's side).

Pin: `constraints.txt` `aindy-runtime==2.38.0`, floor `>=2.38.0,<3.0`, moved together
(`test_runtime_dependency_contract.py`). Nothing of ours pins SQLAlchemy; it reaches us through the runtime's exact pin.

## 1. Every engine we create names its driver

On SQLAlchemy 2.1 a bare `postgresql://` means psycopg 3, which nothing installs. The runtime's own engines rewrite
the URL themselves (`AINDY.config.normalize_database_url`, new in 2.38.0); ours did not. Unfixed, the container stops
at the entrypoint's first step, `scripts/ensure_pgvector.py`, with `No module named 'psycopg'`. **The fix ships in the
same PR as the pin**, since the helper does not exist on 2.37.0.

| Site | Change |
|---|---|
| `scripts/ensure_pgvector.py` (the entrypoint's first step) | `create_engine(normalize_database_url(url))` |
| `alembic/alembic/env.py` | `database_url` normalised where it is read, which covers `sqlalchemy.url` (offline) and `create_engine` (online) |
| `.github/workflows/deploy-bootstrap-guard.yml`, two inline checks | wrapped |
| `scripts/replay_app_migrations.py`, `check_schema_default_parity.py`, `audit_leadgen_fixtures.py`, `inventory.py --live` | wrapped |

`DATABASE_URL` itself is unchanged in compose, `.env` and the pytest ini files: the runtime's engine and every one of
ours now name psycopg2 from the bare URL. `tests/fixtures/db.py` and `scripts/deploy_bootstrap.py` use the runtime's
engine and needed nothing. There is no `psycopg2.connect(...)` (libpq, which must keep the bare URL) in our tree.

**Guard:** `tests/unit/test_database_url_driver.py` walks every `create_engine` call under `apps/`, `scripts/`,
`alembic/`, `tests/` and `docker/` with the AST and requires `normalize_database_url(...)` or a SQLite literal (an
f-string starting `sqlite` included), and line-scans `.github/workflows/*.yml` for inline engines.

## 2. The rest of SQLAlchemy 2.1

- **Autoflush before raw `text()` queries.** Our only raw reads are the `SELECT 1` health checks in five bootstraps,
  each on a fresh session; every other `text(...)` is a column default or a partial-index predicate. Nothing of ours
  reads through `text()` mid unit of work, so nothing changes.
- `str(engine.url)` escapes differently: we never build a connection string from a `URL` object.

## 3. Live

**Live 2026-11-19 05:22:14Z** on image `9dda5a6fdd63` (#627; a 4-minute build with `api` and `mcp` stopped). `/health`
200, `restarts=0`, postgres 0 reinitialisations.

| The handoff's report item | Result |
|---|---|
| Confirm line, from the container | `2.38.0 2.1.8 psycopg2 ['/usr/local/lib/python3.11/site-packages/AINDY']`, as expected |
| `alembic current` on the app line | `dt1directing0001 (head)`, through the normalised `env.py`; runtime line `0022` |
| `deploy-bootstrap-guard` on the adoption PR | **passed**: fresh Postgres, `ensure_pgvector.py`, both inline checks, migrations and `serve`, on SQLAlchemy 2.1.8 |
| The entrypoint's first step | `[ensure_pgvector] extension 'vector' already present`: the site that would have stopped the boot |

**Counters, the 2.37.0 window** (11-18 18:12:08Z → 11-19 05:18:35Z, read before the recreate): 0 identity mismatches,
0 `tenant_mismatch`, 59 gated effects (`reserved`). The 2.38.0 window opens at 05:22:14Z.

The directing hook's one post during the build failed (`URLError`, api down) and is picked up from the transcript tail
by the next prompt; nothing is lost.
