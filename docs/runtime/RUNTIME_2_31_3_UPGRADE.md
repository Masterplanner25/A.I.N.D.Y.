---
title: "Runtime 2.31.3 adoption"
last_verified: "2026-11-07"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.31.3 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.31.0.md` through `APP_HANDOFF_v2.31.3.md` (tag `v2.31.3`,
`0bd7e61`, #904). We come straight from 2.30.0 (live since 2026-11-04, `RUNTIME_2_30_0_UPGRADE.md`), so this
one record covers all four releases. No schema change (head stays `0020`, contract `2026-09-20`), no
dependency-pin change, no ui-kit release (2.1.1 stays).

**2.31.2 and 2.31.3 are security fixes.** Four users can sign in on this stack.

**Released through A.I.N.D.Y.:** 2.31.3 only. 2.31.0, 2.31.1 and 2.31.2 have no handoff row.

## 1. The email reply on 2.31.3 does not prove #535

The handoff was requested at 07:32:49Z on 2026-11-07 and reached the gate at 07:43:38Z. The owner replied
APPROVE at 07:44:26Z, the watcher saw it at 07:44:51Z, and the handoff was `done` at 07:46:26Z.

That was 00:44 on the account's clock (-07:00), so the UTC and local dates were both 11-07. #535 fixes the
case where they differ, which at -07:00 is a gate opened between 00:00Z and 07:00Z. **The code before #535
would have found this reply too.** It proves the email path again, not #535. A gate opened before
midnight local time still owes that proof.

## 2. Undo works (2.31.0, DEC-108..110)

**Ask confirmed, by a text search of `main` on 2026-11-07:** no caller of `sys.v1.agent.undo`, no
`compensate=` hook, no plan step declaring `expects`, no code reading `VERIFY_FAILED`, and
`AINDY_VERIFY_FAILED_AUTO_UNDO` is not set. Soak register row 8 reads "no declaring plan".

## 3. MCP grants the declared capability (2.31.1, DEC-112)

- **`memory.search`, `.tree` and `.trace` become reachable** through our launcher, which already listed them.
- **The launcher now assigns its allowlist.** It used `setdefault`, so an inherited `AINDY_MCP_SERVER_TOOLS`
  replaced the read-only list, and since DEC-112 a name like `sys.v1.memory.delete` would really delete. Nothing
  here sets that variable, so this closes a risk, not an incident. `test_mcp_read_access.py` covers it.
- **`work.context` and `work.facts` keep their capability names.** Nothing needs them to move. The comments
  now say why, and `test_mcp_read_access.py` no longer pins the old rule.

**`MEM-TRACE-SCOPE-1` (#897), ask 3, read 2026-11-07 on the 2.30.0 stack:**

| Query | Result |
|---|---|
| `memory_nodes` total / with a path | 3,661 / 77 |
| Node pairs that could have crossed users | **0** |

So no trace could have crossed users here. For `MEM-PATH-NULL-1`, 98% of our nodes have no path, so `tree`
and wildcard `list` will come back small.

**Ask 2 (a live MCP call) is owed after the rebuild** (§7).

## 4. Identity only from authentication (2.31.2, DEC-113)

The handoff names a background caller as the likeliest break: code acting for a user while dispatching as
another identity. **A text search of ours found none, and our routes take no `user_id` from a request body.**
The callers that forward a `user_id` pass the same user as the caller (`nodus_apply.py`, the identity services,
`network_bridge_services.py`, `tasks/syscalls`). A job over all users stays a Python loop that starts one run
per user, as `CLAUDE.md` already requires. This is a search, not proof; the counter is the proof (§7).

## 5. The agent registry's routes need an operator (2.31.3, DEC-114)

Five `/apps/coordination/agents*` routes answer 403 unless the caller is an operator. **Nothing of ours needs
them as a non-admin**, and `client/src` does not call them.

- **`docs/api/API_REFERENCE.md`:** the five routes and `/graph` now state the rule.
- **`scripts/smoke_autonomy.py`:** its coordination steps now need an admin login, and its own signup account
  is not one. It says so in its docstring. Nothing runs it automatically.

## 6. Tests on 2.31.3

- **Unit suite and `test_bootstrap_completeness.py`:** 1,730 passed, 1 failed, in a `--rm` container with 2.31.3
  installed. The failure, `test_genesis_turn_no_recalc.py::test_other_triggers_still_recalculate`, is that
  container having no `git` binary (`FileNotFoundError: 'git'`), not the runtime. CI has it.
- **No test failed with `TENANT_VIOLATION` or an unexpected 403.** Output from passing tests is not captured, so
  this says what failed, not what was logged.
- **CI on #539 was green.** It runs `tests -m app_profile`, which includes the `git` test above. **Nodus VM
  Integration** runs after merge, against a live stack, and passed on `main` at 08:09Z. Anything under
  `tests/integration` not marked `app_profile`, and not in that workflow, was not run.

## 7. Rebuild: done 2026-11-07

**We are on 2.31.3, live since 08:14:02Z on 2026-11-07.** This is the line the runtime's advisory waits for.

1. **Identity counter, window 12** (2026-11-04 07:13:27Z → 2026-11-07 08:13:40Z): no samples, so 0 refused,
   over 85 syscall outcomes on `/metrics`. 0 agent runs executing before the recreate.
2. **Rebuilt** (image `fefa37feac45`) and **recreated at 08:14:02Z**, which opens window 13. Healthy in about
   a minute, 0 restarts, `default-apps` with 16 plugins, an empty `AgentContinuation` log, 0 agent runs
   executing, and all 4 `.nd` workflows in site-packages. Runtime schema head `0020`, app head `rt1medium0001`.
3. **The handoff's check:**

   ```text
   $ docker exec <api> python -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
   2.31.3 ['/usr/local/lib/python3.11/site-packages/AINDY']
   ```

4. **Ask 2 of 2.31.1, a live MCP call on this build,** as the owner, from an `mcp` client inside the container:

   | Tool | Arguments | Status | Nodes |
   |---|---|---|---|
   | `nodus_memory_search` | a query | `success` | 5 |
   | `nodus_memory_tree` | `/memory/<user id>/**` | `success` | 26 |

   The owner has 1,397 nodes and 26 of them have a path, so `tree` returns exactly the nodes with a path. That
   is `MEM-PATH-NULL-1` as the handoff describes it. `nodus_work_context` also returned `success`, with 9 Works.
5. **The launcher's allowlist, live:** the same client started the launcher with
   `AINDY_MCP_SERVER_TOOLS=sys.v1.memory.delete` set. It listed its seven read tools and no delete.
6. **No log line** says `TENANT_VIOLATION`, `ignoring agent run state`, `belongs to another user` or `does not
   belong to this run`. That covers boot only, so it is not the day-of-traffic check below.

## 8. Identity window 13, closed early

**Window 13** (2026-11-07 08:14:02Z → 15:43:06Z): no samples, so 0 refused, over 1 syscall outcome on `/metrics`
(`sys.v1.nodus.execute`). None of the log lines in §7 appeared, and 0 agent runs were executing. The stack came
down at that reading to free room on the host for another release. About 7.5 hours and one syscall say very
little, so **this is not the day-of-traffic read.**

**Window 14** opened at 20:05:42Z the same day, on image `f894b90acb1b` (runtime 2.31.3, `main` through #542,
app schema head `fl1metrics0001`).

## 9. Identity window 14, closed by the port change

**Window 14** (2026-11-07 20:05:42Z → 21:52Z): no samples, so 0 refused, over 59 syscall outcomes on `/metrics`,
all `success`. The api was recreated at 21:52:53Z to bind its port to `127.0.0.1` (the owner uses the stack from this laptop only), which opens **window
15** on the same image. The old container's log was not searched for the §7 lines before it was replaced, and
under 2 hours of traffic is still not a day, so **this is not the day-of-traffic read either.**

**Still owed:**

- **After a day of normal traffic, from about 2026-11-08 21:53Z (ask 3 of 2.31.2):**
  `aindy_payload_identity_mismatch_total` by `syscall`, and those same log lines.
- **#535:** a gate opened before midnight local time (§1).
