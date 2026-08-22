# Apps Repo Signoff

## Summary

- Date: 2026-05-17
- Operator: Codex
- Apps repo path: C:\dev\aindy-apps-monolith
- Runtime dependency path used for validation: C:\dev\aindy-runtime
- Installed runtime package version: 1.0.0
- Validated extraction commit: `7565ce937f56c59e57b331ae1a50ca9f50faa668`
- Working-tree state at signoff refresh: not clean; subsequent local CI,
  dependency-contract, and documentation edits exist outside the validated
  extraction commit

## Structure

- [x] `apps/` present
- [x] `client/` present
- [x] `alembic/` present
- [x] repo-root `aindy_plugins.json` present
- [x] local `AINDY/` source absent
- [x] runtime-only docs/CI/source absent from the repo root layout

Notes:
- Root contents after cut: `.github/`, `alembic/`, `apps/`, `client/`, `docs/`, `scripts/`, `tests/`, `.gitignore`, `aindy_plugins.json`, `alembic.ini`, `LICENSE`, `pyproject.toml`, `pytest.ini`, `README.md`.
- Confirmed absent: `AINDY/`, `routes/`, `docs/runtime/`, `.github/workflows/runtime-ci.yml`.

## Manifest And Dependency State

- [x] app manifest points to `apps.bootstrap`
- [x] default profile is `default-apps`
- [x] repo depends on installed `aindy-runtime`
- [x] no sibling-source dependency on local `AINDY/`
- [x] imports resolve against the installed runtime package
- [x] declared runtime dependency range is bounded and matches runtime
  compatibility guidance: `aindy-runtime>=1.0,<2.0`

Command(s) run:

```powershell
python -m pip install -e C:\dev\aindy-runtime --no-deps --no-build-isolation
python -m pip install -e .[test] --no-build-isolation
python -c "import importlib.util; spec=importlib.util.find_spec('AINDY'); print(list(spec.submodule_search_locations))"
```

Observed runtime import path:
- `C:\dev\aindy-runtime\AINDY`

Manifest payload:

```json
{
  "default_profile": "default-apps",
  "profiles": {
    "platform-only": { "plugins": [] },
    "default-apps": { "plugins": ["apps.bootstrap"] }
  }
}
```

## Boot

- [x] `apps.bootstrap` imports
- [x] `apps.bootstrap.bootstrap_models()` works
- [x] app-profile boot works against installed runtime
- [x] app routes mount
- [x] `/api/version` reports app-profile mode under `runtime`
- [x] app plugin count is non-zero

Command(s) run:

```powershell
python -c "import os; os.environ.update({'DATABASE_URL':'sqlite://','MONGO_URL':'','AINDY_ALLOW_SQLITE':'1','OPENAI_API_KEY':'sk-test-placeholder','DEEPSEEK_API_KEY':'ds-test-placeholder','SECRET_KEY':'apps-smoke-secret','AINDY_API_KEY':'apps-smoke-api-key','PERMISSION_SECRET':'apps-smoke-permission-secret','AINDY_SKIP_MONGO_PING':'1','SKIP_MONGO_PING':'1'}); import apps.bootstrap as b; b.bootstrap_models(); print('ok')"
python -c "import os, json; os.environ.update({'DATABASE_URL':'sqlite://','MONGO_URL':'','AINDY_ALLOW_SQLITE':'1','OPENAI_API_KEY':'sk-test-placeholder','DEEPSEEK_API_KEY':'ds-test-placeholder','SECRET_KEY':'apps-smoke-secret','AINDY_API_KEY':'apps-smoke-api-key','PERMISSION_SECRET':'apps-smoke-permission-secret','AINDY_SKIP_MONGO_PING':'1','SKIP_MONGO_PING':'1'}); from fastapi.testclient import TestClient; import AINDY.main as main; client=TestClient(main.app); print(json.dumps(client.get('/api/version').json(), indent=2, sort_keys=True))"
```

Observed `/api/version` runtime payload:
- `boot_mode: app-profile`
- `boot_profile: default-apps`
- `boot_profile_source: default_profile`
- `app_plugins_loaded: true`
- `app_plugin_count: 16`

Additional smoke observations:
- `len(AINDY.platform_layer.registry.get_registered_apps()) == 16`
- `AINDY.platform_layer.registry.get_job('tasks.background.start')` resolved
- `AINDY.platform_layer.registry.get_job('analytics.kpi_snapshot')` resolved
- `/apps/identity/boot` route mounted

## Test Results

- [x] representative app-profile tests passed
- [x] cross-app import boundary check passed

Command(s) run:

```powershell
python -m pytest tests/test_bootstrap_completeness.py tests/unit/test_runtime_agent_api_ownership.py tests/unit/test_app_manifest_bootstrap_contract.py tests/unit/test_app_model_registration.py tests/unit/test_tasks_public_contract.py tests/unit/test_analytics_public_contract.py tests/unit/test_import_boundaries.py -m app_profile -q
python scripts/check_app_imports.py
```

Result:
- Passed: 55
- Failed: 0
- Skipped: 0
- Cross-app import boundary: `33 declared, 0 undeclared`

Validation basis:
- this signoff records the validated extraction baseline at commit
  `7565ce937f56c59e57b331ae1a50ca9f50faa668`
- later local changes in the apps repo were not part of the original repo-cut
  validation run and should be validated separately before a new signoff is cut

## Remaining Cautions

- Bootstrap emits accepted `APP_DEPENDS_ON` ordering-gap warnings for `analytics -> identity` and `masterplan -> identity`.
- `apps.freelance.bootstrap` warns when `STRIPE_WEBHOOK_SECRET` is unset.
- Runtime import/startup still requires the documented minimal env (`DATABASE_URL`, secrets, provider keys).
- Runtime warning still present from installed runtime: `NodusFlowRequest.register` shadows a `BaseModel` attribute.

## Decision

- [x] Go with caution

Decision notes:
- The apps repo cut is operationally valid. It boots in app-profile mode against the installed `aindy-runtime` package, retains app-owned content, and does not rely on a local runtime source tree.
