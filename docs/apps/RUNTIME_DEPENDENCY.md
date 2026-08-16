---
title: "Runtime Dependency"
last_verified: "2026-07-18"
api_version: "1.0"
status: current
owner: "platform-team"
---
# Runtime Dependency

`aindy-apps-monolith` depends on the separately packaged `aindy-runtime`
distribution.

This repo does not own `AINDY/`, runtime-only entrypoints, or runtime-only
documentation. Those live in the `aindy-runtime` repo and are consumed here as
published contracts.

## Package Contract

Recommended dependency range:

```toml
aindy-runtime>=2.1.0,<3.0
```

The upper bound is required. The apps repo should not accept unbounded runtime
upgrades.

Validated on `2026-08-15`:

- installed runtime version: `2.1.0`
- apps repo dependency (pinned in `pyproject.toml`): `aindy-runtime>=2.1.0,<3.0`
- runtime `/api/version` recommendation: `>=2.0,<3.0`
- app-profile boot smoke on 2.1.0: `boot_profile=default-apps`, `app_plugins_loaded=True`, `app_plugin_count=16`

## 2.0.0 — a major bump, and the pin cannot move alone

`>=2.0,<3.0` **must land in the same change as the register-flow rewrite.** Registration now
returns `202` with no token; a client that auto-logs-in from the register response has
nothing to read and signup visibly fails.

Deploy notes, in the order they will bite:

1. **Every session ends at upgrade.** Access tokens now require a `purpose` claim, so all
   existing tokens are rejected and every user logs in again. Expected, not a fault.
2. **Verification mail must be deliverable.** Registration emails a link and the access token
   is only issued by `POST /auth/verify-email`. With neither an `email` connector nor
   `AINDY_SMTP_*` configured, **a new signup cannot complete.** Existing accounts are
   unaffected — the 2.0.0 migration backfills them to verified.
3. **`AINDY_EMAIL_VERIFY_URL_TEMPLATE` must point at the client's `/verify-email` route**
   (e.g. `https://<host>/verify-email?token={token}`). Unset, the mail carries a bare token
   with nowhere to paste it. Compose pass-throughs are wired in `docker-compose.prod.yml`.
4. **Leave `AINDY_REQUIRE_VERIFIED_LOGIN` off** unless every account is verified — it is a
   lockout risk, and the enumeration fix does not depend on it.
5. **Register enforces `MIN_PASSWORD_LENGTH` (8).** Seeding and smoke scripts using shorter
   passwords will 400. Stored passwords and login are unchanged.

**Security, pre-existing and fixed upstream in 2.0.0:** before this release `/auth/register`
and `/auth/login` passed the whole request body as the pipeline's `input_payload`, so
plaintext passwords could reach the execution record. Audited on this deployment across
`execution_units.extra`, `system_events.payload`, `job_logs.payload`, `agent_events.payload`
and `memory_nodes` — **no credential key and no credential value found**, and `input_payload`
is not persisted in any of the 2,651 execution units (spanning 2026-07-19 to 2026-08-02).
Anywhere execution records are exported outside the database is outside what that audit
covers.

Previously, the floor was raised to `1.11.0` to adopt v1.11.0 (minor, not patch — it adds a public endpoint):
`POST /auth/password/change`, which closes FR-6 item 1. Nothing in the release is
source-breaking for app code.

**The one behavioural change that can reach a deployment:** `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS`
default moved `30000 → 60000`, because the flow runner holds its session
`idle in transaction` for the whole of node execution while a nodus run may legitimately
occupy 45s (`AINDY_NODUS_MAX_EXECUTION_MS` 30s + `AINDY_NODUS_BOOT_ALLOWANCE_MS` 15s). At 30s a
slow-but-in-budget run had its connection killed mid-flight.

**A default change only helps deployments that do not pin the value — and this one does.**
`docker-compose.prod.yml` sets it explicitly to `120000` (verified in the running container),
which already clears the 45s ceiling, so no action was required. The action item is the negative
one: **do not lower it below ~45s**, and if either nodus budget is raised, raise this above their
sum. Root cause is not fixed in 1.11.0 — the transaction is still held across node execution;
the opt-in fix is `AINDY_MEMORY_RECALL_OWN_SESSION` (default off), which gives memory recall its
own short-lived session. Runtime tracks it as `DB-NODUS-BUDGET-1`.

**If the `[mcp]` extra is ever installed**, it is now capped at `mcp>=1.0.0,<2`; `mcp 2.0.0`
removed the 1.x low-level `Server.list_tools()` decorator that `nodus-mcp 0.1.2` is built on. Any
direct `mcp` install must carry the same cap.

Previously, the floor was raised to `1.10.2` to adopt v1.10.2 (additive/opt-in, no schema change): the **third and
final RT-MEMTXN-LEAK-1 fix**, closing the issue across all three parts. See
`RUNTIME_FEATURE_REQUESTS.md` for the live verification numbers.

RT-MEMTXN-LEAK-1 took three releases because it was three distinct "slow external call inside an
open transaction" sites, each masked by the previous fix:
- `1.10.0` — memory recall's embedding. Fixed the *post-request lingering* (connections now
  drain at request end). Partial: the within-request fan-out remained.
- `1.10.1` — the embedding job's post-commit refresh. Verified app-side as **still broken**:
  login 41.9s with 60/60 connections idle-in-transaction on `memory_nodes`.
- `1.10.2` — the third site in the recall read path itself.

**Verification lesson:** sample `pg_stat_activity` *mid-request*. A post-request sample looks
clean from 1.10.0 onward even while the leak is present — that is what made 1.10.0 look fully
fixed. Repro scripts live in `scratchpad/memtxn_*.sh`.

Prior floor `1.10.0` also **closed NODUS-WARMPOOL-1** (warm `nodus_worker` pool, Phases 1–3 —
opt-in via `AINDY_NODUS_WARM_POOL=true`, default off) and added canonical `UI_CONTRACT`
platform routes.

Prior floor `1.9.0` adopted v1.9.0 (additive/opt-in, no schema change): **FR-5** —
native Nodus workflows can now reach app logic (`run_nodus_workflow` gains a
`capability_token` param so `call_tool` steps can be granted capabilities, and the VM's
`sys()` resolves app-registered syscalls), unblocking Nodus-native reasoning execution;
plus NODUS-WARMPOOL-1 Option A (VM cold-start off the script budget). App-side adoption of
the Nodus reasoning routing lands in a follow-on PR.

Prior floor `1.8.0` adopted v1.8.0: FR-1 connector-registration hook +
capability-enforced outbound boundary (`register_connector`), FR-3
`NEXT_ACTION_DISPATCHED` dispatch-outcome contract, the FR-4 / DOCS-BUCKET-A-1
error-handling-policy runtime/app split, plus a `setuptools>=83.0.0` (CVE-2026-59890)
security bump and `nodus-lang 4.1.0` / `nltk 3.10.0`.

The floor stays at or above `1.5.3` for **both** nodus_vm execute-to-completion fixes (first shipped in v1.5.2 / v1.5.3): aindy-runtime
#152 / PR #155 (v1.5.2 — `ExecutionPipeline.run()` marks itself active before emitting its
own `execution.started`) and aindy-runtime #157 / PR #158 (v1.5.3 — the syscall idempotency
gate no longer casts a run-scoped `execution_unit_id` to a UUID column and wraps the lookup
in a savepoint). Together they let a resumed nodus_vm segment run to a terminal state; Gate 2
of `tests/integration/test_nodus_vm.py` hard-asserts that completion. See TECH_DEBT
`RTR-1-NODUS-COMPLETION`.

`aindy-runtime` is published on PyPI (`PYPI-PUBLISH-1` is closed), so this is the
live, published dependency contract — not a pre-publication staging arrangement.

## CI Install Strategy

`aindy-runtime` is installed from PyPI as a normal pinned dependency:

- the declared dependency in `pyproject.toml` is `aindy-runtime>=2.1.0,<3.0`
- CI installs it via `pip install -e .[test]` (no runtime-repo checkout, no source
  install)
- CI verifies the installed runtime version and that `/api/version` reports the
  expected compatibility metadata

GitHub workflow behavior:

- CI checks out only this repo and resolves `aindy-runtime` from PyPI within the
  pinned range; there is no runtime-repo checkout or `AINDY_RUNTIME_*` token.

This is the published packaged-runtime contract in steady state.

## Startup Contract

The apps repo owns:

- `aindy_plugins.json`
- `apps.bootstrap`
- app bootstrap ordering and degraded-domain policy

The runtime package owns:

- `aindy-runtime serve`
- `aindy-runtime`
- manifest parsing and profile selection
- plugin loading
- runtime-only boot

Deployment boundary:

- this repo owns app-profile deployment inputs such as `aindy_plugins.json`,
  `apps.bootstrap`, `alembic/`, and `client/`
- the runtime repo owns runtime-only deployment guidance, runtime packaging,
  and standalone runtime boot surfaces

## Release Staging Expectation

When the runtime repo stages a new release:

1. the runtime version is bumped in `AINDY/_version.py`
2. the runtime staged build verifies `/api/version` compatibility metadata
3. this repo keeps or updates its bounded dependency range deliberately
4. app-profile CI runs against the target runtime version before adoption

The apps repo should not move to an unbounded runtime dependency such as
`aindy-runtime>=1.0`.

App CI installs `aindy-runtime` directly from PyPI within the pinned range; bump
the lower bound deliberately when adopting a newer runtime release.

Canonical app-profile startup from this repo root:

```bash
aindy-runtime serve
```

Equivalent explicit-manifest form:

```bash
AINDY_APP_PLUGIN_MANIFEST=./aindy_plugins.json aindy-runtime serve
```

## Runtime Docs

When this repo references runtime contracts such as the public API boundary,
runtime-only deployment, DB ownership, or compatibility policy, treat those as
living in the separate `aindy-runtime` repo.
