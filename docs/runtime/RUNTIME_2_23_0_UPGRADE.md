---
title: "Runtime 2.23.0 upgrade — adoption"
last_verified: "2026-09-25"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.23.0 upgrade — adoption

Floor moved `>=2.22.0,<3.0` → `>=2.23.0,<3.0`; build pin `==2.22.0` → `==2.23.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.23.0.md`.

**No schema step and no required code change, and both were verified, not taken from the handoff.** Two of
the handoff's statements about us are out of date (§5 and §6), and are answered below.

---

## 1. Installed runtime, printing the path

```
2.23.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # dev venv, pip install -c constraints.txt
2.23.0 ['/usr/local/lib/python3.11/site-packages/AINDY']                     # container
```

Rebuild with the pin moved: **224 s**. The 15–18 min figure in CLAUDE.md is a ceiling, not a
constant. Boot: `default-apps`, `app_plugins_loaded=True`, `app_plugin_count=16`, `/health` 200.

---

## 2. Schema — checked by the columns, not the exit code

FR-43 (2.22.0) showed that `bootstrap-schema`'s "no table changes" can be wrong about a type
change, so this adoption reads the database directly:

- `git diff v2.22.0..v2.23.0 -- AINDY/db/models alembic AINDY/memory/memory_persistence.py` is **empty**
- entrypoint: `ok: runtime-owned tables already present (no table changes)` / `stamped … 0020`
- `alembic_version_runtime` **`0020`**; `SCHEMA_CONTRACT_VERSION` **`2026-09-20`**;
  `system_events.source` still **`varchar(128)`**; app head `sc1concl0001` unchanged

---

## 3. What changed under us — the import surface

The runtime diff is 11 files under `AINDY/`. We import from three of them
(`agents/capability_service.py`, `agents/tool_registry.py`, `platform_layer/metrics.py`), and the
only definition changes in those files are **additions** (`_tool_idempotency_strict_enabled`,
`_tool_idempotency_strict_wait_seconds`, `scheduler_resume_forwarded_total`). Every symbol we take
(`TOOL_REGISTRY`, `register_tool`, `register_tool_suggestion_provider`, `get_auto_grantable_tools`,
`validate_token`, five metrics) is unchanged. Unit suite, ruff and the import check pass on the
2.23.0 venv.

---

## 4. The four items, against our stack

| Item | Applies to us? | Evidence |
|---|---|---|
| **FR-42** — FK warning on every non-agent `mint_token` (§2) | **No** | we never call `mint_token`; the 2.22.0 api log had **0** `create_run_capability_mappings failed` lines |
| **FR-15** — two silent losses in distributed mode (§3) | **No** | single-instance (`deployment_profile: single-instance`). `aindy_scheduler_resume_forwarded_total` is exported and will stay 0 here |
| **`AINDY_TOOL_IDEMPOTENCY_STRICT`** (§4, IDEM-13) | **No consumer** | no tool of ours declares `execution_guarantee`; left unset |
| **Dependency bumps** (§5) | transparent | `uvicorn` 0.53.0 served the boot and every probe above |

FR-15's symptom ("`woken: true` and a run that stays `waiting`") is **not** the one we filed as
FR-44 ("`waiters_notified: 0`, run stays `waiting`" on single-instance). The two are close, but
the topology and the cause differ, so FR-44 stays open.

---

## 5. Handoff §5 (`nltk` / `textstat`) — already done

The handoff says our search service imports both **undeclared**. They have been declared in our
`pyproject.toml` since #391 (2026-09-18; `nltk>=3.10.3,<4.0`, `textstat>=0.7.13,<1.0`), as
recorded in `RUNTIME_2_21_0_UPGRADE.md` §4 and acknowledged in the 2.22.0 handoff §3. Nothing
changes for us when the runtime drops its pins after 2026-10-01.

---

## 6. The two asks

1. **The `nodus_vm` denial re-run — already done, 2026-09-23**, on 2.22.0:
   `RUNTIME_2_22_0_UPGRADE.md` §4.1 and the FR-38 register entry (#400). Run `bea83301…` parked
   (`AUTHORITY_NEGOTIATED` → `WAITING`, `no_variant`), was refused without a decision (409) and
   with an unknown one (422), and completed on `skip`. The first denial on `nodus_vm` is
   **observed**; with the 09-16 `agent_flow` run, the phase-3 flip has evidence from both
   backends. One defect found on the way is FR-44.
2. **`AINDY_TOOL_IDEMPOTENCY_STRICT` window — we are not the traffic.** No tool of ours is
   `EXACTLY_ONCE`, so our traffic cannot contend on the tool gate. A window here would read zero
   `replayed` and prove nothing, as the handoff itself warns.

---

## 7. Soak register row 1 — mid-window, across the restart

`AINDY_MEMORY_RECALL_OWN_SESSION=true` (on since 2026-09-23T20:30Z) survived the rebuild; the flag
is in `.env`, so it is not an image property. Read just before the restart (2026-09-25):
`[MemoryOrchestrator] recall failed` **0**, `idle in transaction` **0**,
`aindy_db_pool_exhaustion_events_total` **0**, checked-out 0.

**Presence signal: not yet.** **0** `memory.recall` agent steps since the flag went on. The
owner's one real run (`02e9e214`, 09-25) did not plan one. The absence half is clean, but on the
register's own terms the window has not exercised the flag. The api restart resets the
`/metrics` counters, so the end-of-window reading needs the log and the step table, not only
counters.
