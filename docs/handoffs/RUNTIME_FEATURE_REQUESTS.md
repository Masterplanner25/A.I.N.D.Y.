---
title: "Runtime Feature Requests — handoff to aindy-runtime"
last_verified: "2026-08-01"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime Feature Requests — handoff to `aindy-runtime`

## ✅ CLOSED in aindy-runtime 1.10.2 — RT-MEMTXN-LEAK-1 (verified app-side on the real wheel)

**Filed 2026-07-19; closed 2026-07-19 on `aindy-runtime==1.10.2`.** Verified against the
published wheel (api image rebuilt `--no-cache`, not a hot-patch), native-Linux stack.

| Measure | 1.10.1 | **1.10.2** |
|---|---|---|
| `POST /auth/login` | 41.9s | **0.45s** |
| `POST /auth/register` | 45.4s | **0.56s** |
| Peak idle-in-transaction on `memory_nodes` | 60 | **1** |
| `MemoryNodeDAO.recall()` reads the table | — | **yes — 18 scans, 1 held conn** |

**Sign-in is now ~93× faster and far under the 30s browser timeout. The dynamic frontend
walkthrough is UNBLOCKED.**

**How "fixed" was distinguished from "recall silently stopped running":** a fast login alone is
NOT evidence — "too fast to sample" and "never ran" look identical to a sampler. Resolved with a
sampling-independent counter: `pg_stat_user_tables` cumulative scans on `memory_nodes`, measured
before/after, plus a direct `MemoryNodeDAO.recall()` invocation. recall() executed the real path
(observable OpenAI embedding round-trip), scanned the table, and held **1** connection instead of
60. Read path is functional; it simply no longer holds transactions open.

**Observation for the runtime team (FYI, not a defect):** on 1.10.2 a login now performs
**~0 `memory_nodes` scans**, down from 60. Consistent with the fix having eliminated an N+1
per-node re-read rather than merely batching it. Flagging only so the change in read volume is
intentional and not a surprise.

### Historical record — why this took three releases

Each fix removed one "slow external call inside an open transaction" site and unmasked the next:

- **1.10.0** — memory recall's embedding. Fixed post-request *lingering* (connections drain at
  request end). Partial; within-request fan-out remained.
- **1.10.1** — the embedding job's post-commit refresh. Verified app-side as **still broken**:
  login 41.9s, 60/60 connections `idle in transaction` on `memory_nodes`, every one with
  `xact_age_s == idle_s`.
- **1.10.2** — the third site, in the recall read path itself. **Closed.**

**Verification lesson worth keeping:** sample `pg_stat_activity` **mid-request**. From 1.10.0
onward a post-request sample looks clean even while the leak is present — that is exactly what
made 1.10.0 look fully fixed. Repro/verify scripts: `scratchpad/memtxn_*.sh`.

<details>
<summary>Prior diagnosis retained (1.10.1, third site confirmed)</summary>

**Verdict at the time: a third leak site exists.** Measured on `aindy-runtime==1.10.1`
(native-Linux stack, native `docker.io` in WSL2, pgvector/pg16): **`POST /auth/login` = 41.9s**,
`/auth/register` = 45.4s. Both over the 30s browser timeout, so a real user could not sign in.

### Fresh mid-request snapshot (t+18s into `/auth/login`, on 1.10.1)

```
 count |        state        | wait_event_type | xact_age_s | idle_s | query
-------+---------------------+-----------------+------------+--------+---------------------------------
     1 | idle in transaction | Client          |       17.9 |   17.9 | SELECT memory_nodes.id, memory_nodes.content, …
     1 | idle in transaction | Client          |       17.8 |   17.8 | SELECT memory_nodes.id, memory_nodes.content, …
     1 | idle in transaction | Client          |       17.6 |   17.6 | SELECT memory_nodes.id, memory_nodes.content, …
     …  (60 rows, ages fanned 10.8s → 18.1s, none closing)
```

**Rollup — the fingerprint is 100% present:**
```
        state        | conns | xact_age_eq_idle | min_xact_s | max_xact_s
---------------------+-------+------------------+------------+------------
 idle in transaction |    60 |               60 |       10.8 |       18.1
```
**60 of 60** connections have `xact_age_s == idle_s`, all `wait_event_type=Client`, and all 60
are running the **same single query**:
```
SELECT memory_nodes.id, memory_nodes.content, memory_nodes.tags, memory_nodes.node_type,
       memory_nodes.source, memory_nodes.source_agent, memory_nodes.is_shared,
       memory_nodes.visibility, memory_nodes.u…
```

### Concurrency profile over the request
`idle in transaction` climbs 0 → 60 in ~7s, **plateaus at exactly 60 for ~33s** (t+7s→t+39s —
that flat ceiling is pool exhaustion), then drains 60 → 0 in ~6s once the request ends. The
drain is 1.10.0's fix working correctly; the plateau is the unfixed part.

### What this rules in / out
- **Not the post-request lingering** — that drains correctly (1.10.0 holds).
- **Not the embedding-job post-commit refresh** — 1.10.1 is installed and the shape is unchanged.
- **It is the recall read path itself.** Each connection opens a transaction, runs exactly one
  `memory_nodes` SELECT, then sits idle-in-transaction for that transaction's whole life. 60
  concurrent such transactions are held open across the request instead of being committed and
  returned per read.

**Corpus note (may matter for repro):** this DB has 1246 `memory_nodes`, of which **1239 have
`user_id IS NULL`** (global) and 7 are user-owned. The fan-out reproduces on a brand-new account
with **zero owned nodes**, so the recall is reading the global corpus — a fresh-account repro is
sufficient, no seeded user memory required.

**Repro (self-contained, in this repo):** `scratchpad/memtxn_probe.sh` (registers a throwaway
account, fires login, samples every 1s) and `scratchpad/memtxn_snapshot.sh` (captures the
mid-request fingerprint table above). Note the sampling must happen **mid-request** — a
post-request sample looks clean even while the leak is present, which is the trap that made
1.10.0 look fully fixed.

**What 1.10.0 fixed (confirmed app-side):** the post-request *lingering*. Leaked
idle-in-transaction connections now **drain when the request completes** — after a login,
`idle in transaction` drops back to ~2 (was lingering until the 120s idle-timeout reaped them).

**What 1.10.1 targets:** the **within-request fan-out** measured on 1.10.0 — a single
`POST /auth/login` opened **30+ concurrent** `SELECT memory_nodes …` transactions each sitting
`idle in transaction` (`wait_event_type=Client`) until the request ended → pool exhaustion →
login ~45s, over the 30s client timeout.

**Snapshot that drove the 1.10.1 fix (mid-login, on 1.10.0):**
```
count | wait_event_type | xact_age_s | idle_s | query
------+-----------------+------------+--------+--------------------------------
    2 | Client          |    6.2     |   6.2  | SELECT memory_nodes.id, memory_nodes.content, …
    2 | Client          |    5.3     |   5.3  | SELECT memory_nodes.id, memory_nodes.content, …
    2 | Client          |    4.9     |   4.9  | …   (30+ total, climbing through the login)
```
**Decisive signal: `xact_age_s == idle_s` on every row** — each connection opened a transaction,
ran exactly one `memory_nodes` SELECT, then went idle-in-transaction for the *whole* transaction.
The recall fans out per-node (or per-batch) reads onto separate connections and holds each
transaction open across the whole recall/request instead of committing/closing per read. Fix
direction: commit/close (or use a single connection / read-only autocommit) per memory read so a
recall doesn't hold N concurrent open transactions. Original diagnosis retained below.

### Impact (user-facing)
A single `POST /auth/login` (also `/auth/register`, and any memory-touching request) takes
**~40 seconds** on an otherwise-healthy native-Linux stack (native `docker.io`, real
OPENAI/ANTHROPIC keys, Claude planner default). The web client's request timeout is **30s**,
so **a real user cannot sign in** — the browser aborts before the backend responds. (The
account/session *does* get created server-side ~40s in, after the client gave up.) Every
dynamic surface is unusable through the UI. **Backend testing masked this** because curl just
waits the 40s; a browser can't.

### Root cause (diagnosed via `pg_stat_activity`, not speculated)
Snapshot taken mid-login on an otherwise-idle stack:

```
count | state                | wait_event_type | query
------+----------------------+-----------------+------------------------------------------
   61 | idle in transaction  | Client          | SELECT memory_nodes.id, memory_nodes.content, memory_nodes.tags, …
    1 | idle in transaction  | Client          | SELECT system_events.id …
```

A single login opens **~60–85 connections** that each run a `SELECT memory_nodes …` and then
sit **`idle in transaction`** with **`wait_event_type=Client`** — i.e. the runtime opened a
transaction, ran the read, and **never committed / rolled-back / closed the session**, so
Postgres holds the connection open waiting for a client command that never arrives. These
leaked connections exhaust the SQLAlchemy pool; the rest of the request then waits the full
30s `pool_timeout`, and embedding-enqueue writes fail with `QueuePool limit … reached`. Net:
~40s per request. **At rest the pool is fine** (~20 idle, 0 active) — so it is the memory
*read* path leaking **per request**, not steady-state saturation.

### Suspected code path
The memory recall/read layer — `AINDY/memory/bridge.py::recall_memories`,
`AINDY/memory/memory_scoring_service.py::get_relevant_memories`,
`AINDY/memory/nodus_memory_bridge.py::recall*` — reads `memory_nodes` on a session that isn't
committed/returned to the pool. The exact trigger on the auth path (memory recall on login /
`bootIdentity` / a post-auth event) is for the runtime team to trace; the leaked query is
unambiguously the `memory_nodes` SELECT, and the `wait_event_type=Client` state is the
abandoned-open-transaction signature.

### Not app-fixable via config (attempts, for the record)
- **Pool bump** 60 → 85 (`DB_POOL_SIZE=40`/`DB_MAX_OVERFLOW=45`, under Postgres
  `max_connections=100`): still fully exhausts — the fan-out just grows to the new ceiling.
- **Idle-in-transaction reap** `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` → 5000: *worse* — reaping
  mid-flight causes rollback/retry churn. (The app had raised this to 120000 for the nodus
  cold-start work, which *lengthens* how long these leaked connections linger — but a real fix
  must stop the leak, not tune the reaper.)

### Proposed fix direction (runtime)
Ensure every memory-node read runs inside a scoped session that is committed/closed (or a
read-only/autocommit connection returned to the pool immediately) — nothing left
`idle in transaction`. E.g. a `with session_scope(): …` wrapper (or an explicit
`db.rollback()` after read-only work), and/or routing recall through a single connection
instead of a per-node fan-out.

### Relation to existing items
Sibling of **NODUS-WARMPOOL-1** (apps-monolith `TECH_DEBT.md`): that is the embedding-*write*
fan-out exhausting the pool during agent execution; this is the memory-*read* transaction leak
exhausting it on auth. Same memory/DB-session-management surface — likely worth fixing together.

### Repro
1. Boot app-profile on a native-Linux stack (Postgres, real model keys).
2. `POST /auth/login` with valid creds; time it (~40s).
3. Mid-request: `SELECT count(*), state, wait_event_type FROM pg_stat_activity WHERE
   datname='aindy' AND state='idle in transaction' GROUP BY 2,3;` → ~60–85 rows on the
   `memory_nodes` SELECT with `wait_event_type=Client`.

</details>

---

## Shipped in aindy-runtime v1.8.0 (2026-07-18) — now an adoption tracker

**All four items are now delivered upstream** (FR-2 was already present; v1.8.0 shipped
FR-1, FR-3, FR-4). This doc flips from a *request* handoff to an *adoption* tracker. What
v1.8.0 shipped (additive/opt-in, no schema change):

- **FR-1** — `register_connector` hook + capability-enforced outbound boundary.
- **FR-3** — `NEXT_ACTION_DISPATCHED` dispatch-outcome contract.
- **FR-4 / DOCS-BUCKET-A-1** — `ERROR_HANDLING_POLICY` runtime/app split (closed).
- Plus: `setuptools>=83.0.0` (CVE-2026-59890), `nodus-lang 4.1.0`, `nltk 3.10.0`.

App floor raised to `aindy-runtime>=1.8.0,<2.0` (boot smoke green: `default-apps`,
`app_plugins_loaded=True`, `app_plugin_count=17`).

> **FR-5 shipped in aindy-runtime 1.9.0 (2026-07-18) and is ADOPTED.** `run_nodus_workflow` now takes a
> `capability_token` (so `call_tool` steps can be granted capabilities) **and** the VM's `sys()`
> resolves app-registered syscalls. Floor raised to `>=1.9.0`. App adoption done: reasoning-apply
> routes through the Nodus VM via `sys("sys.v1.analytics.get_reasoning_recommendation", …)`,
> flag-gated `AINDY_REASONING_NODUS_NATIVE` (default off) — `apps/analytics/services/reasoning/nodus_apply.py`;
> `APP-DEBT-MIGRATED-1` Nodus-native reasoning row RESOLVED. Detail below.

**App-side adoption status (FR-1…4):**

| ID | Upstream | App adoption |
|---|---|---|
| FR-1 | ✅ 1.8.0 (`register_connector`) | ✅ adopted (2026-07-18) — `if/elif` ladder replaced by `register_automation_connectors` + `dispatch_connector`; `ctx.call` for egress (`MASTERPLAN-CONNECTOR-RUNTIME-1` RESOLVED) |
| FR-3 | ✅ 1.8.0 (`NEXT_ACTION_DISPATCHED`) | ✅ read adopted (2026-07-18) — `apps/agent/agents/next_action_outcomes.py` + `GET /apps/agent/next-action/outcomes`; remaining is ops-only: soak + flip `AINDY_NEXT_ACTION_ACTING` |
| FR-2 | ✅ 1.7.0 | ✅ adopted — `reasoning_apply_v1.nd` registered at boot (see TECH_DEBT) |
| FR-4 | ✅ 1.8.0 | ✅ adopted (2026-07-18) — reciprocal cross-links updated (GOVERNANCE_INDEX L0, INVARIANTS runtime-half pointer, EVOLUTION_PLAN preamble); `DOCS-MIGRATION-2` RESOLVED |

The per-item detail below is retained as the adoption contract for each.

---

## FR-5 — `run_nodus_workflow` reaches app callables — ✅ SHIPPED 1.9.0

**apps-monolith ref:** `APP-DEBT-MIGRATED-1` (Nodus-native reasoning row) · **Status:** ✅ shipped in
aindy-runtime **1.9.0** (2026-07-18). Diagnosed by probe on 1.8.0 (below); the runtime shipped **both**
asks — `run_nodus_workflow` gained a `capability_token` param (the `call_tool` path) **and** the VM's
`sys()` now resolves app-registered syscalls (the syscall path). App adoption (flag-gated Nodus reasoning
routing) is the follow-on. Original diagnosis retained below as the adoption contract.

### The goal (app side)
Route the analytics reasoning `execution_intent` to execute on the **Nodus VM** via
`run_nodus_workflow("reasoning_apply_v1", …)` instead of the Python flow engine — the last
open item on the reasoning roadmap. FR-2 already registers the `.nd`; this is about
*executing* it.

### What works (verified 1.8.0)
`run_nodus_workflow(name, *, db, user_id, input_payload, error_policy, trace_id, initial_state)`
runs a registered flow-graph `.nd` **to a terminal state** in-process (`nodus_status:
success`); `set_state` values surface at `return["data"]["nodus_output_state"]`. The old
execute-to-completion caveat (nodus_vm §5 gates / RTR-1) is genuinely resolved. So the
executor is fine.

### The gap — neither VM call surface can reach an app callable from this entry point
A `.nd` that needs app logic must call it via one of the VM's two surfaces; **both fail**
when the workflow is launched through the public `run_nodus_workflow`:

1. **`call_tool("<app tool>", args)`** → returns
   `{"success": false, "error": "tool execution requires a capability token"}`. The tool path
   is fail-closed on a **scoped capability token** (`nodus_worker.run_agent_tool`), but the
   public `run_nodus_workflow` signature exposes **no** `capability_token` /
   `granted_capabilities` parameter. (The lower-level `nodus_execution_service` *does* take a
   `capability_token` — `nodus_execution_service.py:281,991` — it is simply not threaded through
   the public entry point.)
2. **`sys("sys.v1.<app syscall>", payload)`** → the workflow completes but the kernel
   `dispatch_syscall` the VM routes to returns `"Unknown syscall"` for **app-registered**
   syscalls (`register_syscall`). The app syscall surface is not resolved in the VM's syscall
   dispatch context.

Net: there is **no app-side way** to make a native `.nd` invoke app reasoning (or any app
tool/syscall) through `run_nodus_workflow` as shipped.

### The ask (runtime) — either is sufficient
- **(a)** Thread a `granted_capabilities` / `capability_token` argument through the public
  `run_nodus_workflow` (it already exists one layer down) so an app-initiated native workflow
  can be granted the capabilities its `call_tool` steps require; **or**
- **(b)** Make the VM's `sys()` dispatch resolve app-registered syscalls (route through the same
  registry `register_syscall` populates), so a `.nd` can reach app logic via a syscall.

### App-side adoption (once shipped)
Rewrite `reasoning_apply_v1.nd` to invoke the reasoning callable (tool `reasoning.evaluate`
under (a), or a new `sys.v1.analytics.reasoning_recommendation` syscall under (b)), add a
flag-gated (`AINDY_REASONING_NODUS_NATIVE`, default off) branch in the reasoning-apply path
that calls `run_nodus_workflow` and normalizes `nodus_output_state.reasoning_apply_result` to
the existing `{data: recommendation}` envelope, then integration-test end-to-end completion
(postgres tier, like `test_nodus_vm.py`). Behavior-neutral substrate change; soak-then-flip.

### References
- Runtime: `AINDY/runtime/nodus_workflow_registry.py` (`run_nodus_workflow`),
  `AINDY/runtime/nodus_execution_service.py:281,991` (`capability_token` exists here),
  `AINDY/runtime/nodus_worker.py:92` (`run_agent_tool` fail-closed; `sys()` → `dispatch_syscall`
  at ~258).
- App: `apps/analytics/nodus/reasoning_apply_v1.nd`, `apps/analytics/agents/tools.py`
  (`reasoning.evaluate`), `apps/analytics/services/reasoning/`, the `APP-DEBT-MIGRATED-1`
  Nodus-native reasoning row in `TECH_DEBT.md`.

---

## FR-6 — Self-service password management (change + reset) 🟡 item 1 SHIPPED, items 2–3 awaiting our call

**apps-monolith ref:** surfaced in the KPI-dashboard walk (2026-07-31) · **Status:** item 1
shipped in `aindy-runtime==1.11.0` (2026-08-01); items 2–3 blocked on a delivery decision the
runtime asked us to make.

### ✅ Item 1 closed — `POST /auth/password/change` (runtime 1.11.0)

Shipped as specified: Bearer-only, `5/minute`, min length 8, bumps `token_version`, returns a
freshly-versioned token in the canonical envelope so `unwrapEnvelope` and the existing token-store
path apply unchanged. **The returned token must be stored** — the version bump invalidates every
session including the caller's, so keeping the old token 401s the next request.

App-side wiring (the in-app "Change password" control) is now unblocked and is ours to build.

### 📮 Our answer on items 2–3: **(a) — the runtime sends it**

The runtime handoff asked us to choose between **(a)** the runtime delivering the reset mail via
an `email` connector, and **(b)** the runtime returning the token for us to deliver.

**We choose (a).** The reasoning, so it does not have to be re-derived:

- **(b) does not actually deliver FR-6.** The runtime is right that a response body carrying a
  live credential-reset token is only safe behind an admin/service-authenticated caller. But the
  gap FR-6 exists to close is *a user who forgot their password has zero recovery path* — an
  endpoint a locked-out user cannot call does not close it. We would build (b), still not have
  the feature, and be left permanently guarding a token-minting route.
- **The connector is not throwaway work.** An `email` channel is wanted regardless — freelance
  order and payment notifications have the same dependency. Under (a) that cost is paid once, by
  the layer that owns egress policy, rather than duplicated per consumer.
- **(b) also moves the security boundary to the weaker side.** Under (a) the token never leaves
  the runtime; under (b) it crosses a process boundary into an app that does not own auth, and
  every future caller of that route becomes an auth-surface reviewer.

**Positions on the open sub-questions** (all ours to be overruled on — they are runtime calls, we
are only removing ambiguity):

| Question | Our position | Why |
|---|---|---|
| Token storage | **Stateless signed token** carrying `user_id` + `token_version` | Self-invalidating: the reset itself bumps `token_version`, so the token is single-use *by construction* rather than by bookkeeping. No table, no migration, no cleanup job. |
| Single-use | Falls out of the above | A consumed token's `token_version` no longer matches. Replay fails without a revocation list. |
| TTL | **30–60 minutes** | Long enough to survive a slow mail hop, short enough that a leaked inbox is not an indefinite backdoor. |
| Unknown email on `/forgot` | **Always 200** | Otherwise the endpoint is an account-enumeration oracle. Agreed with the runtime's own read. |
| Rate limit | Stricter than `/change`'s `5/minute` — suggest **3/minute per IP + per email** | `/forgot` is unauthenticated, so it is the cheapest endpoint to abuse for mail-bombing. |

**Dependency we accept:** this now sits behind FR-1 connector + capability-enforced egress. We are
not asking for it ahead of that work; we are answering so it is not blocked on us.

### Related: no password policy on `register_user`

The runtime flagged that `MIN_PASSWORD_LENGTH` guards `/auth/password/change` only, and that
adding it to `register_user` would reject existing callers. **We want it on register too**, but
agree it is a separate, breaking-ish decision — flagging it here rather than bundling it. This
repo has no production user base whose passwords would be invalidated, so from our side the
migration cost is zero.

### Original filing (for context)

### Today (the limitation)
The entire auth surface is four routes:

```
POST /auth/register   POST /auth/login   POST /auth/logout
POST /auth/admin/invalidate-sessions/{user_id}
```

There is **no forgot-password, no reset-token, and no change-password endpoint** — verified by
enumerating the live `/openapi.json` on 1.10.2. Consequences:

- A user who forgets their password has **zero recovery path** through the product.
- Even a **logged-in** user cannot change their own password — there is no route for it.
- The only way to set a password is a direct `UPDATE users SET hashed_password = …` against
  Postgres, hashing with the runtime's own `hash_password()`. That is exactly what had to be done
  this session to restore admin access (`admin@local.test`), and it is the same class of gap as
  the **first-admin bootstrap** finding (walk-log item 29: `admin/users/{id}/promote` is
  admin-gated with no UI, so the first admin was made via a direct DB `UPDATE`). Auth
  self-service — recovery, rotation, and bootstrap — is thin across the board and currently
  requires DB surgery.

### Why this is a runtime request (not app-fixable here)
Auth is unambiguously runtime-owned: `/auth/*` is in `RUNTIME_OWNED_PREFIXES`
(`client/src/api/_routes.js`), the routes are mounted by the runtime, password hashing/verifying
lives in `AINDY.services.auth_service` (`hash_password`, `verify_password`, `pwd_context`), and
this repo does not own `AINDY/`. Even the client auth calls (`loginUser`, `registerUser`) are
re-exported from `@aindy/ui-kit`. There is no `register_*` hook that lets an app add an auth
route, so this is a build against `aindy-runtime`.

### The ask (runtime) — sliceable, cheapest first
1. **`POST /auth/password/change`** (authenticated) — verify current password, set new. Needs no
   delivery channel, so it is the smallest useful slice and closes the "logged-in user can't
   rotate" gap on its own. Should invalidate existing sessions on success (the
   `invalidate-sessions` machinery already exists).
2. **`POST /auth/password/forgot`** — issue a time-boxed, single-use reset token for an email.
3. **`POST /auth/password/reset`** — consume the token, set the new password, invalidate sessions.

All three reuse `hash_password` / `verify_password`. **Delivery dependency:** the forgot/reset
pair needs a way to get the token to the user (email). That ties to **FR-1** (connector +
capability-enforced egress) — the runtime could either send via its own channel or return the
token for the app to deliver through the future email connector. Because of that coupling, **item
1 (change-password) is independently shippable now**; items 2–3 can follow the FR-1 egress work.

### App-side adoption (the contract)
Once the endpoints exist, this repo wires the UI — no runtime dependency beyond the routes:
- a **"Forgot password?"** link on `client/src/components/shared/LoginPage.jsx` → a reset form
  that calls `/auth/password/forgot` then `/auth/password/reset`;
- an in-app **"Change password"** control calling `/auth/password/change`.

Nothing to wire until the routes ship. Same pattern as the rest of the frontend walk: the UI is
app-owned and cheap; the capability underneath must exist first.

### References
- Runtime: `AINDY/services/auth_service.py` (`hash_password`, `verify_password`, `pwd_context`;
  the four `/auth/*` routes), `users.hashed_password` column.
- App: `client/src/components/shared/LoginPage.jsx`, `client/src/api/auth.js` (ui-kit re-exports),
  `RUNTIME_OWNED_PREFIXES` in `client/src/api/_routes.js`.
- Relation: sibling of **walk-log item 29** (first-admin bootstrap has no UI path) in
  `docs/handoffs/FRONTEND_WALK_LOG.md`; forgot/reset delivery depends on **FR-1**.

---

## What this is

Four items surfaced during the apps-monolith build that touch `AINDY/` (the runtime),
which this repo does not own. Per the split, apps extend the runtime only through
`register_*` hooks; a need the runtime doesn't expose is a request against
`aindy-runtime`, built + published there, then adopted here.

## Triage update — checked against `aindy-runtime` (2026-07-17)

**Two of the four were already shipped upstream; the original priority was inverted.**
Corrected status and the *real* remaining work per item:

| ID | Item | Status | Actual remaining work |
|---|---|---|---|
| **FR-1** | `register_connector` + capability-enforced outbound I/O | 🔴 **net-new** | The real build — but mostly *wiring*: enforcement primitives already exist unwired (`CapabilityPolicy`, `SecretBroker`, G4a egress seam). |
| **FR-3** | Next-Action autonomous dispatch | 🟡 **~70% shipped** | Acting half exists (`maybe_act_on_next_action`, v1.6.2, flag-gated). Delta: broaden verbs, add a dispatch-outcome record, soak+flip. |
| **FR-2** | `register_nodus_workflow` | ✅ **shipped** | None upstream. **App can adopt today** — see contract doc. |
| **FR-4** | Docs relocation (Bucket A + INVARIANTS runtime half) | 🟢 **hygiene** | Relocate per the existing ownership map. |

**Real priority order (runtime-side effort): FR-1 > FR-3 > FR-2 (adopt) > FR-4.**
The original doc said `FR-3 > FR-1 > FR-2 > FR-4` — wrong, because FR-2 is done and FR-3
is mostly done, leaving **FR-1 as the actual net-new work.**

Cross-referenced from this repo's `TECH_DEBT.md` (IDs match). Details below.

---

## FR-1 — Connector registration hook + capability-enforced outbound I/O 🔴 net-new

**apps-monolith ref:** `MASTERPLAN-CONNECTOR-RUNTIME-1` · **Status:** confirmed real gap; the actual work.

### Today (the limitation)
External automation connectors (`social`, `crm`, `email`, `webhook`, `stripe`,
`subscription`) are dispatched by a **hardcoded `if/elif` ladder** in a single app
service, `apps/automation/services/automation_execution_service.py::execute_automation_action`.
Each builds its own outbound HTTP/SMTP with stdlib and wraps it in
`perform_external_call` (`AINDY.platform_layer.external_call_service`) — which is
**observability-only** (emits `external.call.started|completed|failed`, times the call;
no auth, allow-list, rate-limit, sandbox, or credential vaulting). No `register_connector`
hook exists in `AINDY.platform_layer.registry`.

### The ask (runtime) — mostly wiring, not greenfield
Per the upstream triage, the enforcement primitives **already exist but are unwired**:
- `CapabilityPolicy` (AGENT-HARDEN-8) — recipient/domain allow-lists + rate-limiting.
- `SecretBroker` (AGENT-HARDEN-9) — credential vaulting.
- the G4a egress seam.

So FR-1 is: **(1)** a `register_connector(connector_type, handler)` hook symmetric to
`register_router`/`register_syscall`/`register_job` (suggested handler shape
`handler(action, ctx) -> dict`); **(2)** route connector outbound I/O through
`CapabilityPolicy` + `SecretBroker` + the egress seam so calls are authorized /
allow-listed / rate-limited / vaulted rather than observe-only; **(3)** a shared outbound
HTTP client with retry + circuit-breaking to replace app-side raw `urllib`.

### App-side adoption (the contract)
The app deletes its `if/elif` ladder and registers each connector via the hook; outbound
calls become authorized/allow-listed/rate-limited by the runtime and pull credentials from
the broker rather than app config. No change to *delivery* — this is enforcement + pluggability.

### References
- App: `apps/automation/services/automation_execution_service.py`, `tests/unit/test_automation_connectors.py`.
- Runtime: `AINDY/platform_layer/external_call_service.py`, `AINDY/platform_layer/registry.py`,
  `CapabilityPolicy` (AGENT-HARDEN-8), `SecretBroker` (AGENT-HARDEN-9), the G4a egress seam.

---

## FR-3 — Next-Action autonomous dispatch 🟡 ~70% shipped (Deliverable C)

**apps-monolith ref:** `INFINITY-RUNTIME-1` Gap 4 · **Status:** acting half shipped in aindy-runtime **1.6.2**.

### Already shipped upstream (correction to the original doc)
The original request was written as if the runtime were still **record-first only** — it
isn't. `AINDY/core/next_action_dispatch.py::maybe_act_on_next_action` (PR #213, v1.6.2)
already does the bounded, opt-in **autonomous-acting** half this asked for:
- flag `AINDY_NEXT_ACTION_ACTING` (**default off**),
- chain-depth cap,
- approval gate + admission reuse,
- app-sourced `trigger_execution` only.

### Genuine remaining delta
1. **Broaden verbs** beyond `trigger_execution` (e.g. `retry`, `schedule_follow_up`).
2. **Explicit dispatch-outcome contract** — part 2 of the original ask. Dispatch currently
   reuses events; there is **no dedicated outcome record** the app can read back.
3. **Soak + flip** — turn `AINDY_NEXT_ACTION_ACTING` on after a real-deployment soak (ops).

### App-side adoption (the contract)
The app already returns a runtime-coercible NextAction from its completion hook
(`apps/agent/agents/runtime_extensions.py::handle_agent_run_completed`, boundary-preserving
contract, `INFINITY-COMPLETION-HOOK-BOUNDARY-1` RESOLVED in 1.6.1). Once #2 lands, the app
reads the dispatch outcome from the new record; #3 is the operational flip that activates the
app's autonomous-acting phase.

> **Disambiguation:** distinct from the learned-recursion **Phase 2** (which makes a learned
> model *drive canonical scoring* and is gated on the app-side **3b-full** values decision —
> `docs/architecture/INFINITY_LEARNED_RECURSION_SCOPE.md`). FR-3 is the *autonomous-acting*
> frontier, not learned scoring.

### References
- Runtime: `AINDY/core/next_action_dispatch.py` (`maybe_act_on_next_action`, PR #213, v1.6.2),
  `AINDY/core/next_action.py`, `docs/runtime/INFINITY_LOOP_AUDIT.md` (Gap 4), `INFINITY-RUNTIME-1`.
- App: `apps/agent/agents/runtime_extensions.py`, `INFINITY-COMPLETION-HOOK-BOUNDARY-1` (this repo's `TECH_DEBT.md`).

---

## FR-2 — `register_nodus_workflow` ✅ SHIPPED (adopt-today)

**apps-monolith ref:** `APP-DEBT-MIGRATED-1` (Nodus-native reasoning row) · **Status:** the exact hook exists upstream.

### Already shipped upstream (no runtime work needed)
The requested hook is present and symmetric to `register_flow`, reachable from the
manifest/extension path:
- `AINDY/platform_layer/registry.py:1711` — `register_nodus_workflow(name, source, kind=, version=, capabilities=, …)`
- impl `AINDY/runtime/nodus_workflow_registry.py`; DB model `nodus_workflow.py`; migration `0006`;
  router `nodus_flow_router.py`; **contract doc `docs/runtime/NODUS_WORKFLOW_CONTRACT.md`**;
  tests `test_nodus_workflow_registry.py`.

This is a "**reply to app team: it exists, here's the contract doc**" item, not a build.

### App-side adoption (this repo's follow-on)
The analytics reasoning layer can register a native `.nd` workflow via
`register_nodus_workflow(...)` per `NODUS_WORKFLOW_CONTRACT.md` and route a reasoning
`execution_intent` to it (behind the existing `register_flow_strategy("reasoning", …)` seam)
for Nodus-native, VM-executed execution instead of the Python flow engine. **Adoptable now.**

### References
- Runtime: `AINDY/platform_layer/registry.py:1711`, `AINDY/runtime/nodus_workflow_registry.py`,
  `docs/runtime/NODUS_WORKFLOW_CONTRACT.md`.
- App: `apps/analytics/services/reasoning/`, `apps/analytics/bootstrap.py::_register_flow_strategies`.

---

## FR-4 — Docs relocation: Bucket A + the runtime half of `INVARIANTS.md` 🟢 hygiene

**apps-monolith ref:** `DOCS-MIGRATION-2` · **Status:** hygiene; the ownership map already exists.

### The ask (runtime)
Relocate/author into `aindy-runtime` per the existing ownership map
`aindy-runtime/docs/runtime/RUNTIME_DOCSET_BOUNDARY.md`:
- **Bucket A (relocate as-is):** `architecture/DATA_MODEL_MAP.md`,
  `architecture/MODEL_OWNERSHIP_POLICY.md`, `platform/governance/{AGENT_WORKING_RULES,
  ERROR_HANDLING_POLICY, CHANGELOG}.md`, and all four `tutorials/*` (they teach runtime
  primitives — memory bridge, flow WAIT/RESUME, scheduler, Nodus).
- **Runtime invariants (author):** the runtime half of `INVARIANTS.md`
  (PostgreSQL/UTC/session-isolation/memory-graph/embedding/schema-drift). The app-domain half
  already lives here at `docs/platform/governance/INVARIANTS.md` (section numbers preserved).

### App-side adoption
None functional — update the reciprocal cross-links once relocated.

### References
- App: `DOCS-MIGRATION-2` in this repo's `TECH_DEBT.md`.
- Runtime: `docs/runtime/RUNTIME_DOCSET_BOUNDARY.md`, the pre-split archive.

---

## Coming back to apps-monolith — adoption follow-ons

- **FR-2 (adopt now):** register the reasoning `.nd` workflow(s) per `NODUS_WORKFLOW_CONTRACT.md`,
  behind the existing flow-strategy seam. No upstream dependency.
- **FR-3:** the acting flag exists (`AINDY_NEXT_ACTION_ACTING`, default off); adopt once the
  dispatch-outcome record lands, then it's an ops soak+flip. App-side autonomous-acting phase
  still to be scoped on top.
- **FR-1:** adopt after the runtime ships the hook — replace the connector `if/elif` ladder with
  `register_connector` calls; credentials/allow-lists move to the runtime.
- **FR-4:** update reciprocal doc cross-links after relocation.
