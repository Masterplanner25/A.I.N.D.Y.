---
name: nodus-workflows
description: Writing, registering or changing an A.I.N.D.Y. Nodus (.nd) workflow under apps/<domain>/nodus/: the pattern, fallbacks, capabilities, packaging and FR-55 limits.
---

<!-- Moved from the root CLAUDE.md on 2026-11-09 so it loads only when working here. -->

## New workflows are written in Nodus (`.nd`)

**Owner, 2026-10-22: A.I.N.D.Y.'s own workflows are written in Nodus.** Before that date, all of our
orchestration was Python: `register_flow_definitions` node graphs and APScheduler jobs. Nodus ran
only underneath us, in the agent backend (`nodus_vm`), and the one `.nd` we had was switched off.
**A new workflow goes in `apps/<domain>/nodus/<name>.nd`, not in a new Python flow graph.** Existing
Python flows stay as they are until one is deliberately ported.

- **Ours so far, five:**
  - `apps/analytics/nodus/reasoning_apply_v1.nd`: the reasoning flow.
  - `apps/analytics/nodus/infinity_recalc_v1.nd`: the daily Infinity recalculation for one user (#487).
  - `apps/rippletrace/nodus/archive_published_work_v1.nd`: four steps chained with `after`, each
    `with { retries: 2 }`, for one owner (#489).
  - `apps/rippletrace/nodus/share_drafts_v1.nd`: the share drafts for one newly published piece (a
    LinkedIn post, a short post, a meta description, the previous piece's What's Next? footer), into
    the Drafts section (owner, 2026-10-25). Its step is idempotent: the drafts and the piece's mark
    are one transaction.
  - `apps/rippletrace/nodus/piece_answers_v1.nd`: what one newly published piece answers, stored per
    version of its text (`ARTICLE_ANSWERS_SPEC` B2, owner 2026-11-08). Same shape and idempotence as
    share drafts.

  Each has a flag: `AINDY_REASONING_NODUS_NATIVE`, `AINDY_INFINITY_RECALC_NODUS`,
  `AINDY_ARCHIVE_NODUS`, `AINDY_SHARE_DRAFTS_NODUS` and `AINDY_PIECE_ANSWERS_NODUS`. The flags are off in code and on in compose, and any VM failure falls back
  to Python.
- **The pattern:**
  - **Source:** `apps/<domain>/nodus/*.nd`.
  - **Registration:** one line in the domain's `bootstrap.py`, which calls
    `apps/_shared/nodus.py::register_domain_nodus_workflows(__file__, "<domain>")`.
  - **Call:** a small `services/…_nodus.py` that runs it through `run_nodus_workflow`, reads the
    result and falls back to Python.

  `apps/rippletrace/services/archive_nodus.py` is the fullest example.

  **The `.nd` files ship as package data** (`[tool.setuptools.package-data]` in `pyproject.toml`). A
  scheduled job's callback imports the *installed* `apps`, not `/app/apps`; until 2026-11-02 that copy
  had no `nodus/` folders, so every scheduled run fell back with "is not registered".
  `test_nodus_files_are_packaged.py` builds the wheel and checks them.
- **A fallback must call `record_nodus_fallback(db, workflow=…, user_id=…, reason=…)`** (`apps/_shared/nodus.py`),
  after any rollback. It writes a durable `nodus.fallback` event, and `owner_notices.py` emails the owner
  when one workflow falls back 3 times in a day. Before 2026-11-01 a fallback was one WARNING line, and
  10 days of them went unseen (`NODUS-FALLBACK-SILENT-1`). `test_owner_notices.py` checks every caller.
- **A job that fires often must not start a cold worker for nothing.** Start a VM run only when
  there is work. The archive job runs every 10 minutes, so it checks `archive_due` first, and a
  settled catalogue stays on the Python path.
- **The script reaches app logic only through `sys("sys.v1.…", args)`.** It cannot import Python, so
  everything the workflow needs must be a registered syscall. **`sys()` is granted only the
  capability the runtime infers from the syscall's name** (`_infer_dispatch_capability`): `get_…`,
  `list_…` and the like map to `<domain>.read`, `create_…` and the like to `<domain>.write`, and any
  other name maps to itself. If that is not the capability the syscall requires, every VM run is
  denied and quietly falls back to Python. `sys.v1.analytics.execute_infinity` (requires
  `score.recalculate`) fails this; `sys.v1.score.recalculate` passes. Assert it in a test, as
  `test_infinity_recalc_nodus.py` does.
- **Build a syscall's handler once, at import, never inside the `register_…` function.** The registry
  compares handlers by identity, and every app-profile boot registers again. A closure built at
  registration time is a new object on the second boot, so bootstrap fails with `already registered
  with a different handler`. That happened on #489, and only CI's second boot showed it.
- **A workflow acts as one user.** The runtime refuses a payload `user_id` naming another user over
  MCP since 2.28.0 and **in-process since 2.29.0** (DEC-103: `TENANT_VIOLATION`, the handler does
  not run), and counts each one (`aindy_payload_identity_mismatch_total`; on 2.29.0 a label is a
  refused call). `AINDY_PAYLOAD_IDENTITY_DISPATCH=observe` turns the refusal off; we do not set it. So a job over all users stays a Python loop that starts
  one run per user (`run_nodus_workflow(..., user_id=…)`), and the script's syscalls read
  `ctx.user_id`.
- **Run `nodus check <file>.nd` before pushing**, and add a test like
  `test_analytics_nodus_workflow.py` that compiles it.
- **A cold worker takes 17–21 s; a warm one about 2 s** (measured 2026-10-22: Python did the same
  recalculation in 2.0 s). The warm pool is the runtime's default, but a scheduled job's callback
  is a fresh process (the 90 s `AINDY_RUNTIME_CALLBACK_TIMEOUT_SECS`), so its first run is
  always cold. Keep `.nd` off request paths that must answer quickly.
- **A workflow can pause only until an event arrives. It cannot sleep until a time** (checked
  2026-10-22 on 2.28.1 and runtime `main`, filed as **FR-55**). `await_event(type, schema)` parks the
  run durably: `waiting_flow_runs` survives a restart, and an event or `POST …/runs/{id}/resume`
  wakes it. But:
  - **the deadline fails the run** (`WAIT_TIMEOUT`); it never resumes it;
  - **the deadline is 30 minutes for every guest script** (`FLOW_WAIT_TIMEOUT_MINUTES`), because they
    all run under the runtime's `nodus_execute` flow;
  - **a resume re-runs the script from the top.** Only `nodus_received_events` comes back, not
    what the script saved with `set_state`, so every step must be safe to run twice.

  nodus-lang has `on_timeout: "resume"`, but the A.I.N.D.Y. embedding does not pass it through.
  **So write one-shot workflows, and leave tick-driven jobs in Python until FR-55 ships.** The Resolution
  Check (6 questions a minute) and the release-handoff watcher are two such jobs: ported today, each
  would still need its tick and would rebuild its progress from its own tables on every wake.
- **Trigger with `register_scheduled_job`, not the runtime's Nodus scheduler.**
  `POST /platform/nodus/schedule` stores a copy of the script in a per-user row
  (`nodus_scheduled_jobs`), so a change to the `.nd` file would never reach it.
- **Results land in `data.nodus_output_state`** (what `set_state` wrote), with `data.nodus_status`
  saying whether it succeeded. Each run also leaves a record on the `nodus_state` volume, and
  nothing prunes it.
