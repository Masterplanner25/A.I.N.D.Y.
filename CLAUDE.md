# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Commands

```bash
# Install — published runtime (default; aindy-runtime is published on PyPI)
python -m pip install -e . --no-build-isolation   # resolves aindy-runtime[mcp,security]>=2.36.0,<3.0 from PyPI

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

# Cross-app import boundary check (required before any PR)
python scripts/check_app_imports.py

# API reference drift guard (boots app-profile, diffs live /apps/* vs the doc)
python scripts/check_api_reference.py

# Inventory: what exists, read from the registries (docs/verification/INVENTORY.md). CI runs --check.
# A route or registration change means rerun it and commit; a client API change means
# `UPDATE_CLIENT_ROUTES=1 npx vitest run client-routes-manifest` first (the "called by the client" column).
python scripts/inventory.py
AINDY_INVENTORY_DATABASE_URL=<real db url> python scripts/inventory.py --live   # rows per table, for the audit

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

# Local stack — BOTH compose files AND all THREE profiles, every up/down (see the trap below).
# `public-mcp` (since 2026-11-11) is the read-only MCP server for claude.ai and ChatGPT and its ngrok tunnel;
# drop it to keep the stack private, but then stop `mcp-tunnel mcp` explicitly, since an up/down without the
# profile leaves them running.
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml --profile full --profile mail --profile public-mcp up -d
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml --profile full --profile mail --profile public-mcp build api   # after a merge you want live (`mcp` shares the image; recreate both)
# A source-only change rebuilds in ~a minute; a pin move takes 10-15 min. Slower: OPERATOR_NOTES OPS-004.

# Schema-default parity guard, locally (what CI Step 6 does): migrate a scratch DB FROM EMPTY
# inside the api image, then diff models vs. migrations. PYTHONPATH is load-bearing —
# `pip install .` in the image is non-editable, so without it you audit site-packages' copy.
docker exec <postgres> psql -U aindy -d aindy -c "create database parity_scratch"
docker exec <postgres> psql -U aindy -d parity_scratch -c "create extension if not exists vector"
MSYS_NO_PATHCONV=1 docker run --rm --network aindy-apps-monolith_default -v "$(pwd -W):/src:ro" -w /src \
  -e DATABASE_URL=postgresql+psycopg2://aindy:aindy@postgres:5432/parity_scratch -e PYTHONPATH=/src \
  --entrypoint sh aindy-apps-monolith-api:latest -c 'alembic upgrade head >/tmp/up.log 2>&1; python scripts/check_schema_default_parity.py'
docker exec <postgres> psql -U aindy -d aindy -c "drop database parity_scratch"
```

**`--profile full` is not optional on this stack:** without redis every rate-limited route 500s, `/health` included,
while `/api/version` looks fine (OPS-001, `COMPOSE-REDIS-URL-UNCONDITIONAL-1`).

---

## Architecture

### Ownership

This repo owns:

- `apps/` — A.I.N.D.Y.'s 16 domains, one module each
- `client/` — React/Vite frontend
- `aindy_plugins.json` — app-owned plugin manifest
- `alembic/` — app-owned DB migrations
- app-profile tests and docs

It does **not** own `AINDY/`. Runtime code, runtime-only entrypoints, and runtime-only
docs live in `aindy-runtime` and are consumed as a published dependency.

### 16 domains (one platform)

**A.I.N.D.Y. is one app with 16 domains, not 16 apps** (owner, 2026-09-28). The code calls each
`apps/<domain>/` module a "domain app" and the plugin machinery treats each as a unit, but that
is packaging. Product-facing wording says domains.

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
        register_scheduled_job, register_event_handler,
        register_run_tool_provider,
        # ...about 40 `register_*` functions: check names in AINDY/platform_layer/registry.py,
        # never from a doc (OPS-025)
    )
    # SYSCALLS come from the kernel, not from here (platform_layer's register_syscall is a dead end, OPS-024):
    #   from AINDY.kernel.syscall_registry import SyscallContext, register_syscall
    # Count registrations by booting, or read the generated docs/verification/INVENTORY.md; never trust a written number.
    #
    # AGENT TOOLS: `register_run_tool_provider` (a callable returning the tool list), never
    # `register_agent_tool`. The planner sees one line per tool: `- name: description (risk=…) args={…}`.
    # - Every tool declares `args_schema={"required": [...], "properties": {k: {"type": ...}}}`
    #   (`test_agent_tool_args_schema.py`; without one the planner guesses the keys, OPS-027). Types are the
    #   dispatcher's dialect (`syscall_versioning._SCHEMA_TYPE_MAP`): "number" means float ONLY, so leave an
    #   int-or-float property untyped.
    # - This stack runs `AINDY_TOOL_ARGS_VALIDATION=enforce` (compose, since 2026-09-26): a schema mismatch
    #   refuses the step, so a new tool's schema must be right before it ships. It checks shape, not truth.
    # - Every tool a later step may reference declares `result_schema`, all in `apps/_shared/tool_results.py`,
    #   checked at plan time. A schema listing `properties` is CLOSED: declare the tool's REAL keys
    #   (`test_agent_tool_result_schema.py`).
    #
    # THREE JOB MECHANISMS (confusing them shipped a wrong remedy, OPS-026):
    #   register_scheduled_job  - registry            - APScheduler, runs on an interval
    #   register_job            - registry            - a SYNCHRONOUS callable, looked up later via
    #                                                   get_job("name"); registering does NOT make it async
    #   register_async_job      - NOT in the registry - background dispatch, in
    #                             AINDY.platform_layer.async_job_service; check the module doing the
    #                             slow work uses it, not just the domain
    register_router(router, prefix="/api/myapp")
    register_models([MyModel])
    register_flow_definitions([my_flow_def])
    # ...
```

`apps/bootstrap.py` is the aggregator: it builds a dependency graph from all
`BOOTSTRAP_DEPENDS_ON` declarations and calls `register()` in topological order.

Full pattern documentation: `docs/architecture/PLUGIN_REGISTRY_PATTERN.md`

### New workflows are written in Nodus (`.nd`)

**Owner, 2026-10-22: a new workflow goes in `apps/<domain>/nodus/<name>.nd`, not in a new Python flow graph.**
Existing Python flows stay until one is deliberately ported. Before writing or changing a `.nd` workflow, load the
`nodus-workflows` skill (`.claude/skills/nodus-workflows/SKILL.md`): the pattern, the fallback rule, the capability
trap, the register-twice handler trap, packaging, and FR-55's limits are there.

### Adding a new domain app

1. Create `apps/<newdomain>/` with a `bootstrap.py` declaring `BOOTSTRAP_DEPENDS_ON`,
   `APP_DEPENDS_ON`, `IS_CORE_DOMAIN`, and `register()`.
2. Add `"newdomain": "apps.newdomain.bootstrap"` to `APP_BOOTSTRAP_MODULES` in
   `apps/bootstrap.py`.
3. Run `python scripts/check_app_imports.py` — all cross-app imports must be declared.
4. Add tests under `tests/unit/test_newdomain_*.py` with `pytestmark = pytest.mark.app_profile`.

### Boot profiles

`platform-only` loads no plugins; `default-apps` loads `./aindy_plugins.json` (16 domains). `aindy-runtime serve` from
the repo root picks `default-apps`; elsewhere set `AINDY_APP_PLUGIN_MANIFEST`. Details: `docs/architecture/BOOT_PROFILES.md`.

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
merge rules): `docs/operations/MIGRATION_POLICY.md`.

---

## Runtime dependency contract

```toml
aindy-runtime[mcp,security]>=2.36.0,<3.0    # pyproject.toml — the COMPATIBILITY range
```
```
aindy-runtime==2.36.0         # constraints.txt — the BUILD pin
```

The upper bound is required. Never widen to an unbounded range.

**`[mcp]` (since #468)** brings `nodus-mcp` and the MCP SDK for `scripts/mcp_server.py`. The runtime
owns their bounds; the extra inherits them, so there is nothing of ours to pin. The contract test
reads the specifier, not the extras, so the extra does not change the pin rule below.

**Two files, two jobs, and they must move together.** The range says what this app is
compatible with; the pin says what it is actually built and tested against. Builds install
with `-c constraints.txt` — the Dockerfile and all five CI workflows — so an image stops
depending on the date it was built (`RUNTIME-PIN-FLOAT-1`).

This matters more than ordinary hygiene because `docker/entrypoint.sh` has `aindy-runtime
serve` **self-migrate the runtime schema at boot**: an unintended version bump is an
unintended, irreversible database migration, discovered by the container on start.

**Raising the floor and the pin is one act, not two.**
`tests/unit/test_runtime_dependency_contract.py` asserts they are equal — not merely
compatible — so a floor raised during an adoption pass while the pin is forgotten fails there
instead of silently shipping an unadopted runtime.

For local dev against a sibling `aindy-runtime` checkout — this path deliberately does **not**
use `constraints.txt`, since the editable install is the whole point and a pin would defeat it:

```bash
python -m pip install -e ../aindy-runtime --no-deps --no-build-isolation
```

`--no-deps` prevents pip from overwriting the runtime with a published version while
still making the editable source importable.

CI installs the published runtime from PyPI (the pinned `aindy-runtime[mcp,security]>=2.36.0,<3.0`
dependency) and verifies the installed version at boot. `aindy-runtime` is
published (PYPI-PUBLISH-1 is closed); the sibling-checkout flow above is for local
paired-repo development only.

---

## Integration test patterns

### `run_flow()` return structure

`run_flow()` returns a uniform envelope: `{"status": ..., "data": {...}, "run_id": ..., "trace_id": ..., ...}`. The handler's actual output is always nested under `"data"`. **Do not read output keys from the top-level result dict.**

```python
# CORRECT
result = run_flow("my_flow", payload, db=db, user_id=user_id)
data = result.get("data") or {}
message = data.get("message", "")  # flow output key lives here

# WRONG — output keys are never at the top level of result
message = result.get("message", "")
```

**`status` is one of `SUCCESS` | `FAILED` | `SKIPPED` | `WAITING` — all uppercase. It is
never `"error"`** (OPS-028).

```python
# WRONG — never matches, so a FAILED flow falls through to the success path
if result.get("status") == "error":
    raise RuntimeError(...)

# CORRECT
if result.get("status") != "SUCCESS":
    ...
```

Two things this does NOT mean:

- **It is not the syscall envelope.** A syscall response is lowercase and, since runtime
  2.9.0, is `success` | `partial` | `unknown` | `error` — test those with `!= "success"`.
  `run_flow` dispatches `sys.v1.flow.run` internally and **raises** if that syscall fails,
  so a syscall-level failure reaches you as an exception, not as a status.
- **Do not mechanically rewrite one into the other.** The two envelopes coexist inside the
  same functions: a flow node reads a lowercase syscall status and returns an uppercase flow
  status two lines later (see `_syscall_node` in `apps/*/flows/`).

**Do not hand-write this check.** Use `run_flow_or_raise` / `run_flow_data` from
`apps/_shared/flow.py`; every route that runs a flow goes through it. The helper also maps a
node's `HTTP_<code>:<msg>` error onto that status code, which a hand-written check will not.

**A pipeline `route_name` is at most 32 characters** (`system_events.source`); a longer one is never recorded
(OPS-029). `test_route_names_fit_event_source.py` checks every call site.

**An adapter whose body carries `data` must be wrapped in `stamped(...)`** (`apps/_shared/envelope.py`).
ui-kit ≥ 2.1.0 unwraps only a response carrying `X-AINDY-Envelope`, and once it has seen one it
leaves every unstamped body alone, so an unstamped envelope reaches the component whole. The
runtime's own `raw_canonical_adapter` / `legacy_envelope_adapter` do not stamp (FR-45).
`test_response_adapters_stamp_envelopes.py` checks every adapter we register. The client has no
`unwrapEnvelope` calls any more. Do not add one: stamp the server side.

**A pipeline handler returns data, not ORM rows, and every call passes `metadata={"db": db}`.**
The pipeline commits after the handler, which empties loaded rows, so returned rows serialise as `{}` (OPS-030).
Where a service still hands back rows, wrap the handler: `materialized(handler)` from
`apps/_shared/serialization.py`. `test_pipeline_routes_pass_session.py` guards the session;
`test_handler_returns_data_not_rows.py` guards RippleTrace's wrapping.

### Where the rest lives: nested CLAUDE.md files and skills

These load only when you work in the matching folder. Read the one a task touches before starting:
- `tests/CLAUDE.md`: `_fresh_main_app` and `Base.metadata`; why `test_real_vm_run_routes_through_nodus` fails under
  load or without `pip install -e .[test]`; `AINDY_AGENT_PLANNER_BACKEND=disabled` in integration tests.
- `apps/agent/CLAUDE.md`: agent tool steps run on `nodus_vm` in the worker: metering, the authority gate, FR-44,
  durable continuation and the check after every api restart.
- `apps/arm/CLAUDE.md`: ARM config is keyed per user, and ARM's model names must be DeepSeek's.
- `apps/masterplan/CLAUDE.md`: what `content.draft` is given, and its model.
- `scripts/CLAUDE.md`: the MCP launcher (exposure rules, probing) and how the watcher runs.

Skills: `live-probe` (probing the running container: tokens, admin promotion, `/platform/syscall`), `api-hang-triage`
(the api wedges), `nodus-workflows`.

### Another AI reading A.I.N.D.Y. — MCP

Claude Code is connected to MCP server `aindy` (local scope), read-only as the owner. **Use its `work_context`,
`work_facts` and memory reads for the owner's Work facts instead of asking for a paste.** The api container must be
up. Owner, 2026-10-14: other AIs are *access* to the Infinity Algorithm's state, never a second product. Launcher,
exposure rules and probing: `scripts/CLAUDE.md`. **claude.ai and ChatGPT read it too, since 2026-11-11** (owner): the
same seven reads over OAuth at `$AINDY_MCP_PUBLIC_URL/mcp`, compose profile `public-mcp`. That tunnel is the only public
path; the api stays on `127.0.0.1`.

### Every paid call names the user whose key pays (FR-59)

**A model or search call goes through `apps/_shared/provider_keys.py`, never `get_openai_client()` or a provider key
from the environment.** `llm_client(user_id, provider)` for a model client, `provider_key(user_id, provider)` for a raw
HTTP call (then `refused(resolved, status)`). The user is required: a missing one is a `ValueError`, because the runtime
pays a call with no user with the server's key. Only the operator's own calls pass `system=True`.

- **A key problem is a 402 with a sentence** (`ProviderKeyProblem`). A site that catches every model error and falls
  back must call `raise_key_problem(exc)` first, or a missing key becomes a quietly worse result.
- **A route whose paid call runs inside a flow or syscall calls `require_key(...)` before it starts**: a raise inside a
  flow's syscall loses the message (FR-64).
- **A scheduled job asks `can_pay(user_id, provider)` before a user's work** and skips them; their work stays due.
- **This stack runs `AINDY_PROVIDER_KEYS=per_user` since 2026-11-08** (compose; the master key is in `.env`, and
  startup refuses per_user without it). The owner is the only operator and stays on the server's keys; any other
  account pays with its own key from Settings or gets the 402.
  `test_provider_key_routing.py` fails on a new direct client or key read; add each new site to its per-site list.

---

## When something fails

**Before troubleshooting an unfamiliar failure, read `docs/operations/OPERATOR_NOTES.md`:** each `OPS-` entry starts
with when it applies (`grep -n -A1 "^### OPS-" docs/operations/OPERATOR_NOTES.md`). When you resolve a new failure that
could recur, add an entry there, not here; the file says how, and when one becomes a rule.

**The API hangs:** `[Scheduler] job 'scheduler_wait_tick' skipped a run (max_instances)` names the victim, never the
culprit. Before reading application code, load the `api-hang-triage` skill and check, cheapest first, postgres
reinitialisations, host paging and boot progress. `/health` 500 with `/api/version` 200 is redis missing (OPS-001).

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
| Migration policy | `docs/operations/MIGRATION_POLICY.md` |
| Server deployment guide (+ enabling the Claude planner) | `docs/operations/DEPLOYMENT.md` |
| Forward roadmap / track status | `docs/architecture/BUILD_PLAN.md` |
| Plugin registry pattern doc | `docs/architecture/PLUGIN_REGISTRY_PATTERN.md` |
| Boot profiles doc | `docs/architecture/BOOT_PROFILES.md` |
| Cross-domain coupling doc | `docs/architecture/CROSS_DOMAIN_COUPLING.md` |
| Runtime dependency contract doc | `docs/runtime/RUNTIME_DEPENDENCY.md` |
| CI ownership doc | `docs/operations/CI_OWNERSHIP.md` |
| Strategy layer (objectives / phases / strategies) | `docs/specs/STRATEGY_LAYER_SPEC.md` — built through §8 step 3b(v) as of 2026-09-16 (phase advance, pace and strategy-conclude proposals; attainment shadow recorded, not flipped) |
| Runtime feature requests (passbacks to the runtime side, ui-kit included) | `docs/runtime/RUNTIME_FEATURE_REQUESTS.md`: numbering is the runtime's; `test_fr_register_headings.py` guards the headings; the top block says what is open. **Count `job_logs`, not `automation_logs`** (FR-56) |
| Latest runtime adoption record | `docs/runtime/RUNTIME_2_36_0_UPGRADE.md`; one `RUNTIME_<version>_UPGRADE.md` per release, each saying what changed, what we did, and whether there was a schema step. 2.22.0's §2: a column WIDENING is invisible to `bootstrap-schema` (FR-43); check the column, not the exit code |
| Compose memory bounds (api cap, no swap, guest ceiling) | `docker-compose.prod.yml` api service; guarded by `tests/unit/test_compose_memory_bounds.py` |
| Work model (Works, links, presence, drafts) | `docs/specs/WORK_MODEL_SPEC.md` |
| Resolution Check (does AI search resolve the owner's entities) | `docs/specs/RESOLUTION_CHECK_SPEC.md`: phases A–C built; `listed` is a verdict (§7.4); the score stays unwired (decision 5) |
| Release handoff (A.I.N.D.Y. carries a runtime release past the approval gate) | `docs/specs/RELEASE_HANDOFF_SPEC.md`: **phase 1 built 2026-10-14** (§7.1; the watcher `release_handoff_watch`, `/apps/releases`, the Collaborator card); needs `AINDY_GITHUB_TOKEN` and real SMTP in `.env`; first real use 2.28.0. **Phase 3a built 2026-10-24**: Approve/Reject on the card (`POST /apps/releases/{id}/approve|reject`), only with a second token `AINDY_GITHUB_APPROVE_TOKEN` (Deployments: write) that nothing else sends; **never an MCP approve tool** (owner). **3b built the same day**: reply APPROVE/REJECT to the gate email (`release_reply.py`; the watcher reads the SMTP account's **Sent Mail** over IMAP, never the inbox, so a forged `From` cannot decide) |
| Operator notes (the repo's working experience: `OPS-` entries, symptom → cause → fix) | `docs/operations/OPERATOR_NOTES.md` — durable lessons go here, never into the gitignored `SESSION_HANDOFF.md` or into this file |
| Inventory (what exists, generated) | `docs/verification/INVENTORY.md` from `scripts/inventory.py`; client calls from `docs/verification/client_routes.json` (`client/src/test/client-routes-manifest.test.js`). The audit (after the ~10-29 rebuild) judges what it lists |
| MCP launcher (another AI reads A.I.N.D.Y.) | `scripts/mcp_server.py`; guarded by `tests/unit/test_mcp_read_access.py` |
| Tech debt tracker | `TECH_DEBT.md` |
| Live stack verification scope | `LIVE_VERIFICATION_SCOPE.md` |
