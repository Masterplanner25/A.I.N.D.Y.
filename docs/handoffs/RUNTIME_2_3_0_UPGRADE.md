---
title: "Upgrading to aindy-runtime 2.3.0"
last_verified: "2026-08-16"
api_version: "1.0"
status: current
owner: "platform-team"
---

# Upgrading to `aindy-runtime==2.3.0`

**Released 2026-08-16.** Floor moved to `>=2.3.0,<3.0`.

Three of our own filings land in this release: **FR-16 shipped**, **FR-14 half-closed with the
recurrence guard we said was missing**, and the **scope model we specified is now enforcing**.

---

## TL;DR

| | Action |
|---|---|
| Version pin | **Moved** to `>=2.3.0,<3.0` |
| **JWT scope enforcement — now ON** | **Verify, don't assume** — §1. Escape hatch exists |
| `nodus-lang` 4.2.0 | **Unblocked.** Arrives with the runtime; FR-16 closed |
| `bootstrap-schema` exit codes | **Entrypoint updated** to branch on them — §3 |
| Schema / migrations | **None.** Contract `2026-08-15.1`, head `0016`, both unchanged |
| Soak flags | A ranked list arrived (§5). One recommendation, one refusal |

---

## 1. The behaviour change: JWT sessions are no longer exempt from scope checks

`enforce_api_key_scope` gated API-key callers only — its docstring said *"JWT users carry full
trust and are never gated"* — so **an interactive browser session was strictly more privileged
than any API key.** That is closed.

| Class | Scopes |
|---|---|
| Ordinary session | `flow.read`, `flow.execute`, `memory.read`, `memory.write`, `agent.run`, `execution.read` |
| Admin session | the above **+** `webhook.manage`, `platform.admin` |

**This is the surface we supplied**, derived from the client's real call sites rather than from
preference — so it should be a no-op here. Two design points we asked for are honoured:
authority derives from **`User.is_admin` per request** (nothing encoded in the token, so no
session is invalidated and a promotion takes effect on the next call), and nothing pretends to
answer data ownership — `execution.read` still means *may I read executions*, not *whose*.

**Why it ships enforcing rather than default-off:** only **7 of 147** route decorators enforce a
scope at all, and the three they require are all in the ordinary set, so every signed-in user
passes every enforcing route. A test upstream fails if anyone adds an enforcement an ordinary
session cannot satisfy.

> **Verify rather than assume.** The reasoning is sound and it is our own scope list, but this is
> the one change in the release that can produce scattered 403s across unrelated screens — the
> exact failure shape we warned about when answering §6. Escape hatch:
> `AINDY_JWT_SCOPE_ENFORCEMENT=0`. Deliberately **not** set here; if it were needed, the right
> response is to find out which route and why.

---

## 2. FR-16 — closed

`Requires-Dist: nodus-lang==4.2.0`. Confirmed locally: upgrading the runtime pulled
`nodus-lang-4.2.0` in the same transaction.

The pin stays **exact**, which is the right call for a language runtime and is why prompt bumping
is the obligation instead. Worth recording that the runtime team reproduced our exact block (an
editable install *downgraded* 4.2.0 back to 4.1.0) rather than taking the report on faith.

They also ran a check we did not think to ask for: because `GUEST-CONFINE-1` makes guest
confinement depend on **VM constructor arguments**, a silently renamed argument in the language
bump would leave the guest unconfined while every VM-mocking test still passed. Verified against
the real VM — all three flags present, all 31 gated builtins still refused.

**Our `#376` question remains open and they explicitly did not answer it.** The resume-path fixes
in 4.2.0 present as *"`ok: true` with the result keys missing"*, which matches
`run_reasoning_apply` returning `{'data': {}}` — a signature we attributed to the Nodus 45s hard
limit. **Now re-testable**, and worth doing before treating the 45s note as complete.

---

## 3. FR-14 — half closed, and our entrypoint now uses it

`bootstrap-schema` exits with **branchable codes**:

| Exit | Meaning | Automatable |
|---|---|---|
| `0` | success | — |
| `1` / `2` | configuration error / db-layer import failure | no |
| **`3`** | **additive reconcile required** | **yes** — adds, never drops |
| `4` | offline migration required | no — **wins over 3** when both apply |
| `5` | manual repair required | no |

Before this, every one of these was exit `1`, so an entrypoint could not distinguish "add two
nullable columns" from "your database is broken". That is what made the 2.1.0 adoption a crash
loop.

**`docker/entrypoint.sh` now branches on the code.** `AINDY_BOOTSTRAP_RECONCILE` still gates
whether exit 3 is *applied* automatically — the runtime certifies 3 as safe to automate, so
defaulting it on would now be defensible, and we keep it opt-in so a production schema change
stays a decision rather than a side effect of a restart. What changed is that the refusal is
**precise**: exit 3 prints exactly what to do, and 4/5 no longer masquerade as something a flag
could fix.

**The recurrence guard we said was missing also shipped.** A CI job installs the *previous*
released wheel, builds its schema, installs the new build over that database, and requires
success or exit 3 — the state our own `deploy-bootstrap-guard.yml` structurally could not reach,
for the reason we identified (it only ever boots a fresh database).

> **Note how they handled the same trap we fell into.** That guard passes trivially on a release
> with no schema change, where a broken guard and a clean release look identical — so it ships
> with a **negative-control job** that injects synthetic drift and requires detection, verified
> from logs rather than a green tick. That is the discipline our soak audit concluded we lacked:
> a passing check on degenerate input proves nothing.

**Still open:** the entrypoint-pattern half — the runtime's own scaffold still recommends the bare
form.

---

## 4. Data we can give them: `AINDY_CHILD_CONTEXT_CLAMP`

They flagged this as **do not enable**, naming our file, and they are right. Measured here:

- **One** `child_context` call site in the entire app —
  `apps/automation/syscalls/syscall_handlers.py:45`, inside `_dispatch_owner_syscall`
- **19 call sites** route through that one helper
- **19 distinct capabilities**: `analytics.read`, `arm.analyze`, `arm.generate`, `arm.store`,
  `authorship.read`, `genesis.execute_llm`, `goal.create`, `leadgen.search`, `leadgen.search_ai`,
  `leadgen.store`, `research.query`, `rippletrace.read`, `score.recalculate`, `task.complete`,
  `task.complete_full`, `task.create`, `task.orchestrate`, `task.pause`, `task.start`

The helper builds a child granting the *nested* syscall's capability while the parent holds only
the *outer* one, so a clamp intersects to empty and denies calls that work today.

**Better than the log data they asked for:** the blast radius is not "how often does this happen"
but "every automation-triggered syscall, always, by construction." The upside is that it is
**one function** — so the fix has exactly one site, once the caller has a legitimate grant.

Their WARNING-on-widening will confirm this from live traffic; the count above is the static
answer and it is available now.

---

## 5. The soak list (§6) — our position

They sent a ranked list of every runtime flag waiting on real traffic, with an honest readiness
call on each. Our reading:

**Recommended first — `AINDY_ASYNC_HEAVY_EXECUTION`.** The remaining half of our own FR-15, and
2.2.0 shipped `scheduler.queued` specifically so the before/after is measurable. Wired in compose,
still default off. The evaluation is a deliberate session: reproduce the Genesis burst, flip,
reproduce, compare queue waits.

**Cheapest win — `AINDY_NODUS_WARM_POOL`.** Falls back to a fresh subprocess on any fault, so
worst case is today's behaviour, against a ~12s cold start. `AINDY_NODUS_WARM_PREWARM` only
matters with it on.

**Also low-risk and additive:** `AINDY_MEMORY_RECALL_OWN_SESSION`, `AINDY_PLANNER_MEMORY_INJECTION`,
`AINDY_ASYNC_JOB_LOOP_CLOSURE`.

**Not yet, on our own reasoning rather than theirs:** anything in the *effect semantics* group
(`AINDY_SYSCALL_IDEMPOTENCY`, `AINDY_TOOL_IDEMPOTENCY`, `AINDY_NEXT_ACTION_ACTING`,
`AINDY_AUTONOMOUS_EXECUTE_WINDOW`). The soak audit's finding applies directly: **this deployment
does not currently generate enough varied traffic for a soak to mean anything**, and flags that
change whether a retry re-executes deserve real usage, not an idle stack.

**Refused for now:** `AINDY_CHILD_CONTEXT_CLAMP` — §4.

---

## 6. Verification performed

| Check | Result |
|---|---|
| Boot smoke on 2.3.0 | see §7 |
| Contract / boundary / model / chunking tests | 61 passed |
| `ruff check apps/ tests/` | clean |
| `nodus-lang` after upgrade | **4.2.0** |
| `bootstrap-schema --help` | exit codes 3/4/5 documented as described |
| `sh -n docker/entrypoint.sh` | syntax OK |

---

## 7. Open upstream after this release

- **`HTTP-SCOPE-GAP-1` remainder — the larger half.** 140 of 147 routes still enforce nothing, and
  `memory_router.py` reaches effects with zero dispatcher references. When enforcement widens,
  that handoff will name the scopes.
- **`FR-14`** — entrypoint-pattern half.
- **`IDEM-12`** — `agent.undo` re-invokes every compensator if called twice. Latent only because
  **zero compensators are registered**; it goes live the moment anyone registers the first.
- **`AUTHORITY-VALUE-1`** — beyond the clamp, `SyscallContext.capabilities` is still
  caller-constructible and absent identity *skips* the boundary rather than denying.
- **`TOOL-SEAM-ISOLATION-1`**, **`EXEC-ENV-BIND-1`**, **`FR-6` items 2+3**.

**Next available FR number: `FR-17`.**
