---
title: "Runtime 2.28.0 adoption"
last_verified: "2026-10-15"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.28.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.28.0.md`. No schema change (head stays `0020`), no
ui-kit change. It answers **FR-53**, all three parts, filed by us the day before. It is also **the first
release A.I.N.D.Y. carried to the end itself**: the owner handed `v2.28.0` off and approved at the gate
from the email (`RELEASE_HANDOFF_SPEC.md` §7.2). The adoption task it created (task 62) is this document.

## 1. The pin, and what is actually running (ask 1)

`constraints.txt` `aindy-runtime==2.28.0` and `pyproject.toml` `aindy-runtime[mcp]>=2.28.0,<3.0`, moved
together (`test_runtime_dependency_contract.py`). Verified 2026-10-15:

| Where | Result |
|---|---|
| dev venv | `2.28.0 ['…\venv\Lib\site-packages\AINDY']` |
| api container | `2.28.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| `/health` | 200; `boot_profile=default-apps`, `app_plugin_count=16` |
| schema | runtime `0020`, app `rh1handoff0001`, both unchanged by the release |
| agent runs `executing` after the restart | 0 (soak row 4) |

Full unit suite green on 2.28.0.

## 2. FR-53 (a): `mcp-server` loads our plugins, so the launcher stops doing it (ask 2)

`serve_stdio()` now calls `load_app_syscalls()`, which runs `load_plugins()` with stdout held on stderr
at the file-descriptor level, which is stronger than the launcher's `sys.stdout` swap. The launcher's
own load was a second copy of the slowest step at startup, so it is gone.

**Kept, deliberately:** `scripts/mcp_server.py` itself. What it adds over the plain command is the
read-only allowlist and the refusal of `AINDY_MCP_SERVER_ALLOW_WRITES`. Phase 2 of the release handoff
adds the first write tool there, one at a time. `claude mcp add` is unchanged.

Probed in the container with an `mcp` SDK client: ready in 6.5 s, the same 7 read-only tools,
`work_facts {work: "Nodus"}` found.

**DEC-101:** a plugin that fails to load now stops the MCP server, as it stops the api. To serve the
runtime's tools alone while one is broken, run it with `AINDY_BOOT_PROFILE=platform-only`.

## 3. FR-53 (b): a payload `user_id` can no longer choose the user (ask 2, second half)

Proven live: `nodus_work_context {user_id: <the test account>}`, called as the owner, is refused:

```
TENANT_VIOLATION: payload user_id '283ae082-…' for 'sys.v1.work.context' does not match the
authenticated caller; a payload may not choose the user it acts on   (failure_class: permission)
```

**The allowlist rule stays** (expose only syscalls that read `ctx.user_id`; `test_mcp_read_access.py`
reads their source). It is now our choice, not the only defence: the transport refuses a foreign id,
but in-process dispatch does not yet (§4), and several older syscalls of ours read a payload id
(`get_objective_attainment`, `masterplan.get_active`). The rule costs nothing.

Our one Nodus `sys()` script, `reasoning_apply_v1.nd`, passes the run owner's own id, so it is
unaffected (the runtime checked it; nothing of ours changed).

## 4. New counter: `aindy_payload_identity_mismatch_total{syscall}` (ask 3, window 1 read; window 3 owed ~10-29)

Registered on `/metrics/` with no samples at 2026-10-15 ~05:50 UTC. Every count would be our own
in-process `get_dispatcher().dispatch(...)` call with a payload `user_id` that differs from its context:
either a bug or a real on-behalf case. Zero across a window of real traffic is the evidence for the
runtime refusing in-process too (`PAYLOAD-IDENTITY-DISPATCH-1`).

**Owed: the readout after a week of normal use (~2026-10-22).** The counter **resets when the api is
recreated**, so read it before every rebuild and add up the windows, as with FR-49.

| Window | Container | Read | Result |
|---|---|---|---|
| 1 | 2026-10-15 05:48Z → 2026-10-22 ~17:25Z | 2026-10-22, before the window closed | **0**: the metric had no samples at all, across **1,496** syscall dispatches (`aindy_syscall_outcome_total`) on that container |
| 2 | 2026-10-22 ~17:25Z → 19:51Z | **never: lost** | unknown. The api container was deleted by mistake (a filtered `docker rm` during a test run) and recreated from the same image; that container was replaced at 19:51Z by the 2.28.1 rebuild **without a reading**. About 2.5 hours, little traffic, but **not zero**: it counts as no evidence |
| 3 | 2026-10-22 19:51Z (2.28.1) → | owed **~2026-10-29**, and before any earlier rebuild | |

Window 1's zero stands on its own and is evidence. Window 2 is a hole and must not be read as a zero.
Any non-zero reading goes to the runtime with its `{syscall}` labels: each names a call site.

## 5. Dependency bumps (§4): one reachable fix, nothing of ours

OpenTelemetry 1.45.1 fixes quadratic-time parsing of the `tracestate` header, which any client could
send before authentication (the runtime always instruments FastAPI). Now fixed on this stack.
pydantic 2.14.0, uvicorn 0.54.0, jiter 0.17.0: nothing we use changes (the runtime read the notes).

## 6. FR register

FR-53 marked ✅ shipped in 2.28.0. Open runtime asks: FR-14 recurrence half, FR-6 items 2–3.
