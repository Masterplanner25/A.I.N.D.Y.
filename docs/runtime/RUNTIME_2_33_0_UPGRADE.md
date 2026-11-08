---
title: "Runtime 2.33.0 adoption"
last_verified: "2026-11-08"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.33.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.33.0.md` (tag `v2.33.0`, #928). We come from 2.32.0, live since
2026-11-08 17:06:42Z and rebuilt for #566 at 17:57:24Z (`RUNTIME_2_32_0_UPGRADE.md`). The handoff's carried steps for
2.31.6 and 2.32.0 (the `0021` reconcile, the memory path backfill, `AINDY_REGISTRATION`, the trace helpers' `user_id`)
are done already: `RUNTIME_2_32_0_UPGRADE.md` §7. No schema step of its own (head stays `0021`), no ui-kit release
(2.1.1 stays).

Pin: `constraints.txt` `aindy-runtime==2.33.0`, floor `>=2.33.0,<3.0`, moved together
(`test_runtime_dependency_contract.py`). pgvector comes in with the wheel; we do not pin it.

## 1. pgvector 0.4.2 → 0.5.1

A stored embedding now reads back as a `list`, not a `numpy.ndarray`. **Ours:** no app code reads a stored embedding.
`apps/search/services/search_scoring.py` computes its own vectors from the embedding service, and every similarity
search (recall, `own_piece_links`, the cross-post dedup) goes through the runtime's DAO. numpy stays: two app modules
import it for their own arithmetic (`expectation_model_service.py`, `projection_service.py`), and the runtime still pins
it.

## 2. Memory expansion's similar half (MEM-EXPAND-DEAD-1, DEC-122)

`AINDY_MEMORY_EXPAND_SIMILAR` (default off) and `AINDY_MEMORY_EXPAND_MIN_SIMILARITY` (0.75). **We set neither.** We call
no expansion path: the client's only recall (`MemoryBrowser.jsx` via `recallMemory`) sends `expand_results: false`, and
nothing calls `POST /memory/nodes/expand`. So the planned default-on in the next release changes nothing for us either.
Recall with a query runs two fewer queries, with the same results.

## 3. Tests on 2.33.0

The full app-profile suite and every CI check, locally on 2.33.0 with pgvector 0.5.1. Results in the PR body.

## 4. Live, after the merge

1. Read the identity counter and `tenant_mismatch` before the recreate.
2. Rebuild (the pin moved, so the dependency layer downloads again), recreate. No reconcile: `0021` stays.
3. The handoff's check: `2.33.0 0.5.1 [...site-packages/AINDY]`.
4. A recall through the runtime returns the owner's published writing as before.
