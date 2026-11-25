---
title: "Runtime 2.41.0 adoption"
last_verified: "2026-11-22"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.41.0 adoption (with 2.39.0 and 2.40.0)

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.39.0.md`, `…v2.40.0.md` and `…v2.41.0.md` (tags `v2.39.0`,
`v2.40.0`, `v2.41.0`). We come from 2.38.0, live since 2026-11-19 05:22:14Z, and take the three releases in one move,
which the 2.41.0 handoff allows. **No schema step in any of them:** Alembic stays `0022`, schema contract
`2026-11-09` (the compare `v2.38.0...v2.41.0` touches no migration). No ui-kit or aindy-sdk release.

Pin: `constraints.txt` `aindy-runtime==2.41.0`, floor `>=2.41.0,<3.0`, moved together
(`test_runtime_dependency_contract.py`). We pin nothing else the runtime moved (`openai`, `httpx2`, `httpcore2`,
`truststore`, `nodus-lang`), so the install resolves on the runtime's exact pins.

| Release | What moved | What it asks of us |
|---|---|---|
| 2.39.0 | FR-55: `prior_state(key)` (DEC-135), `await_event_for(event, schema, seconds)` (DEC-136); the stuck-run watchdog respects a wait's own deadline | FR-55 closes on a ported loop (§2) |
| 2.40.0 | `openai` 2.54.0 → **3.57.0** (DEC-138, transport `httpx2`, TLS from the OS store); scoped trace graphs keep the caller's own cross-trace edges (DEC-137); FR-6 notice | re-read `d534a3fd…` scoped (§3); mark FR-6 closed (§4) |
| 2.41.0 | `nodus-lang` 5.16.0 → 5.17.0 (a guest's bounds hold inside module calls); guest imports in a non-root image and `import "memory"` (DEC-139) | the pin and the confirm line |

## 1. What we checked in our tree

- **`openai` 3.** Our one direct client is `apps/automation/services/owner_notices.py::probe_openai`; the runtime
  checked it on 3.57.0 (`timeout=`, `max_retries=`, and the error fields `classify()` reads are unchanged). Every other
  paid call goes through `apps/_shared/provider_keys.py` and the runtime's clients. **No test of ours uses `respx`**,
  so none silently stops intercepting.
- **TLS trust** for OpenAI and DeepSeek is now the OS store (Debian `ca-certificates` in the image). Nothing between
  the api container and the providers presents a private CA, so nothing to set.
- **nodus-lang 5.17.0.** None of our five `.nd` files (`apps/analytics/nodus/`, `apps/rippletrace/nodus/`) imports a
  module, so the new time and memory accounting inside module calls does not reach them. We register no host function
  under the four newly reserved names (`substring`, `str_substring`, `str_span`, `str_span_until`).
- **The watchdog change (2.39.0 §3) reaches one flow of ours.** `genesis_conversation`
  (`apps/automation/flows/flow_definitions.py`) declares `wait_timeout_minutes: 120`. Through 2.38.0 the stuck-run
  watchdog dead-lettered any run waiting over 30 minutes regardless, so a Genesis conversation idle between 30 and
  120 minutes was dead-lettered early. It now gets the 120 it declares. No code change; it is the behaviour the
  declaration always asked for.
- Inventory regenerated: unchanged.

## 2. FR-55

Released in 2.39.0, all three asks: (b) `prior_state`, (a) `await_event_for` (a timed-out wait resumes, returning
`{"timed_out": true, …}`), (c) answered by (a). The register's heading now reads 🟡 shipped. **It closes on our
report of a ported loop**: the Resolution Check as one `.nd` that asks a batch, saves progress, and sleeps between
batches, reporting iterations parked and resumed and any wake outside the ~15 s window. That port is a piece of work
of its own, not part of this adoption. The handoff's traps, kept for it: a distinct event name per iteration; `0i`,
not `0`; work before a wait runs again on every resume, so external calls go after the `prior_state` check.

**Ported in #635 (`apps/masterplan/nodus/resolution_check_v1.nd`), closed 2026-11-25** on its first real run, the
weekly check of 2026-11-23 07:30Z: resolution run `1052e284…`, driver `nodus`, flow run `bf1f6c71…`
(`nodus_execute`, `success`), 07:30:26Z to 07:38:22Z. The Python driver took 5:51 to 8:43 on the five Mondays before.

| Wait | Parked | Deadline | Queued (after deadline) | Resumed |
|---|---|---|---|---|
| `wait.0` (1 s, the first yield) | 07:30:26.9 | 07:30:27.9 | 07:30:41.4 (+13.5 s) | 07:30:42.5 |
| `wait.1` (30 s) | 07:31:44.4 | 07:32:14.3 | 07:32:26.5 (+12.2 s) | 07:32:27.5 |
| `wait.2` (30 s) | 07:33:27.2 | 07:33:57.2 | 07:34:11.4 (+14.3 s) | 07:34:12.5 |
| `wait.3` (30 s) | 07:35:27.2 | 07:35:57.1 | 07:36:11.4 (+14.3 s) | 07:36:12.5 |
| `wait.4` (30 s) | 07:37:26.2 | 07:37:56.1 | 07:37:56.4 (+0.3 s) | 07:37:57.5 |

- **Parked 5, resumed 5**, each with `{"timed_out": true}`; every wake was queued on the scheduler's next 15 s poll
  after its deadline, and resumed about 1 s later. None outside the window.
- **`prior_state` held across every resume:** five `sys.v1.resolution.update_run` calls, one per batch, and 27
  answers for 9 questions × 3 engines, 27 distinct: no batch asked twice.
- **No `nodus.fallback` event** since the adoption, so the Python driver never took over.

## 3. The scoped-traces question (2.34.0 record §6)

Answered by DEC-137: a scoped graph keeps edges to the caller's own events outside the trace, as dangling edges;
edges to another user's or a userless event are still dropped (FR-60 stands). Expected for `d534a3fd…` read as its
owner: 584 nodes, 583 edges, depth unchanged. **Read live 2026-11-23: 584 / 583, closed** (§5).

## 4. FR-6

Items 2–3 shipped in 2.0.0 (#337, #338, our option (a)); the runtime closed FR-6 on 2026-11-04 and told us in the
2.40.0 handoff. Closed in our register on 2026-11-22.

## 5. Live

**Live 2026-11-23 04:10:16Z** on image `7b495c900fa1` (#633, `dac630e`). `/health` 200 at 04:10:53Z, `restarts=0`,
postgres 0 reinitialisations, `default-apps` with 16 plugins.

The first build attempt was stopped for host memory (7.7 GB, 0.8 GB free) with `api` and `mcp` already down. Stopping
Vite (1.0 GB after running since sign-in) and dropping the WSL VM's page cache let the second attempt finish in
2.2 minutes; Vite restarted from its sign-in task afterwards. The api was down from about 03:56Z to 04:10Z.

| Check | Result |
|---|---|
| Confirm lines (all three handoffs), from the container | `2.41.0 5.17.0 3.57.0 2.16.2 2592000 True ['/usr/local/lib/python3.11/site-packages/AINDY']`: runtime, nodus-lang, openai, httpx2, `MAX_WAIT_SECONDS`, `memory.nd` packaged, site-packages |
| Schema heads | runtime `0022`, app `dt1directing0001 (head)`: no schema step, as stated |
| The entrypoint's first step | `[ensure_pgvector] extension 'vector' already present` |
| FR-6's routes | `/auth/password/change`, `/auth/password/forgot`, `/auth/password/reset` all in `/openapi.json` (not exercised: forgot sends a real mail) |

**The trace question, closed.** `get_trace_graph` read in-container for `d534a3fd-0133-45c6-8d6a-ba9e1a6b4718`
(read-only, rolled back):

| | Nodes | Edges | Dangling |
|---|---|---|---|
| Unscoped | 584 | 583 | 290 |
| Scoped to its owner, on 2.34.0 | 584 | 293 | |
| **Scoped to its owner, now** | **584** | **583** | 290 (all `async_child` to the owner's own events in other traces) |

As DEC-137 says: the scoped graph now keeps the caller's own cross-trace edges as dangling edges, and the far events
are not added as nodes. Depth was not re-read (the service function does not return it; the handoff says it does not
change).

**Counters, the 2.38.0 window** (11-19 05:22:14Z → 11-23 03:55:04Z, read before the build): 0 identity mismatches,
0 `tenant_mismatch`, 276 gated effects (`reserved`). The 2.41.0 window opens at 04:10:16Z.
