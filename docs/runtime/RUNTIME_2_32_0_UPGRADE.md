---
title: "Runtime 2.32.0 adoption (with 2.31.6)"
last_verified: "2026-11-08"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.32.0 adoption (with 2.31.6)

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.31.6.md` (tag `v2.31.6`, #919) and `APP_HANDOFF_v2.32.0.md` (tag
`v2.32.0`, #924). We come from 2.31.5, live since 2026-11-08 00:57:50Z (`RUNTIME_2_31_5_UPGRADE.md`), and go straight
to 2.32.0, as its handoff says. No ui-kit release (2.1.1 stays). No dependency pin of ours moves.

Between them the two releases answer all four FRs we filed on 11-07 and 11-08: **FR-57, FR-58 and FR-60 in 2.31.6,
and the runtime half of FR-59 in 2.32.0.**

Pin: `constraints.txt` `aindy-runtime==2.32.0`, floor `>=2.32.0,<3.0`, moved together
(`test_runtime_dependency_contract.py`).

## 0. Schema step: runtime head `0020` → `0021`

2.32.0 adds one table, `user_provider_keys`, and moves the schema contract `2026-09-20` → `2026-11-08`. Nothing
existing changes. Our entrypoint stops on exit 3 because `AINDY_BOOTSTRAP_RECONCILE` is off in compose (on purpose:
a schema change is a decision). So the first boot on the new image stops, we run
`docker exec <api> aindy-runtime bootstrap-schema --reconcile` once, and start again. App head stays `rt3answers0001`.

**Live:** owed after the merge (§7).

## 1. Registration is closed (FR-57, 2.31.6, DEC-120)

`docker-compose.prod.yml` sets `AINDY_REGISTRATION: "${AINDY_REGISTRATION:-closed}"`, which is what FR-57 said we
would do. `POST /auth/register` still answers 202 with the same body and timing, and creates nothing, sends nothing.
Login, password reset and the four existing accounts are unchanged.

- **CI is unaffected.** No workflow runs compose; the in-process tests and `serve-run-completion.yml` keep the default
  `open`.
- **The live smoke scripts** (`scripts/smoke_*.py`, `scripts/live_integration_test.py`) register a fresh account. Against
  this stack they now need `AINDY_REGISTRATION=open` in `.env` and an api recreate, then back to closed. Or point them at
  the designated test account.
- **The client's sign-up page** still shows its "check your email" answer, because the 202 is identical on purpose.
- **Not built upstream:** invite tokens (FR-57 step 2). We have no use for them yet.

The loopback bind (#544) stays: the remaining reasons for it are the open sweep items, not registration.

**Live:** a register request answers 202 and creates no row; owed after the merge (§7).

## 2. `/db/verify` needs an operator (FR-58, 2.31.6, DEC-120)

The check is on the runtime's router, so our mount in `apps/rippletrace/bootstrap.py` has it too. Nothing of ours
calls it: no client, app, script or test reference. We keep the mount, since it is now an operator diagnostic with an
operator check, which is what we asked for.

## 3. Trace helpers scoped to the caller (FR-60, 2.31.6)

`build_trace_graph`, `detect_root_event`, `detect_terminal_events` and `calculate_trace_span` take `user_id`. **Ours:**
`apps/rippletrace/services/rippletrace_service.py` threads it through every wrapper (`get_trace_graph`,
`calculate_ripple_span`, `detect_dominant_path`, `detect_failure_clusters`, `generate_trace_insights`), and
`GET /apps/rippletrace/{trace_id}` passes the caller. A trace that touches another user's events now shows only yours.
`test_rippletrace_causality.py` checks both halves: the owner sees the whole graph, a stranger sees no node, root, span
or path.

The registered flow symbols (`rippletrace_build_trace_graph` and the rest) keep their signatures with `user_id`
optional, so existing callers are unchanged.

## 4. Memory nodes saved without a path (2.31.6, DEC-119)

New owned nodes written without a path now store `/memory/{user}/_legacy/{memory_type}/{id}`, the path readers were
already shown. The existing rows need `aindy-runtime memory backfill-paths` (dry run), then `--yes`.

**Live:** both counts, and a `memory.tree` on the owner's `/memory/<id>/**` (about 1,397 nodes expected, not 26), owed
after the merge (§7).

## 5. Per-user provider keys (FR-59, 2.32.0, DEC-121): the runtime half

- **What's there:** `/auth/provider-keys` lets a signed-in session store its own keys (openai, anthropic, deepseek,
  azure_openai, perplexity), write-only, AES-GCM sealed under `AINDY_SECRET_PROVIDER_KEY_ENCRYPTION_KEYS`.
  `AINDY_PROVIDER_KEYS=per_user` makes a user's own key pay, the operator stays on the server's keys, and anyone else
  without a key gets `ProviderKeyRequired` before any call. A refused key is never retried on the server's key.
- **What we set:** nothing. `AINDY_PROVIDER_KEYS` stays unset (`server`), so every call pays as before, and no master key
  is set, so a `PUT` answers 503. The planner pays as before.
- **Metric:** `aindy_llm_key_source_total{provider,key_source}` counts whose key paid. On this stack it should read
  `server` only.

**Phase 3 is ours, and not in this PR:** route our ~25 paid call sites through `get_llm_client_for_user` /
`resolve_provider_key`, handle `ProviderKeyRequired` ("add your key in Settings") and `ProviderKeyRejected` ("your key
was refused") without ever falling back to the server's key, add a Settings card, then set a master key and flip
`per_user`. The runtime asks to read our call-site routing on a branch before we flip.

## 6. Tests on 2.32.0

The full app-profile suite and every CI check, locally on 2.32.0. Results in the PR body.

## 7. Live, after the merge

1. Read the identity counter and `tenant_mismatch` before the recreate.
2. Rebuild, recreate; the first boot stops on exit 3; run `bootstrap-schema --reconcile` once; start again. Check
   `alembic_version_runtime` reads `0021`.
3. The handoff's check: `2.32.0 [...site-packages/AINDY]`.
4. `memory backfill-paths`, then `--yes`; report both counts and the `memory.tree` size.
5. A register request answers 202 and adds no `users` row.
6. A trace graph for one of the owner's traces is unchanged in size.
7. `aindy_llm_key_source_total` shows only `server`.
