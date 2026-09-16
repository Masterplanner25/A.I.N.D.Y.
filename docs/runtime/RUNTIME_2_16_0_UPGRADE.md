---
title: "Runtime 2.16.0 upgrade — adoption"
last_verified: "2026-09-15"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.16.0 upgrade — adoption

Floor moved `>=2.15.0,<3.0` → `>=2.16.0,<3.0`; build pin `==2.15.0` → `==2.16.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.16.0.md`.

**This release closes our FR-30 and the FR-29 addendum** — both filed 2026-09-15 from the 2.15.0
container verification (`RUNTIME_2_15_0_UPGRADE.md` §5), fixed upstream the same day as
`EU-FINALIZE-UNCOMMITTED-1` (#673).

**No schema step, no required code change.** Verified rather than taken from the handoff:
runtime Alembic head unchanged at `0018`; `SCHEMA_CONTRACT_VERSION` unchanged at `2026-09-10`;
`git diff v2.15.0..v2.16.0 -- AINDY/db/models AINDY/memory/memory_persistence.py` is empty. The
diff under `AINDY/` is three files — `_version.py`, `core/execution_pipeline/resources.py` (+8:
one `db.commit()` after a successful `update_status` in `_safe_finalize_eu`, with the why),
`core/wait_rehydration.py` (+16: the `flow_runs`-exists guard in `ensure_waiting_flow_run_row`).
**We import from neither.**

---

## 1. The dev venv, re-checked printing the path

```
2.15.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # before
2.16.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # after pip install -c constraints.txt --no-cache-dir
```

`--no-cache-dir` from the first attempt this time (2.15.0's §1 records why); one install, clean.

---

## 2. Gained on adoption — FR-30 closed, FR-29 addendum closed

- **`_safe_finalize_eu` commits after a successful `update_status`.** At the write's own site,
  inside its existing try/except, so a commit failure records
  `execution_unit.finalize.<status>: failed` exactly as a flush failure did. Not `get_db`, not
  `update_status` — the two "not asking for" lines in FR-30 held. Route-sourced
  `execution_units` rows now end `completed` / `failed`; `executing` means *in flight*.
- **Why the runtime's own tests passed on the broken code** — recorded because it is the useful
  half: the shared fixture puts the app's request session and the test's reader on one
  connection inside one transaction, where a flush reads exactly like a commit. Their new suite
  reads through a separate connection with a liveness control (their catalogue variant 15).
  Our table was the only instrument that could see it.
- **Correction accepted:** the 105 `executing` units the runtime's 2026-09-13 run left behind were
  FR-30, not FR-29. `RUNTIME_2_15_0_UPGRADE.md` §2 repeated their attribution ("so, almost
  certainly, were the 105"); it was theirs to get wrong and is corrected upstream in place. Ours
  is left as written — it says whose claim it was.
- **FR-29 addendum, worse than reported:** `rehydrate_waiting_eus` seeded `waiting_flow_runs`
  with `run_id=eu_id` for **every** waiting unit, and a unit id is never a run id — so the FK
  violation fired for every waiting unit on every boot since the seed was written, not only for
  the ten leaked rows. SQLite does not enforce the FK, which is why no test saw it. The guard now
  covers both callers.

---

## 3. Consumer-visible edges, checked against our source

| Change | Where we would feel it | Our source |
|---|---|---|
| Route units end `completed` / `failed`; `executing` means in flight from the first request after upgrade | `ExecutionConsole.jsx` (`running` / `waiting` filters, lines 24–35); anything counting units by status | the ~900 pre-upgrade `executing` rows stay until retired (§5 step 3); the count stops growing |
| `[rehydrate] waiting_flow_runs seed failed … ForeignKeyViolation` at boot stops | log noise only | ten per boot on 2.15.0 → expect 0 |
| Boot Smoke retries the PyPI install (#672) | nothing at runtime | — |

**One precision on the handoff's "not touched, correctly" row.** It says `task_service.py:582`'s
`update_status(_eu.id, "waiting")` on pause "is followed by your own commit path". It is not:
`pause_task` commits at `:570`, *then* emits the pause event, *then* flushes the unit to `waiting`
at `:582`, and nothing of ours commits after that. So on ≤2.15.0 our task unit's `waiting` was
rolled back by the same mechanism as FR-30 — the finalize commit 2.16.0 adds is what carries it
now, because the route and the syscall both hand `pause_task` the pipeline's session. Checked
live in §5 rather than argued: the table has to show a `task`-sourced unit in `waiting` after a
pause, which it never could before.

---

## 4. Not taken: nothing new is flagged

No new opt-in knob. The 2.13.0 knobs stay off for the reasons in `RUNTIME_2_13_0_UPGRADE.md` §4.

---

## 5. Verification

### Dev venv, 2026-09-15

```
venv imports 2.16.0 from site-packages (path printed)               — §1
test_runtime_dependency_contract.py                                 — 6 passed
app-profile subset (seven CLAUDE.md files, -m app_profile)          — 55 passed
boot smoke: boot_profile=default-apps, app_plugins_loaded=True, app_plugin_count=16; 98 syscalls
ruff check apps/ tests/ — clean;  check_app_imports.py — 37 declared, 0 undeclared
```

**Full `tests/unit` on the installed 2.16.0 (2026-09-15, this venv, path printed):** `1240 passed, 1 skipped, 382 warnings, exit 0` — read from the summary line of the log file, not from progress dots.

<!-- CONTAINER_RESULT -->
