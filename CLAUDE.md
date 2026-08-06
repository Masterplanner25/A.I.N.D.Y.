# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Commands

```bash
# Install — published runtime (default; aindy-runtime is published on PyPI)
python -m pip install -e . --no-build-isolation   # resolves aindy-runtime>=1.10.2,<2.0 from PyPI

# Install — runtime from a sibling checkout (local paired-repo dev only)
python -m pip install -e ../aindy-runtime --no-deps --no-build-isolation
python -m pip install -e . --no-build-isolation

# Boot app-profile server (run from repo root so aindy_plugins.json is discovered)
aindy-runtime serve
AINDY_APP_PLUGIN_MANIFEST=./aindy_plugins.json aindy-runtime serve   # explicit manifest form

# App-profile test subset (no live server required)
pytest tests/unit/test_app_manifest_bootstrap_contract.py \
       tests/unit/test_import_boundaries.py \
       tests/unit/test_runtime_agent_api_ownership.py \
       tests/unit/test_tasks_public_contract.py \
       tests/unit/test_analytics_public_contract.py \
       tests/unit/test_app_model_registration.py \
       tests/test_bootstrap_completeness.py \
       -m app_profile -q

# Single test
pytest tests/unit/test_import_boundaries.py::test_name -v

# Cross-app import boundary check (required before any PR)
python scripts/check_app_imports.py

# API reference drift guard (boots app-profile, diffs live /apps/* vs the doc)
python scripts/check_api_reference.py

# App-profile smoke (mirrors CI — verifies boot_profile=default-apps, app_plugins_loaded=True)
python -c "
import os, json
os.environ.update({
    'DATABASE_URL': 'sqlite://', 'MONGO_URL': '', 'AINDY_ALLOW_SQLITE': '1',
    'OPENAI_API_KEY': 'sk-test-placeholder', 'DEEPSEEK_API_KEY': 'ds-test-placeholder',
    'SECRET_KEY': 'apps-integration-secret', 'AINDY_API_KEY': 'apps-integration-api-key',
    'PERMISSION_SECRET': 'apps-integration-permission-secret',
    'AINDY_SKIP_MONGO_PING': '1', 'SKIP_MONGO_PING': '1',
})
from fastapi.testclient import TestClient
import AINDY.main as main
payload = TestClient(main.app, raise_server_exceptions=False).get('/api/version').json()
print(json.dumps(payload['runtime'], sort_keys=True))
"
# Expected: boot_profile=default-apps, app_plugins_loaded=True, app_plugin_count=16
```

---

## Architecture

### Ownership

This repo owns:

- `apps/` — 16 domain app modules
- `client/` — React/Vite frontend
- `aindy_plugins.json` — app-owned plugin manifest
- `alembic/` — app-owned DB migrations
- app-profile tests and docs

It does **not** own `AINDY/`. Runtime code, runtime-only entrypoints, and runtime-only
docs live in `aindy-runtime` and are consumed as a published dependency.

### 16 domain apps

`tasks`, `analytics`, `arm`, `authorship`, `automation`, `autonomy`,
`dashboard`, `freelance`, `identity`, `masterplan`, `memory`, `network_bridge`,
`rippletrace`, `search`, `social`, `agent`

**Core domains** (`IS_CORE_DOMAIN = True`): `tasks`, `identity`, `analytics` — startup
fails if any of them fails to register.

All other domains are degradable peripherals — startup continues with a warning.

### Plugin registry pattern

The runtime exposes a registration surface. Apps call it at startup. The runtime never
imports `apps.*` directly.

Every domain app's `register()` function calls runtime-owned registration functions:

```python
# apps/<domain>/bootstrap.py

BOOTSTRAP_DEPENDS_ON: list[str] = ["identity"]  # boot-order hard deps — enforced at startup
APP_DEPENDS_ON: list[str] = []                   # cross-domain import declarations (AST-validated)
IS_CORE_DOMAIN: bool = False

def register() -> None:
    from AINDY.platform_layer.registry import (
        register_router, register_models, register_flow_definitions,
        register_scheduler_jobs, register_syscalls, register_agent_tools,
        register_event_handlers,
        # ...18 registration categories total
    )
    register_router(router, prefix="/api/myapp")
    register_models([MyModel])
    register_flow_definitions([my_flow_def])
    # ...
```

`apps/bootstrap.py` is the aggregator: it builds a dependency graph from all
`BOOTSTRAP_DEPENDS_ON` declarations and calls `register()` in topological order.

Full pattern documentation: `docs/architecture/PLUGIN_REGISTRY_PATTERN.md`

### Adding a new domain app

1. Create `apps/<newdomain>/` with a `bootstrap.py` declaring `BOOTSTRAP_DEPENDS_ON`,
   `APP_DEPENDS_ON`, `IS_CORE_DOMAIN`, and `register()`.
2. Add `"newdomain": "apps.newdomain.bootstrap"` to `APP_BOOTSTRAP_MODULES` in
   `apps/bootstrap.py`.
3. Run `python scripts/check_app_imports.py` — all cross-app imports must be declared.
4. Add tests under `tests/unit/test_newdomain_*.py` with `pytestmark = pytest.mark.app_profile`.

### Boot profiles

| Profile | Manifest | Plugins loaded |
|---|---|---|
| `platform-only` | `AINDY/runtime_plugins.json` | none |
| `default-apps` | `./aindy_plugins.json` | `apps.bootstrap` → 16 apps |

Running `aindy-runtime serve` from this repo root automatically selects `aindy_plugins.json`.
Set `AINDY_APP_PLUGIN_MANIFEST=./aindy_plugins.json` explicitly if the CWD is different.

---

## Import boundary rules

These are enforced by CI and must not be violated:

- `AINDY/` code must never import `apps.*` — validated by `test_import_boundaries.py`
- Apps may only import `AINDY.*` through declared public contracts
- Cross-app imports (`apps.tasks` importing from `apps.identity`) must be declared in
  `APP_DEPENDS_ON` in the importing app's `bootstrap.py` — enforced by
  `scripts/check_app_imports.py`

Violation consequence: the import scan exits non-zero and blocks CI.

---

## Alembic

App-owned migrations live in `alembic/alembic/versions/` (the repo-root
`alembic.ini` sets `script_location = alembic/alembic`). Runtime migrations live
in `aindy-runtime/alembic/`.

- The runtime uses the `alembic_version_runtime` table; apps use the standard
  `alembic_version` table.
- Run app migrations separately (`alembic upgrade head` from this repo root with
  `DATABASE_URL` pointing at the app database).
- All migrations must use `IF NOT EXISTS` / `IF EXISTS` guards — same idempotency
  rule as the runtime.

Full migration discipline (revision workflow, additive-only policy, integrity and
merge rules): `docs/deployment/MIGRATION_POLICY.md`.

---

## Runtime dependency contract

```toml
aindy-runtime>=1.0,<2.0
```

The upper bound is required. Never widen to an unbounded range.

For local dev against a sibling `aindy-runtime` checkout:

```bash
python -m pip install -e ../aindy-runtime --no-deps --no-build-isolation
```

`--no-deps` prevents pip from overwriting the runtime with a published version while
still making the editable source importable.

CI installs the published runtime from PyPI (the pinned `aindy-runtime>=1.10.2,<2.0`
dependency) and verifies the installed version at boot. `aindy-runtime` is
published (PYPI-PUBLISH-1 is closed); the sibling-checkout flow above is for local
paired-repo development only.

---

## Integration test patterns

### `run_flow()` return structure

`run_flow()` returns a uniform envelope: `{"status": "SUCCESS"|"error", "data": {...}, "run_id": ..., "trace_id": ..., ...}`. The handler's actual output is always nested under `"data"`. **Do not read output keys from the top-level result dict.**

```python
# CORRECT
result = run_flow("my_flow", payload, db=db, user_id=user_id)
data = result.get("data") or {}
message = data.get("message", "")  # flow output key lives here

# WRONG — output keys are never at the top level of result
message = result.get("message", "")
```

### `_fresh_main_app()` and `Base.metadata` — model import timing hazard

`_setup_postgres_schema` (session-scoped, autouse) calls `Base.metadata.create_all()` once at session start. Each test's `_fresh_main_app()` reloads `AINDY.main` + `AINDY.startup`, which imports all app modules and may add new model classes to `Base.metadata`. Tables registered this way exist in `Base.metadata` but **were never created in PostgreSQL** because `create_all` already ran.

`cleanup_committed_test_state` guards against this by querying `pg_catalog.pg_tables` before building the `TRUNCATE` list — only truncating tables that actually exist in the DB. **Do not simplify this back to iterating `Base.metadata.sorted_tables` directly.** Tables like `freelance_refund_records` (imported late via a freelance module reload) will raise `UndefinedTable`, which rolls back the cleanup transaction, leaves data in the DB, and cascades into isolation assertion failures and `InFailedSqlTransaction` errors across the rest of the session.

### Don't import `apps.*` at test-module scope — collection runs before bootstrap

A module-level `from apps.<domain>... import X` in a test file executes at pytest **collection**
time, ahead of every test, pulling that app's import chain in before the plugin bootstrap runs.
Registration-dependent state can then be missing for tests that expected bootstrap to establish
it — and the failure lands in a **different file that you did not touch**.

Observed: adding `tests/unit/test_arm_path_confinement.py` with a module-level
`apps.arm.services.deepseek` import made `test_reasoning_nodus_apply.py` fail. Its Nodus
workflow was no longer registered when it ran, so the VM path fell back and returned
`{'data': {}}`. Both files pass alone and in a pair; only the full suite shows it.

Import inside a fixture or inside the test instead. If a suite-wide failure appears in a file
your change never touched, check for a new `apps.*` import at another test module's top level
before hunting in the failing file.

### `AINDY_AGENT_PLANNER_BACKEND` in integration tests

Use `disabled` (set in `pytest.integration.ini`), **not** `stub`. The `stub` backend causes planner-path tests to fail with errors rather than cleanly skip when the planner isn't wired up. Tests that touch planner-dependent paths must check `os.environ.get("AINDY_AGENT_PLANNER_BACKEND") == "disabled"` and skip or fast-path accordingly.

### ARM config — per-user scoping

`arm_config.id` is a `String(36)` primary key. All rows are keyed by user UUID. All `arm_config_dao` calls must pass `user_id=str(current_user["sub"])`. A missing `user_id` falls back to the key `"default"` — the system default singleton, not per-user storage. The `String(36)` length is required to hold a UUID; `String(32)` is too short.

---

## Key file locations

| What | Where |
|---|---|
| Plugin manifest | `aindy_plugins.json` |
| Bootstrap aggregator | `apps/bootstrap.py` |
| Bootstrap validator (AST-based) | `apps/_bootstrap_validator.py` |
| Cross-app import checker | `scripts/check_app_imports.py` |
| API reference drift guard | `scripts/check_api_reference.py` |
| App-owned Alembic migrations | `alembic/alembic/versions/` |
| Migration policy | `docs/deployment/MIGRATION_POLICY.md` |
| Server deployment guide (+ enabling the Claude planner) | `docs/deployment/DEPLOYMENT.md` |
| Forward roadmap / track status | `docs/architecture/BUILD_PLAN.md` |
| Plugin registry pattern doc | `docs/architecture/PLUGIN_REGISTRY_PATTERN.md` |
| Boot profiles doc | `docs/architecture/BOOT_PROFILES.md` |
| Cross-domain coupling doc | `docs/architecture/CROSS_DOMAIN_COUPLING.md` |
| Runtime dependency contract doc | `docs/apps/RUNTIME_DEPENDENCY.md` |
| CI ownership doc | `docs/apps/CI_OWNERSHIP.md` |
| Tech debt tracker | `TECH_DEBT.md` |
| Live stack verification scope | `LIVE_VERIFICATION_SCOPE.md` |
