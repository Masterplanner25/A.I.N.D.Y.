# Tests: hazards that look like your change and are not

<!-- Moved from the root CLAUDE.md on 2026-11-09 so it loads only when working here. -->

## `_fresh_main_app()` and `Base.metadata` — model import timing hazard

`_setup_postgres_schema` (session-scoped, autouse) calls `Base.metadata.create_all()` once at session start. Each test's `_fresh_main_app()` reloads `AINDY.main` + `AINDY.startup`, which imports all app modules and may add new model classes to `Base.metadata`. Tables registered this way exist in `Base.metadata` but **were never created in PostgreSQL** because `create_all` already ran.

`cleanup_committed_test_state` guards against this by querying `pg_catalog.pg_tables` before building the `TRUNCATE` list — only truncating tables that actually exist in the DB. **Do not simplify this back to iterating `Base.metadata.sorted_tables` directly.** Tables like `freelance_refund_records` (imported late via a freelance module reload) will raise `UndefinedTable`, which rolls back the cleanup transaction, leaves data in the DB, and cascades into isolation assertion failures and `InFailedSqlTransaction` errors across the rest of the session.

## `test_real_vm_run_routes_through_nodus` fails under load, not because of your change

The Nodus VM worker cold-starts the whole app stack (~16 apps) per execution. The runtime
default budget is **30s script + 15s boot**, which a full-suite run on a busy machine can
exceed:

```
[nodus.execute] FAILURE error=Nodus worker exceeded 45000ms hard limit
  (30000ms script budget + 15000ms boot allowance) — worker or plugin cold-start hung
```

The VM then falls back and `run_reasoning_apply` returns `{'data': {}}` with no `_via`, so the
assertion reads as a logic failure rather than a timeout. It passes when the file is run alone.

`pytest.ini` now sets `AINDY_NODUS_MAX_EXECUTION_MS=120000` and
`AINDY_NODUS_BOOT_ALLOWANCE_MS=60000`, matching what `docker-compose.prod.yml` already does
for the container and for the same documented reason.

**Do not attribute this failure to whatever you just changed until you have re-run it.** It is
load-dependent, so two consecutive failures are not proof of causation — check the log for the
`45000ms hard limit` line first.

**If that line is ABSENT, it is the other failure mode: your venv, not the code.** Diagnosed
2026-09-06 after this entry sent a session looking for a timeout that was not there.

```bash
python -m pip list | grep aindy-apps-monolith   # empty = this is your problem
python -m pip install -e .[test] --no-build-isolation
```

The Nodus worker is spawned as `subprocess.run([sys.executable, nodus_worker.py])`, so
`sys.path[0]` is the *worker's* directory and the inherited cwd is **not** on `sys.path`. If this
repo is not pip-installed, the worker cannot `import apps`, `load_plugins()` raises
`ModuleNotFoundError`, and `_ensure_tools_loaded` swallows it **at DEBUG**. The worker then runs
with 23 runtime syscalls instead of 97 (measured 2026-09-16), and the visible symptom is
three layers away:

```
"error": "Unknown syscall: 'sys.v1.analytics.get_reasoning_recommendation'"
```

…for a syscall that is registered and present in the parent process. Reasoning then takes its
designed fallback to Python and the only surviving evidence is the missing `_via` key — i.e.
**exactly the same assertion failure as the timeout case, with a completely different cause.**

`pytest` and `python -c` both put cwd on `sys.path`, which is why every other test passes and
only this one — the only test that crosses a subprocess boundary — notices. Two things depend on
the install and fail silently without it:

| missing | consequence |
|---|---|
| `pip install -e .` | the worker cannot import `apps` (above) |
| `.[test]` extra → `pytest-env` | **`pytest.ini`'s entire `env =` block is inert**, including the `AINDY_NODUS_*` budgets this section prescribes and `ENFORCE_EXECUTION_CONTRACT=true` |

That second row is why the remedy above can appear not to work: without `pytest-env` the budget
fix is never applied. `conftest.py` sets `DATABASE_URL` and `AINDY_ALLOW_SQLITE` by
`os.environ.setdefault`, which is why nothing else complains. CI runs `pip install -e .[test]`
and has neither problem. Filed upstream as `RUNTIME_FEATURE_REQUESTS.md` FR-25(c) — the log
level, not the spawn, which is ours.

## `AINDY_AGENT_PLANNER_BACKEND` in integration tests

Use `disabled` (set in `pytest.integration.ini`), **not** `stub`. The `stub` backend causes planner-path tests to fail with errors rather than cleanly skip when the planner isn't wired up. Tests that touch planner-dependent paths must check `os.environ.get("AINDY_AGENT_PLANNER_BACKEND") == "disabled"` and skip or fast-path accordingly.
