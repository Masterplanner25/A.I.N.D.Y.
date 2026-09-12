---
title: "Runtime 2.11.0 upgrade — adoption"
last_verified: "2026-09-11"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.11.0 upgrade — adoption

Floor moved `>=2.9.0,<3.0` → `>=2.11.0,<3.0`; build pin `==2.9.0` → `==2.11.0`. One move
covers two releases — 2.10.0 shipped without a handoff of its own and its consumer-relevant
content is folded into the 2.11.0 handoff (`aindy-runtime/docs/runtime/APP_HANDOFF_v2.11.0.md`).

**No schema step, no required code change.** Verified rather than taken from the handoff:
`git diff v2.9.0 v2.11.0 -- AINDY` touches 20 files and none of them is
`platform_layer/registry.py` or `kernel/syscall_registry.py`, so every `register_*` hook and
every syscall this repo depends on is byte-identical. The deployed database is already served
past the 2.8.0 step the 2.9.0 doc still owed (`flow_runs.graph_signature` present, runtime
Alembic head `0018`).

---

## 1. ★ The handoff's first section is about us, and it is the `pip show` trap again

The 2.11.0 handoff opens with a measurement taken in this repo on 2026-09-10 concluding we were
on **2.6.0** — from `dist-info` and `AINDY._version.__version__` in `venv/Lib/site-packages`.
That is the published-package venv, which nothing here runs. The local paired-repo flow is an
**editable install of the sibling checkout** (`CLAUDE.md`, "Runtime dependency contract"), and
on that path `dist-info` reports whatever version was recorded the day the editable link was
made and never re-reads:

```
importlib.metadata.version('aindy-runtime')   → 2.0.1     (stale metadata)
import AINDY._version; __version__            → 2.11.0    (what actually runs)
```

Two sessions in this repo made the same mistake on 2026-09-08 (`SESSION_HANDOFF`, "pip show
lies about editable installs"), and now the runtime team has made it from the other side. The
container is the only place the number is unambiguous, because it installs from PyPI with
`-c constraints.txt`: it was `2.9.0` before this change and is `2.11.0` after the rebuild.

**Verify by importing.** The handoff's own §7 step 1 uses `importlib.metadata`, which is the
wrong instrument for an editable install; the right one is
`python -c "import AINDY._version as v; print(v.__version__)"`.

---

## 2. One deployment change taken: durable nodus workflow state

Handoff §4. Guest Nodus workflows keep framework run records in the worker's cwd
(`/home/aindy`, no volume) and lose them on every recreate. `docker-compose.prod.yml` now sets
`NODUS_RUN_STATE_ROOT=/var/lib/aindy/nodus-state` on a named volume `nodus_state`.

Why taken rather than deferred: it is one env var and one volume, the runtime's own compose does
the same, and not doing it leaves a known data loss in place for the day
`AINDY_REASONING_NODUS_NATIVE` comes off its soak gate. Three things from the handoff, honoured:
the new variable (not the legacy `NODUS_WORKFLOW_STORE_ROOT`), local storage (a Docker volume on
the WSL disk; the store is SQLite in WAL mode), and the fact that **it grows and nothing prunes
it** — noted in the compose comment. With the flag off nothing writes there today.

---

## 3. Not taken, and why

- **`AINDY_AUTHORITY_NEGOTIATION`** — inert for us by construction: no tool this repo registers
  declares a `degraded_variant`, so the sweep the runtime runs at startup examines nothing. The
  16 tools arrive through `register_run_tool_provider` (`CLAUDE.md`); when one of them wants a
  fallback, that is the day to read `authority_negotiation.py`.
- **`AINDY_FLOW_FAN_OUT`** — no flow in `apps/` declares a `FanOutEdgeGroup`, so the flag gates
  nothing here. Width is process-wide and shares the DB session budget with request handling,
  which on this host's memory floor (`POSTGRES-CRASH-RESIDUAL-1`) is a reason to leave it off
  even once a flow could use it.
- **Deploy entrypoint** — unchanged. `docker/entrypoint.sh` already runs `bootstrap-schema`
  before `serve`, which is the ordering the handoff's §1 exists to recommend to people who lack
  it.

---

## 4. Smaller things, checked

- `SCHEMA_CONTRACT_VERSION` moved `2026-09-02.1` → `2026-09-10` with no migration. Nothing in
  `apps/` or `tests/` asserts on it (grepped).
- `pydantic-core` is no longer pinned by the runtime. Nothing here pinned it either.
- The eight `Unknown event type` warnings per agent run go away. Nothing here alerts on them.
- `nodus-lang` 5.9.0 → 5.13.0 is a security release upstream to which the runtime was not
  exposed (it embeds `NodusRuntime`, never `nodus serve`). Same for us: the only Nodus source
  in this repo is `apps/analytics/nodus/reasoning_apply_v1.nd`, registered from disk.

---

## 5. Also fixed while here: `RUNTIME_DEPENDENCY.md` had said 2.4.1 since August

Three places declared the range as `>=2.4.1,<3.0` and the "validated on" block named runtime
`2.1.0`, while the real pin went 2.6 → 2.8 → 2.9 underneath. Corrected to 2.11.0 with a note that
the per-release upgrade doc is the record and that file is a pointer. The `Dockerfile` header
comment carried the same stale `2.4.1`; also corrected. This is the failure `CLAUDE.md` names
for the syscall count — *a number nobody re-derives is a number that drifts* — and it had
three more instances.

---

## 6. Verification

Local `AINDY/` is the sibling checkout at `v2.11.0-2` — ahead of the tag only in `docs/`, no
diff under `AINDY/`.

| check | result |
|---|---|
| `test_runtime_dependency_contract.py` | pass — range and pin in lockstep at 2.11.0 |
| app-profile subset (8 files, `-m app_profile`) | 55 passed |
| full `tests/unit` | **1,222 passed, 0 failed, 1 skipped** |
| boot smoke | `default-apps`, `app_plugins_loaded=True`, count **16** |
| `scripts/check_app_imports.py` | 37 declared, 0 undeclared |
| `ruff check apps/ tests/` | clean |
| `docker compose config` | `NODUS_RUN_STATE_ROOT` set, `nodus_state` volume declared |

**After the rebuild** (`--no-cache`, because the pin moved — the one case
`live-verification-practice` reserves it for): the container's own `pip show aindy-runtime`
must say `2.11.0`, `alembic_version_runtime` must still be `0018` (no runtime migration ships),
and `/health/deep`'s `syscall_registry.count` must be **97** (73 ours + 24 runtime, measured
2026-09-10) — a lower number means the app plugin stack did not load.

### What this does not establish

Nothing in 2.10.0 or 2.11.0 changes a code path this repo exercises, so the suites prove the
same thing they proved on 2.9.0. The two new features are unexercised because nothing here
declares the things they act on. That is the correct state for a release whose handoff says
"required of you: nothing".
