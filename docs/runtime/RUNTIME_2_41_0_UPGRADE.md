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

## 3. The scoped-traces question (2.34.0 record §6)

Answered by DEC-137: a scoped graph keeps edges to the caller's own events outside the trace, as dangling edges;
edges to another user's or a userless event are still dropped (FR-60 stands). Expected for `d534a3fd…` read as its
owner: 584 nodes, 583 edges, depth unchanged. Result: §5.

## 4. FR-6

Items 2–3 shipped in 2.0.0 (#337, #338, our option (a)); the runtime closed FR-6 on 2026-11-04 and told us in the
2.40.0 handoff. Closed in our register on 2026-11-22.

## 5. Live

Pending the rebuild.
