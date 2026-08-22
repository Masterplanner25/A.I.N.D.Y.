---
title: "Archived — CI and test-infrastructure gap report (2026-05-25)"
last_verified: "2026-08-22"
api_version: "1.0"
status: outdated
owner: "app-team"
---

# Archived: CI and test-infrastructure gap report

**Written 2026-05-25. Archived 2026-08-22 — kept for provenance, not for action.**

This was a gap report comparing the freshly-split apps repo against the pre-split archive's CI and
test setup. It was accurate when written and it drove real work: most of what it asked for now
exists. It is archived rather than deleted because its ranked list is a useful record of what the
split actually cost, and of what was deliberately *not* carried over.

## Audit of its 14 ranked recommendations (2026-08-22)

**Eleven are done.** `pytest-env` is in the test extras; ruff runs in CI (`App Lint`);
`tests/integration/` exists with 16 files (the repo now has **95 test files**, against the 8 this
report counted); `pytest.integration.ini` and `pytest.postgres.ini` both exist; the `redis` and
`multi_instance` markers are in `pytest.ini` (plus `integration`); `docker-compose.test.yml` and
`.env.example` exist; `validate-env.js` runs as part of the build script; five CI jobs carry
`timeout-minutes`; and **all 10 action references are SHA-pinned**.

**One was superseded by a better design.** The report asked for `alembic upgrade head` +
`alembic check` against real Postgres. That prescription is wrong on a fresh database — a bare
`upgrade head` replays the pre-split revisions and drifts the runtime-owned tables, which is the
exact failure `APP-DEPLOY-1` fixed. What exists instead is `deploy-bootstrap-guard.yml`, which
mirrors `docker/entrypoint.sh` against a real pgvector service on any PR touching `alembic/**`.

**Two remain open, and are now tracked properly** in `TECH_DEBT.md` as
**`TEST-INFRA-GAPS-1`** — coverage is never invoked, and there is no E2E job. A third, narrower gap
was found during this audit and is tracked in the same item: **no CI anywhere runs
`alembic upgrade head`**, so the 154 app-owned revisions are never replayed against an existing
database, which is precisely what a real deployment does.

Do not action anything below without re-checking it first — the state it describes is three months
stale.

---

## Original report, verbatim

```
 I have the full picture. Here is the gap report for C:\dev\aindy-apps-monolith.

  ---
  CI Workflows in aindy-apps-monolith (current)

  .github/workflows/app-ci.yml

  Triggers: push/PR to main, workflow_dispatch

  ┌──────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │       Job        │                                                           What it does                                                            │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ app-docs         │ scripts/lint_docs.py + scripts/check_api_contracts.py (20-min timeout)                                                            │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ app-contracts    │ 4-way conditional runtime checkout from source; installs runtime + app deps; smoke /api/version in app-profile mode;              │
  │                  │ scripts/check_app_imports.py; bootstrap dep validator; pytest tests -m app_profile -q (45-min timeout, SQLite only)               │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ frontend-quality │ npm ci && npm test from client/ (no timeout)                                                                                      │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ frontend-build   │ npm run build + docker build on client Dockerfile — depends on frontend-quality (no timeout)                                      │
  └──────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  No other workflows. No release, no staging, no postgres, no integration, no coverage, no lint.

  ---
  Workflows Present in Archive but Missing from aindy-apps-monolith

  ┌─────────────────────────────────┬────────────────────────────────────────────┬──────────────────────────────────────────────────────────────────────┐
  │       Archive job / step        │                What it did                 │                      Relevant to apps monolith?                      │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ lint — ruff check AINDY/        │ Catches style and import errors on every   │ Yes — app-ci.yml has no linter at all; apps/ has ~60 Python modules  │
  │                                 │ push                                       │ with zero ruff enforcement in CI                                     │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ test — Postgres + Redis + Mongo │ Real backend for integration and           │ Yes — apps monolith owns migrations, domain models, and cross-domain │
  │  service containers             │ postgres-mode tests                        │  flows that require real Postgres                                    │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ test — alembic upgrade head +   │ Verifies all 130+ migrations apply cleanly │ Critical — apps monolith owns the Alembic migration history          │
  │ alembic check                   │  against real Postgres                     │ entirely; a broken migration cannot be caught by SQLite              │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ test-postgres — pytest -c       │ Full run on pgvector:pg15 (port 5433) for  │ Yes — postgres marker is defined in pytest.ini but there is no       │
  │ pytest.postgres.ini             │ FK cascades, JSONB, UUID behavior          │ Postgres container in any workflow to exercise it                    │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ test — --cov=AINDY --cov=apps   │ Coverage enforcement and regression        │ Yes — pytest-cov==7.0.0 is listed in pyproject.toml test deps but is │
  │ --cov-fail-under=68             │ detection                                  │  never invoked; coverage tracking is completely absent               │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ test — Codecov upload           │ Trending and badge                         │ Yes — falls out of coverage enforcement above                        │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ test — coverage omit guard      │ Prevents forbidden production paths from   │ Yes — no .coveragerc exists at all in the apps monolith              │
  │                                 │ being omitted from .coveragerc             │                                                                      │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ test — pytest.integration.ini   │ Domain integration tests against real      │ Yes — domain-specific tests (arm, analytics, genesis, memory bridge, │
  │ suite (30 tests)                │ Postgres/Redis/Mongo                       │  leadgen, data ownership, social scoring, calculation services,      │
  │                                 │                                            │ execution contract) all belong in the apps monolith                  │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ frontend-e2e — Playwright       │ npm run test:e2e with artifact upload on   │ Yes — apps monolith owns client/; app-ci.yml has unit tests and a    │
  │ Chromium E2E                    │ failure                                    │ build smoke but no E2E                                               │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ frontend-test — node            │ Verifies the build env script (catches     │ Yes — frontend-build runs npm run build but not the dedicated        │
  │ scripts/validate-env.js         │ missing/invalid VITE_* vars before deploy) │ env-validation step                                                  │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │                                 │ Local test services (Postgres 5433, Redis  │                                                                      │
  │ docker-compose.test.yml         │ 6380, Mongo 27017) for developer           │ Yes — apps monolith has no docker-compose*.yml of any kind           │
  │                                 │ integration testing                        │                                                                      │
  ├─────────────────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────┤
  │ .env.example                    │ Documents all required env vars for local  │ Yes — no .env.example exists in the apps monolith                    │
  │                                 │ setup                                      │                                                                      │
  └─────────────────────────────────┴────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────────┘

  ---
  Specific Gaps in Test Infrastructure

  pytest.ini — missing markers

  The archive had four markers; the apps monolith has two:

  ┌────────────────┬─────────┬────────────────────────────────────────────────────────────┐
  │     Marker     │ Archive │                    aindy-apps-monolith                     │
  ├────────────────┼─────────┼────────────────────────────────────────────────────────────┤
  │ app_profile    │ Yes     │ Yes                                                        │
  ├────────────────┼─────────┼────────────────────────────────────────────────────────────┤
  │ postgres       │ Yes     │ Yes (defined, but never exercised — no Postgres container) │
  ├────────────────┼─────────┼────────────────────────────────────────────────────────────┤
  │ redis          │ Yes     │ Missing                                                    │
  ├────────────────┼─────────┼────────────────────────────────────────────────────────────┤
  │ multi_instance │ Yes     │ Missing                                                    │
  ├────────────────┼─────────┼────────────────────────────────────────────────────────────┤
  │ runtime_only   │ Yes     │ Correctly absent — apps repo doesn't own runtime           │
  └────────────────┴─────────┴────────────────────────────────────────────────────────────┘

  pytest-env — silent no-op

  pytest.ini declares an env = block (e.g. DATABASE_URL=sqlite:///:memory:). This block requires the pytest-env plugin to take effect. The archive had
  pytest-env in AINDY/requirements.txt. The apps monolith pyproject.toml [project.optional-dependencies].test lists only:

  pytest==9.0.2
  pytest-asyncio==1.3.0
  pytest-cov==7.0.0
  pytest-mock==3.15.1

  pytest-env is absent. The env = block in pytest.ini is silently ignored unless someone has pytest-env installed from an unrelated path. This means the
  DATABASE_URL, AINDY_ALLOW_SQLITE, and all other env settings declared there have no effect in a clean install — the conftest os.environ.setdefault() calls
   are the only thing keeping tests from crashing, and they are less explicit than the ini-declared defaults.

  Test file count — severe gap

  The archive's tests/integration/ had 30 files. The apps monolith has 8 test files total:

  tests/test_bootstrap_completeness.py
  tests/unit/test_analytics_public_contract.py
  tests/unit/test_app_manifest_bootstrap_contract.py
  tests/unit/test_app_model_registration.py
  tests/unit/test_import_boundaries.py
  tests/unit/test_runtime_agent_api_ownership.py
  tests/unit/test_runtime_dependency_contract.py
  tests/unit/test_tasks_public_contract.py

  These are exclusively structural contracts (import boundaries, manifest shape, public API shape). There are zero domain behavior tests — no analytics
  calculation tests, no arm tests, no genesis flow tests, no task service tests, no memory bridge behavior tests. The archive had all of these in
  tests/integration/.

  No tests/integration/ directory

  There is no tests/integration/ directory. The archive domain-specific integration tests that should be ported into the apps monolith:

  ┌────────────────────────────────────────┬───────────────────────────────────────────┐
  │              Archive file              │               Domain owner                │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_arm.py                            │ apps.arm                                  │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_calculation_services.py           │ apps.analytics                            │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_data_ownership.py                 │ apps.tasks / multi-domain                 │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_execution_contract.py             │ Joint — execution pipeline via app routes │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_genesis_flow.py                   │ apps.masterplan                           │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_leadgen_search_integration.py     │ apps.search                               │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_memory_bridge.py + v1–v5 variants │ apps.memory / AINDY.memory                │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_memory_embedding_pipeline_e2e.py  │ apps.memory                               │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_social_scoring.py                 │ apps.analytics / social                   │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_external_call_service.py          │ apps.freelance                            │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_async_embedding_pipeline.py       │ apps.memory                               │
  ├────────────────────────────────────────┼───────────────────────────────────────────┤
  │ test_research_query_live_summary.py    │ apps.search                               │
  └────────────────────────────────────────┴───────────────────────────────────────────┘

  The runtime-owned ones (test_migrations.py, test_redis_queue.py, test_request_context.py, test_multi_instance_resume.py, test_platform_quickstart.py,
  test_system_event_persistence.py) belong in aindy-runtime as noted in the previous report — not here.

  ---
  GitHub Config Gaps

  ┌─────────────────┬─────────────────────────────────────┬──────────────────────────────────────────────┬─────────────────────────────────────────────┐
  │      Item       │               Archive               │             aindy-apps-monolith              │                     Gap                     │
  ├─────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │ CODEOWNERS      │ Present                             │ Present — covers all major paths including   │ No gap — apps monolith CODEOWNERS is        │
  │                 │                                     │ /alembic/, /client/, /aindy_plugins.json     │ well-scoped                                 │
  ├─────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │                 │ Sprint/Issue, 453+ test count, 64%  │                                              │ Partial — apps template is correctly        │
  │ PR template     │ coverage floor, ruff, alembic,      │ App-scope checklist (runtime dep review,     │ reframed, but has no coverage floor         │
  │                 │ CHANGELOG/TECH_DEBT checklist       │ migration review, frontend/build review)     │ statement and no test count expectation;    │
  │                 │                                     │                                              │ add both once coverage is wired             │
  ├─────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │                 │ 8 required secrets + CODECOV_TOKEN  │ Present, well-written — correctly identifies │                                             │
  │ SECRETS.md      │ optional                            │  AINDY_RUNTIME_CHECKOUT_TOKEN as the only    │ No gap                                      │
  │                 │                                     │ optional CI secret                           │                                             │
  ├─────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │ Dependabot      │ Absent                              │ Absent                                       │ No gap                                      │
  ├─────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │ Issue templates │ Absent                              │ Absent                                       │ No gap                                      │
  ├─────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │ Action SHA      │                                     │                                              │ Both lag aindy-runtime which pins to commit │
  │ pinning         │ Not pinned (@v4 tags)               │ Not pinned (@v4 tags)                        │  SHAs — supply-chain risk; port             │
  │                 │                                     │                                              │ aindy-runtime's pinning style here          │
  ├─────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼─────────────────────────────────────────────┤
  │ Job             │                                     │ Set on app-docs (20 min) and app-contracts   │ A hanging npm install or frozen Docker      │
  │ timeout-minutes │ Set on all Python jobs              │ (45 min); absent on frontend-quality and     │ build will consume the entire Actions       │
  │                 │                                     │ frontend-build                               │ budget with no bound                        │
  └─────────────────┴─────────────────────────────────────┴──────────────────────────────────────────────┴─────────────────────────────────────────────┘

  ---
  Recommended Carry-Over Items — Ranked

  1. pytest-env in pyproject.toml — Lowest-effort, highest-correctness fix. Add pytest-env to [project.optional-dependencies].test. Without it the env =
  block in pytest.ini is inert and tests rely solely on conftest.py setdefault() calls, which is a hidden fragility.
  2. Ruff lint job — Add a lint job to app-ci.yml scoped to apps/ tests/ using ruff check. No secrets or services required; zero cost to add; catches 100%
  of import-convention and style violations on every push.
  3. Alembic migration CI verification — Add a Postgres service container (pgvector/pgvector:pg15) and run alembic upgrade head && alembic check in
  app-contracts or a dedicated migrations job. The apps monolith owns 130+ migrations; this is the only way to know they apply cleanly before they reach a
  deployed database.
  4. Coverage enforcement — Wire --cov=apps --cov-fail-under=<N> (start at 40%, ratchet up) into app-contracts. Already have pytest-cov in pyproject.toml;
  just not invoked. Add Codecov upload. This is inert code today — one missing flag.
  5. tests/integration/ with domain behavior tests — Port the domain-specific test files from the archive (arm, analytics, genesis flow, leadgen,
  calculation services, execution contract, data ownership, social scoring, memory bridge). These directly exercise apps.* behavior and have no runtime-only
   dependencies. They belong here, not in aindy-runtime.
  6. pytest.integration.ini — Add an integration config targeting tests/integration, setting AINDY_ALLOW_SQLITE=false and AINDY_SKIP_MONGO_PING=false.
  Required to run integration tests cleanly in CI and locally.
  7. pytest.postgres.ini — Port from the archive verbatim. The postgres marker is already defined; wire up a test-postgres CI job to actually exercise it.
  8. redis and multi_instance markers — Add to pytest.ini. Apps code that uses distributed queue behavior (watcher signals, async job submission) cannot be
  tagged, skipped, or selectively run without these markers.
  9. docker-compose.test.yml — Port the test services file (Postgres 5433, Redis 6380, Mongo 27017). Developer must have this to run integration tests
  locally; it's also the template for the CI service containers above.
  10. .env.example — Port from the archive. Documents all env vars needed for a working local setup. Currently absent; onboarding requires reading the CI
  workflow to understand what env is needed.
  11. Frontend E2E job — Add a frontend-e2e job with Playwright Chromium. The client/ is owned here; frontend-quality catches unit failures and
  frontend-build catches compile failures, but neither catches a broken user flow.
  12. node scripts/validate-env.js — Add to frontend-build job. The archive called this separately in frontend-test; it verifies that build-time env var
  injection is correct before deploying a client that silently sends requests to nothing.
  13. timeout-minutes on frontend jobs — Add timeout-minutes: 15 (or similar) to frontend-quality and frontend-build. No service dependency, minimal effort.
  14. Action SHA pinning — Port aindy-runtime's pinning style (actions/checkout@<sha>) to harden against supply-chain compromise. Low effort, meaningful
  security uplift.

  Items that are archive-specific and should NOT be ported:
  - Bootstrap dep validator that calls apps._bootstrap_validator — already present in app-contracts
  - tools/generate_api_reference.py — monolith-specific doc tooling
  - Runtime entrypoint verification — belongs in aindy-runtime, not here
  - tests/v1_gates/ — port only if the apps monolith wants to own v1 platform surface gates; currently they live in the monolith archive and have no natural
   home yet
```
