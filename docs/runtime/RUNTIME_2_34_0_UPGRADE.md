---
title: "Runtime 2.34.0 adoption"
last_verified: "2026-11-08"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.34.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.34.0.md` (tag `v2.34.0`, #934). We come from 2.33.0, live since
2026-11-08 18:34:38Z (`RUNTIME_2_33_0_UPGRADE.md`). **It answers all four requests we filed on 2026-11-08: FR-61, FR-62,
FR-63 and FR-64.** No migration (head stays `0021`), no ui-kit release (2.1.1 stays).

Pin: `constraints.txt` `aindy-runtime==2.34.0`, floor `>=2.34.0,<3.0`, moved together
(`test_runtime_dependency_contract.py`).

## 1. FR-61: outbound-call events name their user (#931, DEC-123)

New `external.call.*` events record whose call they were: the call site's `user_id`, or the current request's caller.
The runtime's embedding job attributes its model call to the memory node's owner, which was the hub of trace
`d534a3fd…`. Since #566 our own paid calls pass the user to `perform_external_call` too.

Old events: `aindy-runtime events backfill-call-users` gives each one its trace's user, only when every other event in
that trace belongs to one user. **Live:** the dry run, `--yes`, and the re-read of `d534a3fd…` are owed after the merge
(§6).

## 2. FR-62: `memory backfill-paths --yes` works (#930)

Every database command now loads the models. We had already filled the paths in-process on 2.32.0 (1,721 nodes;
`RUNTIME_2_32_0_UPGRADE.md` §7), so a run now should find little or nothing. **Live:** owed after the merge (§6).

## 3. FR-63: key errors come out of the chat helpers as themselves (#930)

`chat_completion` and `chat_completion_deepseek` raise `ProviderKeyRejected` and `ProviderKeyRequired` directly, with no
cause cycle. `apps/_shared/provider_keys.key_problem` keeps walking the chain, bounded; it is now only a fallback.

## 4. FR-64: the run did not disappear live; the message did (#932, #933, DEC-124)

- **Their finding:** the runner commits the `FlowRun` when it starts, so a live run survives a handler that rolls back.
  Our "FlowRun … disappeared" came from `test_genesis_through_its_syscall_answers_402`, under the fixture where the app's
  and the test's sessions share one outer transaction. That test now never reaches the flow: the route's
  `require_key` answers the 402 first, so it does not depend on the fixture's rollback.
- **Fixed upstream:** a node out of retries now fails the run with its last error, so `raise_problem_in` finds the
  `HTTP_402:` sentence; and a failing runtime write handler rolls back only to its own savepoint (DEC-124).
- **Ours, fixed in this PR:** `_syscall_node` (in `automation/flows/flow_definitions.py`, `system_flows.py` and, a third
  copy the handoff did not name, `tasks/flows/tasks_flows.py`) turned every syscall error into `RETRY`, so a refused
  user key was tried three times. A key problem (`is_key_problem_text`: the `HTTP_402:` marker) is now `FAILURE`; any
  other error still retries. `test_a_flow_node_fails_a_key_problem_instead_of_retrying_it` covers all three.

## 5. Their review of FR-59 phase 3 (#566), and the notes

Sound, nothing blocking; recorded in `RUNTIME_2_32_0_UPGRADE.md` §10. Their three notes:

1. **`_count_key_source` is private:** we now import the public `count_key_source` (2.34.0).
2. **`resolution_engines._call` keeps up to 200 characters of a provider's error body:** `refused()` runs first, so a
   refused key is never echoed. The order stays.
3. **Embeddings stay on the server's key** (DEC-121 D4), as our routing assumes.

They asked that §4's two items be fixed before turning on `per_user`. `per_user` has been on here since 19:33:31Z: their
review reached us before this handoff did, and the `RETRY` mapping is fixed in this PR. Between 19:33Z and this release's
rebuild, a refused key inside a flow could have been tried three times. On this stack only the owner pays, and the owner
uses the server's key, so it could not happen here.

## 6. Live, 2026-11-08

From #574's merge (`2a4dee5`), image `ff06d67fe91c`, up healthy at **21:51:02Z**, no restarts.

1. **Counters before the recreate** (21:47Z): 0 identity mismatches, 0 `tenant_mismatch`; 2 OpenAI calls, both
   `key_source="server"` (the owner). Schema head `0021`; 0 stranded `executing` agent runs.
2. **The handoff's check:** `2.34.0 0.5.1 ['/usr/local/lib/python3.11/site-packages/AINDY']`.
3. **`events backfill-call-users`:**
   - **Before:** 28,600 userless `external.call.*` events.
   - **Dry run:** 10,966 would get their trace's user; 859 traces left alone with no user, 0 with more than one.
   - **`--yes`:** gave 10,966 events their trace's user in 13 batches.
   - **A second dry run finds nothing.**
   - **17,634 stay userless,** all in the 859 traces with no user at all (system work).
4. **`memory backfill-paths --yes`** now runs (FR-62): 0 to store, since we had filled all 1,721 on 2.32.0; 1,903 with
   no owner left alone.
5. **Trace `d534a3fd…`, re-read scoped to its owner:**

   | | Nodes | Edges | Depth |
   |---|---|---|---|
   | Unscoped | 584 | 583 | |
   | Scoped, on 2.32.0 | 582 | 291 | 1 |
   | Scoped, now | **584** | **293** | 1 |

   - **The nodes are fixed.** The trace has 0 userless events now; the two model-call events are kept.
   - **The edges are not, and the cause is narrower than FR-61.** The 290 edges still dropped are all `async_child`
     edges whose child is an `execution.started` event **in another trace**, and every one of those 290 events belongs to
     the same owner.
   - The unscoped graph keeps those edges, but not their far ends as nodes, so 290 of its 583 edges dangle. The scoped
     graph applies FR-60's rule, "edges whose ends both remain", and drops them.
   - **For the runtime:** should a scoped graph keep an edge to the caller's own event outside the trace (as a dangling
     edge, like the unscoped one, or with that event as a node)? Not filed as a request; reported here as asked.
