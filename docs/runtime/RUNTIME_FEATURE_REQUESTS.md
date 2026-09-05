---
title: "Runtime Feature Requests — handoff to aindy-runtime"
last_verified: "2026-09-05"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime Feature Requests — handoff to `aindy-runtime`
## FR-25 — 11 of 13 syscall error paths emit no log line and no durable event 🔴 observability

**apps-monolith ref:** found 2026-09-05, and found *only* because 2.9.0 shipped
`aindy_syscall_outcome_total`. Before that metric this was unobservable, so thank you — the
request is to finish the job the metric started.

### What we hit

Three syscalls were failing on our live stack — `sys.v1.agent.count_runs`,
`sys.v1.agent.list_recent_durations`, `sys.v1.automation.update_loop_adjustment`. We only know
because the new counter said so. `docker logs` contains no ERROR line for any of them, and
`system_events` contains no `syscall.executed` row for them either.

We spent a session narrowing it and could not identify the cause, because **there is no error
message anywhere to read.** We excluded registration, capability mismatch, tenant violation and
data-dependence by direct test, and could not reproduce it through the route
(`GET /apps/identity/boot` returns 200 without moving the counter).

### The mechanism, from your code

Every dispatcher error funnels through `_error_envelope`
(`AINDY/kernel/syscall_dispatcher.py:859`). It increments the outcome metric and returns the
envelope. It does not log, and it does not call `_emit_syscall_event`.

Thirteen call sites reach it. **Only two — line 375 (generic handler exception) and line 526 —
log anything.** The other eleven are silent:

> unknown syscall version · unknown syscall · permission denied · tenant violation ·
> quota backend unavailable · input validation failed · handler contract violation ·
> outcome contract violation · stable output validation failed

Several of those are *operator-actionable configuration errors*. "Permission denied: requires
capability X" is precisely the message someone needs, and today it exists only inside a returned
dict that a defensive caller discards.

Confirmed against our data: `system_events` holds `syscall.executed` rows with `status="error"`
from August but none from 2026-09-05, because `_error_envelope` never emits one.

### Why the swallow is not the caller's bug

Our `identity_boot_service` does `if result.get("status") != "success": return 0`. That is
correct defensive code — and exactly the shape 2.9.0's own §1 asked everyone to adopt. Combined
with a silent dispatcher it produces a **confident wrong number**: a surface reporting "0 agent
runs" rather than "unavailable", with nothing anywhere to contradict it.

### Ask

Log at `WARNING` inside `_error_envelope`, once, with the syscall name and the message it is
already constructing. One line at the funnel covers all thirteen paths and cannot double-count —
the same single-funnel property the comment there already relies on for the metric.

Emitting `SYSCALL_EXECUTED` with `status="error"` from that funnel would additionally make
failures reconcilable after the fact, which is the half that matters once a response is gone.
We would take the log line alone.

### Not asking for

Any change to the envelope contract, or to the metric. Both are right. This is purely that the
message already computed on line 862 should be visible to an operator.

---

## FR-24 — `nltk==3.10.0` is an exact pin, and it is now a published CVE ✅ SHIPPED in 2.7.0

**Closed 2026-09-02, one day after filing.** `aindy-runtime` 2.7.0 pins `nltk==3.10.3`
(runtime commit `4a9fea9`, "deps: bump nltk 3.10.0 -> 3.10.3"), which clears
`PYSEC-2026-3726` / `CVE-2026-62383`. Adopted here in
`docs/runtime/RUNTIME_2_7_0_UPGRADE.md`. The ask below — relax the exact pin to admit the
patched line — is exactly what landed.

Upstream also closed the reporting gap that let this sit unseen: `pip-audit` now runs on
pushes to `main`, not only on pull requests. It previously gated every PR into `main` and
never gated `main` itself, so a newly published advisory could redden an unchanged branch
with nothing surfacing it for up to a week. That is precisely what happened on
2026-08-31.

**One thing did not go away, and it is not this FR.** 3.10.3 carries a *different*
advisory — `PYSEC-2026-3740` / `CVE-2026-81726` — which has **no fix released**. So our
`Security Audit` is still red-by-default until exempted, but for a new and unfixable
finding rather than this one. We now carry that as a documented ignore, assessed against
our own call sites rather than copied from the runtime's exemption: the runtime's first
ground is that it never imports nltk, and **we do**
(`apps/search/services/seo_services.py:7`). Reasoning in
`RUNTIME_2_7_0_UPGRADE.md` §3 and in the workflow comment.

Do not resolve that by pinning nltk back to 3.10.0 — that reintroduces the fixed
vulnerability this FR was about.

### Original entry (2026-09-01) — retained

**apps-monolith ref:** found 2026-09-01 while triaging a Dependabot backlog. This is the
first runtime dependency pin to turn our `main` branch red on its own.

### Symptom

`Security Audit` on `main` went from green (2026-08-24) to red (2026-08-31) with no app
change in between — the advisory was published into the window:

```
Name Version ID              Fix Versions Description
---- ------- --------------- ------------ -----------
nltk 3.10.0  PYSEC-2026-3726 3.10.2       nltk versions before 3.10.2 contain a symlink-based
                                          arbitrary file read vulnerability in IPIPANCorpusReader
                                          methods that bypass nltk.pathsec validation entirely.
```

It is now also the only red check on every unrelated PR, which is the expensive part —
`pip-audit` runs on the resolved tree, so a CI-config bump (#252) and an npm-only
bump (#251) both showed a failing "Python Dependency Audit" that neither one caused.

### Why we cannot fix this on our side

`nltk` is not ours. It is not in `pyproject.toml` — our direct dependencies are
`aindy-runtime`, `aindy-sdk`, and `anthropic`. It arrives entirely through the runtime,
and the pin is **exact**:

```
$ python -c "import importlib.metadata as md; print(md.distribution('aindy-runtime').requires)"
... 'nltk==3.10.0', 'textstat==0.7.13' ...
```

Confirmed against the published metadata for the version we pin (`aindy-runtime>=2.6.0,<3.0`):

```
$ curl -s https://pypi.org/pypi/aindy-runtime/2.6.0/json | jq '.info.requires_dist[] | select(test("nltk"))'
"nltk==3.10.0"
```

`==` leaves no room. Adding `nltk>=3.10.2` to our `pyproject.toml` produces a resolver
conflict rather than an upgrade, so there is no app-side remedy that is not a lie to the
resolver or a suppression of the finding.

### Ask

Relax the pin to admit the patched line. `3.10.2` is the advisory's stated fix; `3.10.3`
is current:

```diff
- nltk==3.10.0
+ nltk>=3.10.2,<3.11
```

`textstat==0.7.13` is worth the same look while the file is open — it depends on `nltk`
too, and an exact pin there will constrain the same resolution.

### What we are doing in the meantime

Nothing that hides it. We are **not** adding `--ignore-vuln PYSEC-2026-3726` to
`.github/workflows/security-audit.yml`; the finding is real and reachable
(`apps/search/services/seo_services.py` imports `nltk` directly), and an ignore entry
outlives the memory of why it was added. We are merging around the red check by hand and
treating this FR as the fix. If the runtime bump is going to take more than a release
cycle, tell us and we will add a **dated, FR-referencing** ignore rather than keep
merging past a red gate.

### Note for us, not the runtime

`apps/search/services/seo_services.py` imports `nltk` without declaring it — we get it
transitively from the runtime. That is our bug regardless of how this FR lands, and it is
why the CVE is reachable from app code at all. Tracked separately.

## FR-23 — `/observability/system` reports 0 syscalls and 0 tools while 90 and 16 are live 🔴 observability

**apps-monolith ref:** found 2026-08-22 while measuring the syscall vocabulary for a CLI-ownership
question. Two separate causes, one visible symptom, and the symptom is a confident wrong number on
an operator surface.

### Measured on a full 16-app boot

| `GET /observability/system` → `registry` | reports | actual |
|---|---|---|
| `syscall_count` | **0** | **90** (`AINDY.kernel.syscall_registry.SYSCALL_REGISTRY`) |
| `tool_count` | **0** | **16** (`get_tools_for_run('agent')`) |

`observability_router.py:491` computes both from `platform_layer.registry`:
`sum(1 for _ in iter_syscalls())` and `sum(1 for _ in iter_agent_tools())`.

### Cause 1 — two functions named `register_syscall`, and the dispatcher reads only one

`platform_layer/registry.py:482` validates the handler and stores it in `_syscalls`. **The
`SyscallDispatcher` never reads that dict** — `syscall_dispatcher.py:365,386` resolve against the
kernel `SYSCALL_REGISTRY`. Every app registers through
`AINDY.kernel.syscall_registry.register_syscall`; `_syscalls` is empty after a full boot.

So `platform_layer.register_syscall` is a seam that accepts registrations, validates them, and
routes them nowhere a call can reach. Its only consumer is the metric above, which is why the
symptom is a zero rather than silence. Worth noting our own `CLAUDE.md` documented the
platform_layer path as the one to use — corrected on our side the same day.

### Cause 2 — the tool metric counts the extension model nobody uses

Two models coexist in the same file: static `register_agent_tool` → `_agent_tools` (walked by
`iter_agent_tools`), and `register_run_tool_provider` → `_agent_run_tools[run_type]`, a callable
resolved by `get_tools_for_run`. **No app in this repo uses the static form**; both that do register
tools use the provider. So `iter_agent_tools() == 0` is accurate about that dict and wrong as
"tool_count".

### The ask

1. **Point the metric at the live sources** — `len(SYSCALL_REGISTRY)` and the resolved provider
   count. Smallest possible fix, and it stops an operator surface asserting zero.
2. **Decide what `platform_layer.register_syscall` is for.** If it is a legacy seam, deprecate or
   delete it; a validating function that routes nowhere is worse than an absent one, because it
   accepts work silently. If it is intended, wire it into dispatch.
3. **Same question for `register_agent_tool`.** Two extension models where one is unused is a choice
   worth stating, not an accident to preserve.

### Why we are not fixing it ourselves

`AINDY/` is yours, and the surface that displays these numbers is the operator dashboard in FR-21 —
a repo boundary this reporting already sits across. We render what the endpoint returns.

### What we are NOT claiming

- **Not that syscalls are broken.** Dispatch works; 90 are registered and reachable. This is a
  reporting defect plus an unwired seam, not a functional one.
- **Not that the provider model is wrong.** It is the one in use and it works. Only that a metric
  counting the other one reads as "no tools are registered".

---

## FR-22 — 51 runtime routes are documented in our reference and guarded by nobody ✅ CLOSED in 2.6.0 — and our premise was wrong

> **Amendment, 2026-08-23.** Shipped: `AINDY/route_inventory.json` now ships inside the wheel and
> is contract-tested upstream in both directions. The runtime gave us something better than the
> guard we asked for — a machine-readable inventory we can *subtract* from our booted surface to
> derive the app-owned set, instead of curating one by hand.
>
> **The request also rested on a premise that is false, and it was ours.** We assumed `/apps/*`
> marked the ownership boundary. Read from the installed wheel: the inventory has **126 entries, of
> which exactly 35 are under `/apps/*`** — `/apps/memory/` (22) and `/apps/coordination/` (13). So
> `scripts/check_api_reference.py`, scoped to `APP_PREFIX = "/apps/"`, has been enforcing over 35
> runtime-owned routes all along, and of the 265 `/apps/*` entries in our reference **230 are
> genuinely ours**.
>
> One small correction back: the 2.6.0 handoff describes the 35 as "coordination, memory, agent".
> There are no `agent` routes in the file.
>
> Follow-up on our side is rewiring the guard onto the inventory, tracked in
> `RUNTIME_2_6_0_UPGRADE.md` §6 — not here.

## FR-22 — 51 runtime routes are documented in our reference and guarded by nobody 🟡 drift *(original request below)*

**apps-monolith ref:** found 2026-08-22 while restructuring `docs/`. Small, and the cheapest of
the requests filed this week.

### What exists

`docs/api/API_REFERENCE.md` is titled *"App HTTP REST API Reference"* and is guarded by
`scripts/check_api_reference.py`, which boots the app profile and diffs the live route tree against
the document. That guard enforces **`/apps/*` only** — `APP_PREFIX = "/apps/"`.

The document also carries **~51 runtime-owned entries**: 43 `/platform/*`, 5 `/health`, 2 `/auth`,
1 `/ready`. The guard's own docstring calls them "a curated inventory". They are useful — app
developers call these routes and want one place to look them up — but **nothing checks them.**

So the file has two halves with very different guarantees: the app half cannot drift without CI
failing, and the runtime half can drift silently for months and nobody finds out until a developer
follows a stale entry.

### The ask

**Guard your own surface.** Whatever shape suits you — publish a machine-readable route inventory
we can diff against, or run the equivalent of `check_api_reference.py` upstream and let us pin to
its output.

We are deliberately **not** proposing to extend our guard to cover your routes. That is the mistake
FR-20 documents: when this repo notices a runtime-owned problem, building an app-side enforcement
mechanism around it makes the app responsible for policing a surface it does not own, and the real
issue stops being visible to the people who could fix it.

### What we are NOT claiming

- **Not that the entries are wrong today.** They were verified accurate on 2026-07-05. The point is
  that nothing would tell us if they stopped being accurate.
- **Not asking you to take the document.** The app half belongs here. Only the guarantee is missing.

---

## FR-21 — the operator surface has been rebuilt app-side, next to yours; we would like to retire ours 🔴 ownership

**apps-monolith ref:** found 2026-08-22 while auditing why a runtime-verification phase produced
almost entirely app-side fixes. This is the largest single instance, and it is offered as a
handover, not a complaint.

### What exists

The runtime ships and serves an operator SPA: `GET /platform/` returns 200 from
`AINDY/platform/dist`, titled *"A.I.N.D.Y. Platform"*.

This repo independently grew a second one — `client/platform.html` → `client/src/PlatformApp.tsx`,
titled *"AINDY Platform"*: **5,949 lines across 13 components and 12 routes.**

| Panel | Lines | Shipped |
|---|---|---|
| `FlowEngineConsole` | 1678 | flows/runs |
| `AgentConsole` | 862 | #164 (envelope fixes) |
| `RippleTraceViewer` | 767 | |
| `AgentRegistry` | 659 | #159 |
| `ObservabilityDashboard` | 454 | |
| `AgentApprovalInbox` | 286 | |
| `ExecutionConsole` | 269 | #168 — execution-graph traces |
| `DeadLetterQueuePanel` | 202 | #169 — Replay / Delete / Drain |
| `WebhooksPanel` | 180 | #170 — full CRUD |
| `AdminUsers` | 129 | #169 — admin promotion |
| `PlatformNav` | 83 | #163 — 7 of 8 panels had no navigation before this |

Every write action is confirm-gated, and the frontend suite covers the DLQ and webhook panels.

### Why we are raising it rather than continuing

Checked against your served bundle (332 KB) on 2026-08-22: **zero occurrences of `webhook`,
`dlq`, `dead-letter`, or `drain`.** So these are not duplicated implementations of panels you
already have — they are operator capabilities the runtime's own surface does not currently expose,
built in the wrong repo because that is where the walk happened to be standing.

The surfaces they drive are **runtime-owned**: the dead-letter queue, the flow engine, webhooks,
the agent registry, admin promotion. An app repo should not be the place an operator goes to drain
a runtime DLQ.

### The ask

**Adopt whichever of these belong to you, and we will retire ours.** We are explicitly volunteering
to delete `client/src/components/platform/` and the `/platform/*` routes from this repo once the
equivalent lands in the runtime's SPA — that is the outcome we want, not dual maintenance.

Take them panel by panel; there is no need for a single cutover. We can supply the components, the
API shapes each was built against (every one was verified against live `curl` output, not fixtures
— see FR-17's neighbour note), and the test suites.

### What we are NOT claiming

- **Not that your SPA is wrong.** We never established which surface is canonical, and that
  ambiguity is the actual defect. This request is to settle it.
- **Not that all 13 belong to you.** `RippleTraceViewer` reads an app domain and probably stays
  here. The DLQ, flow engine, webhooks, registry and admin panels are the clear runtime ones.
- **Not urgent for correctness.** Both surfaces work. The cost is duplication, drift, and an
  operator who has to know which URL is the real one.

---

## FR-20 — `route_execution_guard` replaces a deliberately raised 4xx with an opaque 500 🟡 diagnostics

**apps-monolith ref:** observed 2026-07-22 (frontend walk item 3), filed 2026-08-22 after noticing
we had built a CI guard against it instead of asking.

A route that raises `fastapi.HTTPException` **before** entering the execution pipeline has its
status replaced: the guard catches every exception — including `HTTPException`, which is legitimate
control flow — and converts it to a `RouteExecutionViolation` (500). Your own log names the
condition exactly: `endpoint raised HTTPException before pipeline entry`.

**The violation is ours and we accept that.** `masterplan_router.py` disagreed with itself —
`lock_from_genesis` entered the pipeline, `get_masterplan` did not. We now enforce it in CI
(`scripts/check_route_pipeline_contract.py`).

**The ask is narrow: preserve the raised status while still recording the violation.** A stale
masterplan link should 404. Today it 500s, so the user-visible symptom of an app contract slip is
an *incorrect status code* rather than a logged violation — and the empirical sweep is the only
reliable detector, because file-level static analysis cannot find it (every file that raises also
uses the pipeline; the violation is per route).

**What we are NOT claiming:** not that the contract is wrong, and not that the guard should stop
firing. Only that a caught `HTTPException` already carries an intended status, and discarding it
loses information nobody gains from losing.

---

## FR-19 — an enveloped and a bare response share one URL space, with nothing to tell them apart 🔴 contract

**apps-monolith ref:** filed 2026-08-22. This was **the dominant defect class of the entire live
verification phase** and — the reason it is worth your time — it was never raised with you. Five
separate defects on five surfaces, ~40 `safeMap prevented crash` lines inside `@aindy/ui-kit`, and
56 references across our walk log. We fixed it eleven times in client code and asked you zero
times.

### The contract as it stands

Only routes that go through the execution pipeline return the `{status, data, ...}` envelope.
Everything else returns a bare body. Both live under the same `/apps/*` URL space, and **nothing
in the response distinguishes them**.

So every consumer must carry per-route knowledge of whether that route happened to enter a
pipeline. Our client did not: 3 of 11 API modules unwrapped, 8 did not. The failure signature is
brutal to debug — an object has no `.length`, so the empty-state branch does not fire either, and
the surface renders blank with no error at all.

A blanket unwrap is not available as a workaround: applying it indiscriminately corrupts any plain
response that legitimately carries a `data` key.

### The ask, in preference order

1. **Envelope everything under `/apps/*`** — one shape, no per-route knowledge required.
2. **Failing that, make it detectable** — a header or a stable envelope marker a generic client
   helper can branch on, so the knowledge lives in one function instead of in every module.

Either removes an entire defect class rather than another instance of it.

### What we are NOT claiming

**The inconsistency is substantially ours.** Whether a route enters the pipeline is an *app*
decision, and ours were inconsistent — the same root as FR-20. Making every `/apps/*` route enter
the pipeline is work we can do, and should.

But the *consequence* is a contract question only you can settle: two response shapes sharing a URL
space with no discriminator. Even with our side perfectly consistent, a client still has to know
which routes are enveloped, and there is no way to find out except by trying.

---

## FR-18 — every liveness probe persists a full health snapshot, and it is now 99.6% of the database 🔴 storage

**apps-monolith ref:** found 2026-08-22 while taking a routine `pg_dump` before a runtime upgrade.
The dump would not finish; the reason turned out to be worth a report on its own.

### What we measured

On a **local dev stack with four user accounts and no real traffic**, `system_events` is
**3653 MB across 183,604 rows** — against a total database size of 3795 MB. One event type
accounts for nearly all of it:

| type | rows | payload total | first | last |
|---|---|---|---|---|
| `health.liveness.completed` | **120,444** | **3317 MB** | 2026-07-19 | 2026-08-22 (still writing) |
| `autonomy.decision` | 25,377 | 6320 kB | | |
| `watchdog.scan.completed` | 16,648 | 2471 kB | | |

3528 MB of the table is TOAST, and `n_dead_tup` is **0** — this is not bloat and not a missing
autovacuum. It is live, intended data.

### The mechanism

`AINDY/routes/health_router.py:157`:

```python
def _emit_health_event(payload: dict) -> None:
    event_db = SessionLocal()
    try:
        emit_system_event(db=event_db, event_type="health.liveness.completed",
                          payload=payload, required=False)
    finally:
        event_db.close()
```

The `payload` persisted is the **entire health response** — 26 top-level keys including
`trusted_python_execution`, `deployment_contract`, `plugin_sandbox_attestation`,
`extension_execution_posture`, and the full plugin inventory. A row stores ~28 kB compressed;
`trusted_python_execution` alone is ~52 kB uncompressed.

The driver is the **container healthcheck**, which is simply `curl --fail --silent
http://localhost:8000/health` on a **15s interval** — the interval the runtime's own recommended
compose shape uses. That is 5,760 writes/day, each opening its own `SessionLocal`. Measured growth
over the 34 days above is **~98 MB/day, ~3 GB/month**, unbounded, with no retention policy.

### Why this is filed as a defect rather than a preference

The content is near-constant. Sandbox posture, deployment contract and plugin inventory do not
change between two probes 15 seconds apart, so effectively the same 28 kB is rewritten 5,760 times
a day. Three concrete costs:

1. **It swamps the signal.** `system_events` is where FR-15 and FR-17 are investigated. 65% of its
   rows are liveness snapshots.
2. **It makes backup and restore impractical.** A plain `pg_dump` passed 4.3 GB and was still
   running; `--exclude-table-data=system_events` produces **17 MB**. The real data is 0.4% of it.
3. **It is a continuous write load on the one thing that must stay up.** A 28 kB insert every 15s
   is WAL, checkpoint work, and page cache on every deployment, including small hosts.

### The ask

Stop persisting a full snapshot per probe. Any of these would resolve it, in our order of
preference:

1. **Emit on change only** — persist when health state or posture actually changes, not per probe.
2. **Make persistence opt-in** (env flag, default off), so a liveness probe is a read by default.
3. **Persist a digest** — status, degraded domains, and a hash of the posture blob, with the full
   snapshot available from the endpoint on demand.

A retention/prune policy for `system_events` would be welcome regardless, but it is a mitigation,
not a fix: the write rate is the problem.

### What we are NOT claiming

- **Not proven to have caused anything.** This stack has a separate, undiagnosed postgres
  crash-restart pattern — 11 cluster reinitialisations on 2026-08-22 alone, every one reported as
  `exited with exit code 2` and never `signal 9`, so the kernel OOM-killer is not the visible
  cause. The liveness writes are a plausible contributor to IO and checkpoint pressure —
  checkpoints on this host have measured 21s — but we have **not** established a causal link and
  are not asserting one.
- **Not a regression.** Present since at least 2026-07-19, across several runtime minors.
- **Not necessarily wrong to emit the event at all** — only to persist the whole snapshot every
  15 seconds.

### What we are doing app-side meanwhile

Raising the api healthcheck interval in our compose, and pruning historical
`health.liveness.completed` rows. Both are mitigations of write *rate* and accumulated volume; the
per-probe snapshot itself is runtime-owned.

---


## FR-17 — `async_job_service` emits `execution.started` outside a pipeline, so the gate eats it 🟢 observability

**apps-monolith ref:** found 2026-08-16 while verifying the 2.3.0 upgrade on a live stack. Small,
non-fatal, and adjacent to something you just fixed for the same reason.

### What we see

```
WARNING [AsyncJob] Emitting execution.started trace=af07e912-… encountered unexpected error:
        ExecutionContract violation: execution event 'execution.started' emitted outside …
```

Source: `AINDY/platform_layer/async_job_service.py:421`. Caught and logged, never raised — so
nothing breaks. But the event **is not recorded**, which means an async job execution has no
`execution.started` row in `system_events`.

### Why it is worth a line

This is the *same* constraint you described in `APP_HANDOFF_v2.2.0.md` §2 when explaining why the
new event is `scheduler.queued` and not the `execution.queued` we asked for:

> *"The execution-contract gate raises for any `execution.*` event emitted outside a pipeline, and
> the two hottest enqueue callers … have no pipeline active."*

You named the event-bus subscriber thread and wait expiry. **`async_job_service` looks like a
third caller in the same position**, still emitting an `execution.*` name from outside a pipeline
— so the gate discards it exactly as designed.

The cost is observability, and it is the specific kind that cost us three hours on FR-15: a trace
timeline with a silent gap where the work actually started. `apps/*/bootstrap.py` registers async
jobs in four domains (`agent`, `arm`, `masterplan`, and others via `register_async_job`), so this
path is live here.

### The ask

Either give the async-job path a pipeline context before it emits, or rename to a
non-`execution.*` event the way `scheduler.queued` was named — whichever matches the intent. If
the event is genuinely not a pipeline execution, the second is presumably right.

### What we are NOT claiming

**We cannot date it.** Observed on a fresh 2.3.0 container with only 2 occurrences; the 2.1.0
container it would be compared against is gone. **This is not offered as a 2.3.0 regression** —
only as something visible now, on a path your §2 explanation predicts.

---

## FR-16 — `nodus-lang==4.1.0` is an exact pin, so we cannot take 4.2.0 ✅ CLOSED in 2.3.0

**Shipped the same day it was filed.** `aindy-runtime==2.3.0` declares
`Requires-Dist: nodus-lang==4.2.0`. Verified locally: upgrading the runtime pulled
`nodus-lang-4.2.0` in the same transaction.

The pin stays **exact** — defensible for a language runtime, and the runtime team's position is
that this makes prompt bumping their obligation rather than our problem. They reproduced our block
first (an editable install *downgraded* 4.2.0 back to 4.1.0) rather than taking the report on
faith.

They also ran a check we did not think to ask for: `GUEST-CONFINE-1` makes guest confinement
depend on **VM constructor arguments**, so a silently renamed argument during a language bump
would leave the guest unconfined while every VM-mocking test still passed. Verified against the
real VM — all three flags present, all 31 gated builtins still refused.

**Our `#376` question stands open, and they explicitly declined to answer it** rather than guess.
The resume-path fixes present as *"`ok: true` with the result keys missing"*, matching
`run_reasoning_apply` returning `{'data': {}}` — which `CLAUDE.md` attributes to the Nodus 45s
hard limit. **Now re-testable, and worth doing before treating that note as the whole story.**

---

### Original filing (2026-08-16) — retained for context

## FR-16 — `nodus-lang==4.1.0` is an exact pin, so we cannot take 4.2.0 🟡 dependency

**apps-monolith ref:** found 2026-08-16, the day `nodus-lang==4.2.0` was published.

### The block

`aindy-runtime==2.2.0` declares:

```
Requires-Dist: nodus-lang==4.1.0
```

An **exact** pin, not a range. We do not depend on `nodus-lang` directly — it reaches us only
through the runtime — so there is no app-side change that can adopt 4.2.0. `pip install
nodus-lang==4.2.0` succeeds and leaves the environment inconsistent with the runtime's own
declared requirement, which is worse than a clean refusal.

### Why we want it — this release fixes things on a path we run

We execute `apps/analytics/nodus/reasoning_apply_v1.nd` through `run_nodus_workflow`
(`AINDY_REASONING_NODUS_NATIVE`, still soak-gated). 4.2.0's **#376** is four causes behind one
intermittent failure on exactly that path:

- a `RuntimeService` sweeper **adopted every non-terminal run in the store** every 500ms,
  including runs it never created, rebinding the graph to its own throwaway VM
- `LocalWorkflowStore.list_runs()` scanned **without the store lock**, and on Windows
  `os.replace` onto an open path fails with `[WinError 5]` and the record is lost — POSIX
  permits it, which is why it never showed in CI
- **resume ran under a 200ms wall-clock budget** sized for running a script, while a resume first
  reads state, reads checkpoint and recompiles the stored source. New `RESUME_TIMEOUT_MS` (30s)

> **The signature is one we have seen.** #376 presents as *"a resume returning `ok: true` with the
> result keys missing."* `CLAUDE.md` documents `run_reasoning_apply` returning `{'data': {}}` with
> no `_via`, which we attributed to the Nodus 45s hard limit under load. That attribution may be
> right and may be incomplete — **we are not claiming #376 explains it**, only that the signatures
> match and both are load-dependent. Worth re-running the nodus tests once 4.2.0 is reachable,
> before assuming the 45s note is the whole story.

### The ask

Bump the pin to `nodus-lang==4.2.0`, or relax it to a compatible range (`>=4.2,<5`) if the
language's own compatibility policy allows. Either unblocks us; the range is preferable only if
upstream is confident about it, since an exact pin is a defensible choice for a language runtime.

### What is NOT a problem

4.2.0's breaking change — *"every error now reports the resolved absolute path"* — **does not
affect this repo.** Nothing here parses Nodus stderr or matches on error-location strings
(grepped 2026-08-16). The two known issues shipped with 4.2.0 (`try/finally` without `catch`, and
closures capturing a top-level loop body) are compile-time failures, and our one `.nd` uses
neither construct.

---

## FR-15 — a request can wait ~3 minutes to enter the execution pipeline 🟡 (b) and (c) SHIPPED in 2.2.0; (a) is ours

**Mechanism found and confirmed — it is not a hypothesis any more.** From
`APP_HANDOFF_v2.2.0.md` §2:

`_scheduler_heartbeat_tick` is the only thing that drains the scheduler queue. It runs on a
**1-second APScheduler job with `max_instances=1`** and dispatched each item **synchronously**,
because `_decide_mode()` returns `INLINE` for everything: Rule 2 short-circuits Rules 4 and 5
when `AINDY_ASYNC_HEAVY_EXECUTION` is false, which is the default. **The entire async path —
including "high-priority work should never block a request thread" — was unreachable by
default.** Demonstrated across all eight type × priority combinations.

Our `maximum number of running instances reached (1)` log was not a side-symptom; it was the
queue being blocked, printing once per starved second. **And it predates 2.1.0** — the caution
about not attributing this to the upgrade was correct.

| Ask | Status |
|---|---|
| **(a)** confirm a single-slot serialisation | ✅ Confirmed, and it is default-on |
| **(b)** emit something while queued | ✅ **Shipped** — `scheduler.queued` SystemEvent with `queue_depth`, plus `aindy_scheduler_queue_wait_seconds` bucketed to 300s |
| **(c)** bound the wait | 🟡 **Partial** — not bounded, but wait firing moved to its own job and thread |

**Why it is `scheduler.queued` and not the `execution.queued` we asked for:** the execution-contract
gate raises for any `execution.*` event emitted outside a pipeline, and the two hottest enqueue
callers have no pipeline active. Our requested name would have raised in exactly the paths that
matter. Good catch on their side.

**(c) also fixed a correctness bug we had not noticed.** `tick_time_waits()` lived inside
`schedule()`, so a slow execution skipped the next tick and **no time-based wait fired** — a flow
parked on a timer stayed parked because an *unrelated* flow was busy. That shared tick is also why
`/health` died at 2.7 cores for 13 minutes.

### What remains is ours: `AINDY_ASYNC_HEAVY_EXECUTION`

Dispatch still runs INLINE by default, so work still queues behind a single 1s tick. 2.2.0 makes
that wait **visible** and stops it starving timers and health; it does not remove it. The
remaining step is flipping `AINDY_ASYNC_HEAVY_EXECUTION=1`, which routes
`flow`/`agent`/`nodus`/`job` to threads. Per the standing split, **soak happens here, not
upstream** — a deliberate handoff, not an omission.

### Their correction to our write-up — verified, they are right

We cited `apps/automation/flows/flow_definitions.py:254` for the synchronous
`sys.v1.analytics.execute_infinity` amplifier. **254 is the decorator line; the syscall appears at
258, 375 and 554 — three call sites, not one.** Confirmed by grep 2026-08-16. Removing one by
line number would have left two.

---

### Original filing (2026-08-16) — retained for context

## FR-15 — a request can wait ~3 minutes to enter the execution pipeline, with no events emitted 🔴 defect

**apps-monolith ref:** found 2026-08-16 driving a Genesis session to lock. Full writeup and
reproduction: [`DEFECT_GENESIS_MESSAGE_LATENCY.md`](../verification/DEFECT_GENESIS_MESSAGE_LATENCY.md).

### What we measured

On `aindy-runtime==2.1.0`, single user, no other traffic. Event timeline from `system_events` for
one Genesis message request (total wall time 184s):

```
external.call.completed   06:00:43.180   ← 4 LLM calls, 3.7s total
execution.started         06:03:40.561   ← 177.4s gap, ZERO events recorded
flow.node.* … execution.completed        ← the entire flow: ~0.9s
embedding.started         06:04:09.472   ← a further 26.3s gap
```

**The work is fast. The waiting is the whole cost.** 177 seconds elapse between the app handing
off and `execution.started`, and nothing is emitted in that window — so from the outside the
process looks hung rather than queued.

Across five identically-shaped calls latency was 5.4s / 18.2s / 48.8s / 22.3s / **184.1s** —
unbounded and non-monotonic. In a first episode the API pegged ~2.7 cores for **13 minutes** with
`/health` itself timing out, and needed a manual restart.

Throughout, APScheduler logged continuously:

```
Execution of job "Scheduler heartbeat tick (trigger: interval[0:00:01], …)"
  skipped: maximum number of running instances reached (1)
```

### The ask

1. **Is there a single-slot serialisation on the path into the execution pipeline?** We infer one
   from the queueing behaviour and the starved 1s heartbeat, but we cannot see inside the executor
   and are explicitly not claiming the mechanism.
2. **Emit something while a request is queued.** A `execution.queued` event, or a periodic
   "waiting on executor" log, would have turned a three-hour investigation into a one-line answer.
   Right now a queued request and a hung process are indistinguishable from the outside — which is
   the same observability shape as FR-14, where a crash loop could only be diagnosed from the
   container log.
3. **Consider a bound.** An unbounded wait with no timeout means one slow path can exhaust the
   API's ability to serve anything, including health checks.

### Our half, already identified

The app amplifies this by calling `sys.v1.analytics.execute_infinity` **synchronously on every
Genesis chat message** (`apps/automation/flows/flow_definitions.py:254`). That is ours to fix and
we will, but it only removes an amplifier — a 177s queue for one user's second chat message is not
explained by one extra syscall.

### Not attributable to 2.1.0 without further evidence

The heartbeat warnings begin during an unrelated image build on a loaded machine, ~1.5h before any
Genesis traffic. We have a documented history of misattributing load-dependent failures and are
not repeating it here.

---

## Response to v2.1.0 §6 — which scopes the UI actually needs

**Not a feature request — an answer to a question the runtime team asked**, in
`APP_HANDOFF_v2.1.0.md` §6: *"If you have a view on which scopes your UI actually needs, now is
the useful time to say so."* Answered 2026-08-15, from the client's real call surface rather than
from preference.

### Context, restated so the ask is unambiguous

Today `enforce_api_key_scope` gates API-key callers only — *"JWT users carry full trust and are
never gated by this check"* — so **an interactive browser session is more privileged than any API
key**. Scope enforcement currently reaches 8 call sites across 2 routers
(`flow.read` ×4, `memory.read` ×3, `flow.execute` ×1), which is the `HTTP-SCOPE-GAP-1` the runtime
team already tracks. This is close to greenfield, which is the good time to have an opinion.

### The finding that shapes the answer: our UI is not one caller

It is **two privilege classes sharing one JWT**, and the client already draws that line itself:
`useAuth()` exposes `isAdmin`, and `AdminUsers.jsx`, `AgentConsole.jsx` and
`AgentApprovalInbox.jsx` each bail to `<AdminAccessRequired />`. **That gate is frontend-only
today** — the token behind it carries full trust either way.

So deriving authority from the user row does not impose a new model on us. **It makes the server
enforce the boundary the UI already draws.** That is the strongest argument for the approach the
runtime team was already leaning toward.

| Class | Representative calls | Scopes |
|---|---|---|
| **Ordinary session** — Tasks, MasterPlan, Genesis, memory, search, social, identity | recall, node create/update, feedback, share, run flows | `memory.read`, `memory.write`, `flow.read`, `flow.execute`, `agent.run`, `execution.read` |
| **Admin session** — the operator console (`client/src/api/operator.js`) | `runFlow`, `resumeFlowRun`, `getFlowRegistry`, webhook CRUD, `promoteUser`, DLQ drain, execution graph | the above **+** `webhook.manage`, `platform.admin` |

**Not needed by the UI at all:** `memory.delete` (no DELETE against memory anywhere in the
client — the only client DELETEs are operator webhooks/DLQ, rippletrace sources and search
history) and `event.emit` (nothing in the client emits directly).

### Two caveats worth designing around

1. **`execution.read` conflates two questions.** "May I read executions" is a scope; "may I read
   *someone else's*" is data ownership. A scope alone will not answer the second. This is the
   same distinction that `memory_agents_list`'s owner-scoping just ran into — see
   `RUNTIME_2_1_0_UPGRADE.md` §2a.
2. **Please tie the admin scopes to the existing user-row admin flag**, not a new concept. Two
   sources of truth for "is this person an operator" is worse than none.

### On the rollout posture

Starting permissive and narrowing is right for us. The one thing that would hurt is a narrowing
step that lands without a release note — the UI would fail as scattered 403s across unrelated
screens, which reads as a frontend bug. **Name the scopes being enforced in the handoff for the
release that enforces them.**

---

## FR-14 — the recommended deploy entrypoint crash-loops on any additive runtime schema release 🟡 HALF CLOSED in 2.3.0

**Both things we asked for shipped**, and one arrived better than requested.

**Branchable exit codes.** `bootstrap-schema` now exits `0` success, `1` config error, `2` db-layer
import failure, **`3` additive reconcile required (safe to automate)**, `4` offline migration
required, `5` manual repair required. When a report indicates both, **`4` wins over `3`**, so an
entrypoint never auto-reconciles a database that needs a person. `--help` now states plainly that
a bare call under `set -e` in a container is a crash loop.

**`docker/entrypoint.sh` now branches on the code.** `AINDY_BOOTSTRAP_RECONCILE` still gates
whether exit 3 is applied automatically; the refusal path is now precise rather than opaque, and
4/5 no longer masquerade as something a flag could fix.

**The recurrence guard shipped too — the half we said was missing.** A CI job installs the
*previous* released wheel, builds its schema, installs the new build over that database, and
requires success or exit 3. That is exactly the state our own `deploy-bootstrap-guard.yml`
structurally cannot reach, for the reason recorded in this entry.

> **And they avoided the trap we fell into.** That guard passes trivially on a release with no
> schema change — where a broken guard and a clean release are indistinguishable — so it ships
> with a **negative-control job** that injects synthetic drift and requires detection, verified
> from logs rather than a green tick. That is precisely the discipline `SOAK_AUDIT_2026-08-15.md`
> concluded we lacked: a passing check on degenerate input proves nothing.

**Still open: the entrypoint-pattern half.** The runtime's own `init` scaffold still recommends
the bare form, which is what led us here originally.

---

### Original filing (2026-08-15) — retained for context

## FR-14 — the recommended deploy entrypoint crash-loops on any additive runtime schema release 🔴 upgrade-path (as filed)

> **The 2.2.0 upgrade will not crash-loop, and that is not a fix.** Flagged explicitly by the
> runtime team in `APP_HANDOFF_v2.2.0.md` §6, and worth repeating here because *"the upgrade
> worked"* is the observation most likely to be mistaken for *"the defect is gone."*
>
> 2.2.0 contains **no schema change** — nothing under `AINDY/db/models/`, no migration, schema
> contract stays `2026-08-15.1`, Alembic head stays `0016`. So `bootstrap-schema` has no additive
> drift to refuse and the bare entrypoint succeeds. **The next release that adds a runtime column
> reproduces exactly what we hit on 2.1.0.** Both gates still default off upstream and the README
> still recommends the bare form.
>
> Our own mitigation is in place and unaffected: `AINDY_BOOTSTRAP_RECONCILE` (`entrypoint.sh`,
> default off) turns the crash loop into an opt-in unattended reconcile, and a refusal now prints
> the remedy. That is a local guard, not a resolution of the upstream gap.

---

## FR-14 — the recommended deploy entrypoint crash-loops on any additive runtime schema release 🔴 upgrade-path

**apps-monolith ref:** found 2026-08-15 adopting 2.1.0, by the api container failing to start.
**Severity: this takes a deployment down**, and it will recur on every runtime release that adds
a column.

### What happened

`docker/entrypoint.sh` runs the runtime's own documented deploy command, bare, under `set -e`:

```sh
aindy-runtime bootstrap-schema        # entrypoint.sh:32
python scripts/deploy_bootstrap.py
exec "$@"                             # aindy-runtime serve
```

On 2.1.0 against an existing database it exits non-zero:

```
error: runtime-owned schema is not ready: Runtime-owned schema requires an explicit additive reconcile:
  Runtime table 'agents' is missing required column 'metadata'.
  Runtime table 'agents' is missing required column 'updated_at'.
Re-run with --reconcile for an additive column/index fix, or perform the required offline
migration before retrying.
```

`set -e` → exit; `restart: unless-stopped` → **crash loop**; `serve` is never reached. The stack
stayed down until we ran `bootstrap-schema --reconcile` by hand.

### Why this is a real gap rather than us holding it wrong

**The refusal itself is right.** A command that may run against production should not silently
`ALTER TABLE`. We are not asking for that default to change.

The gap is the combination:

1. `bootstrap-schema` is what the runtime **recommends as the deploy entrypoint command** (its
   own `--help`: *"Intended for a deploy entrypoint that splits schema ownership"*), and our
   entrypoint follows that recommendation, shaped against the runtime's `init` scaffold.
2. `APP_HANDOFF_v2.1.0.md` §1 said *"nothing to backfill and no data to prepare"* and FR-13 said
   *"purely additive, no backfill"*. Both are true **about data** and both read, to a deployer,
   as "nothing to do". The required step was not mentioned in the handoff at all.
3. So the documented upgrade path for an existing deployment is: rebuild, restart, watch it crash
   loop, read the container log to discover the missing step.

**This is the FR-8 shape again.** In 2.0.0 the verified-flag backfill did not run on a wheel
install and every user silently became unverified; here an additive DDL does not run and the
container will not boot. Different symptom, same root: *the upgrade path is not exercised on an
existing database before release.*

### The ask (runtime) — any one of these is sufficient

- **Say it in the handoff.** Cheapest fix: when a release changes runtime-owned schema, the
  handoff states "existing deployments must run `bootstrap-schema --reconcile`". A one-line
  addition to a doc we already read carefully.
- **Make it discoverable from the release, not the crash.** Have `bootstrap-schema` exit with a
  distinct, greppable code for "additive reconcile required" so an entrypoint can branch on it
  instead of dying.
- **Ship the recommended entrypoint pattern.** If the intended deploy shape is
  `bootstrap-schema --reconcile` in a container and bare `bootstrap-schema` interactively, say so
  in the scaffold — our entrypoint was modelled on `aindy-runtime init` and inherited the bare form.

### What we are NOT asking for

Auto-applying DDL by default. Whether *our* entrypoint passes `--reconcile` is our call
(`RUNTIME_2_1_0_UPGRADE.md` §7) and does not need a runtime change either way.

### Our own CI has the identical blind spot — app-side follow-up

Worth stating plainly rather than only pointing upstream. `.github/workflows/deploy-bootstrap-guard.yml`
exercises `bootstrap-schema -> deploy_bootstrap -> serve` **on a fresh database**, and it passed
on this very PR while the live stack was crash-looping.

It passes *because* the database is fresh: `create_all` builds `agents` from the new packaged
metadata, so the columns are present and there is nothing to reconcile. The guard can never see
this class of failure, because the failure only exists when a database predates the schema change
— which is the case for every real deployment and no CI run.

**The missing guard is an upgrade-path one:** boot the *previous* runtime against a fresh DB,
then bring up the *new* one against that now-existing DB. That is the shape that would have
caught FR-8 and FR-14 before either reached a running stack. Not built here; the adoption PR is
not the place for it.

### Verified

Reconcile succeeded (`ok: reconciled runtime-owned tables to packaged metadata.` /
`ok: stamped alembic_version_runtime to revision 0016.`), `agents.metadata` (jsonb, nullable) and
`agents.updated_at` (timestamptz, nullable) created, all 7 rows intact, api healthy in ~25s on
`aindy-runtime==2.1.0`.

---

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

## FR-12 — No way to register an agent; the roster is hardcoded in the runtime ✅ CLOSED in 2.1.0 (+ FR-12b)

**Shipped in `aindy-runtime==2.1.0` (2026-08-15)**, in two halves:

- **FR-12 — `registry.register_agent`.** Declarative: records a spec, touches no database
  (plugin load happens long before a session exists). `startup._apply_registered_agents()` upserts
  by `memory_namespace` at boot and *updates* an existing row, so renaming an agent between boots
  needs no manual edit.
- **FR-12b — user-owned agents**, which we did not ask for and is the more useful half:
  `GET|POST /platform/agents`, `PATCH|DELETE /platform/agents/{slug}`,
  `POST /platform/agents/{slug}/restore`.

**Contract details that will bite if assumed otherwise:**

| | |
|---|---|
| `memory_namespace` | **derived, not accepted** — `u:<user_id>:<slug>`. You supply `slug` matching `^[a-z0-9][a-z0-9._-]{0,63}$` |
| `agent_type` | forced to `custom`, not caller-settable |
| `POST` | **not idempotent** (unlike the admin route) — repeated slug is `409`; use `PATCH` |
| Another user's agent | `404`, never `403` |
| `slug` | **immutable on `PATCH`** — it is the tag already written onto that agent's memory nodes |

**Our filed premise was partly wrong.** We wrote that "the only ways to add a row are a runtime
code change or a raw INSERT" — but `POST /platform/admin/agents/register` already existed and was
mounted. The real gaps were narrower: no hook, no path ever wrote `owner_user_id`, and reads were
unscoped.

**The security finding this surfaced is the part worth reading.** The seven platform system
namespaces were **unreserved**: registering with `memory_namespace: "runtime"` took the route's
idempotent-update branch and silently rewrote the platform's own Runtime agent row — for anyone
with admin on the deployment — and the next boot did not repair it, because the seed only
inserted when the row was absent. 2.1.0 reserves all seven in both the hook and the route, repairs
a drifted system row at boot, and adds
`POST /platform/admin/agents/{namespace}/restore`.

**Checked on this deployment 2026-08-15: no drift.** All 7 rows present, `agent_type='system'`,
`is_active=true`, `owner_user_id` NULL, names matching the platform spec (ARM, Genesis, Memory,
Nodus, Platform, Runtime, SYLVA).

**App-side adoption: not done, deliberately.** This unblocks
`docs/specs/TERMINAL_AGENT_SCOPE.md` §4a and the registry half of the Collaborator face, but
building that surface is its own piece of work, not part of a version adoption.

---

### Original filing (2026-08-06) — retained for context

**apps-monolith ref:** found 2026-08-06 while designing the terminal-agent surface
(`docs/specs/TERMINAL_AGENT_SCOPE.md` §4a).

### Today

The `agents` table is well shaped for a general agent registry:

```
id (varchar) · name · agent_type · description
owner_user_id (uuid) · is_active · memory_namespace · created_at
```

`owner_user_id` implies per-user agents; `memory_namespace` gives each agent its own memory
space; `agent_capability_mappings` scopes capabilities by `agent_type`. All of that works — seven
agents are live, each with a namespace, and the mapping table has rows.

**But there is no way to add one.** The roster comes from `_bootstrap_system_agents()` — a
hardcoded list of seven specs inside the runtime's `startup.py`, upserted by
`memory_namespace`:

```python
_SYSTEM_AGENTS = [
    {"name": "ARM", "namespace": "arm", "agent_type": "system", ...},
    {"name": "Genesis", ...}, {"name": "Nodus", ...}, {"name": "SYLVA", ...},
    {"name": "Platform", ...}, {"name": "Runtime", ...}, {"name": "Memory", ...},
]
```

`register_agent_tool()` exists on the platform registry, but that registers **tools**, not agent
identities. There is no `register_agent`, no route, and no syscall. Every live row is
`agent_type='system'` with `owner_user_id` NULL — the per-user half of the schema has never been
exercised.

### Why we need it

We want to register a **terminal agent** — an identity a local MCP client (Claude Code, Codex,
whatever comes next) authenticates as, so that:

- capability scoping is per-agent-type rather than "an MCP client connected, here are 77
  syscalls";
- repo/session context lands in the agent's own memory namespace instead of the user's
  Collaborator memory;
- commits, task completions, watcher sessions and syscall calls attribute to a real platform
  actor, which is what effort attribution needs.

The durable identity should be the **role** (`development.main-runtime`), with the vendor client
as swappable metadata — see FR-13.

Today the only ways to create that row are a runtime code change or a raw `INSERT`. Neither is
something an app should do.

### The ask (runtime) — sliceable

1. **A registration surface for non-system agents.** Either a platform-layer
   `register_agent(...)` an app can call at bootstrap (consistent with the other
   `register_*` hooks), or an authenticated route/syscall for user-owned agents. App bootstrap
   is enough for our case; a route is what a product eventually needs.
2. **Honour `owner_user_id`.** Registration should be able to scope an agent to a user, and
   reads should filter by owner so one user cannot enumerate another's agents.
3. **Keep the idempotent-upsert semantics** `_bootstrap_system_agents` already uses — re-running
   registration must not duplicate.
4. **Reserve the system namespaces.** An app-registered agent should not be able to claim `arm`,
   `genesis`, `nodus`, `sylva`, `platform`, `runtime` or `memory`.

### Related observation, not a request

`AGENT_USER = "user"` exists in `AINDY/db/models/agent.py` and is deliberately excluded from
`SYSTEM_AGENTS`, but no `agents` row is ever created for it. So the user's own agent — the thing
the product surface represents — has no identity or memory namespace today. If FR-12 lands,
registering it becomes possible and the model stops special-casing the terminal.

### References

- Runtime: `AINDY/startup.py` (`_bootstrap_system_agents`), `AINDY/db/models/agent.py`,
  `AINDY/platform_layer/registry.py` (`register_agent_tool` — the near-miss).
- App: `docs/specs/TERMINAL_AGENT_SCOPE.md` §4a, `docs/specs/SURFACE_IDENTITY_BRIEF.md` §1.

---

## FR-13 — `agents` has no metadata field, so identity cannot outlive the vendor ✅ CLOSED in 2.1.0

**Shipped in `aindy-runtime==2.1.0` (2026-08-15).** `agents.metadata` (JSONB) and
`agents.updated_at`, both nullable, purely additive, no backfill.

> **★ The ORM attribute is `Agent.agent_metadata`; the COLUMN is `metadata`.** `metadata` is
> reserved on a SQLAlchemy declarative class (`Base.metadata`), so the attribute had to differ.
> Raw SQL and JSONB queries see the real column name — `WHERE metadata->>'workspace' = 'w1'`
> works as written. Anything going through the ORM must say `agent_metadata`.

Schema arrives via runtime Alembic head **`0016`** (`alembic_version_runtime`). Nothing for the
app-owned `alembic_version` tree.

> **It does not self-migrate, despite "purely additive".** On an existing database the deploy
> entrypoint's bare `aindy-runtime bootstrap-schema` **refuses and exits non-zero**, demanding
> `--reconcile`, which under `set -e` + `restart: unless-stopped` is a crash loop. Verified on
> this stack 2026-08-15. See `RUNTIME_2_1_0_UPGRADE.md` §1a and **FR-14**.

---

### Original filing (2026-08-06) — retained for context

**apps-monolith ref:** found 2026-08-06 alongside FR-12.

### Today

`agents` carries `id`, `name`, `agent_type`, `description`, `owner_user_id`, `is_active`,
`memory_namespace`, `created_at`. There is no JSONB, and no `updated_at`.

### Why that blocks the useful shape

The point of registering a terminal agent is that **the identity is the role, and the client is
an implementation detail**:

```
agent:      development.main-runtime      (durable — id, namespace, history)
provider:   codex  ->  claude_code        (swappable)
workspace:  aindy-runtime
branch:     feature/foo
```

If the provider switches next month, the platform should not think a brand-new agent with no
history appeared. The durable half already works — `id` and `memory_namespace` are
provider-independent. The swappable half has nowhere structured to live: `description` is free
text, and encoding `provider=codex;workspace=...` into it is the kind of thing that looks fine
until something needs to query it.

### The ask (runtime)

1. **Add `metadata JSONB` to `agents`** (nullable, additive). Provider, workspace, branch,
   client version, last-seen — whatever the registrant wants, without further schema changes.
2. **Add `updated_at`**, so "last seen / last re-registered" is answerable. Every other table in
   this schema has one.
3. Optionally expose it on whatever FR-12's registration surface becomes, so re-registering with
   a new provider updates metadata rather than creating a second identity.

Additive and nullable, so nothing existing changes.

### References

- Runtime: `AINDY/db/models/agent.py`.
- App: `docs/specs/TERMINAL_AGENT_SCOPE.md` §4a.

---
## FR-8 — 2.0.0 upgrade: the verified-backfill does not ship in the wheel ✅ CLOSED in 2.0.1

**Closed in `aindy-runtime==2.0.1` (2026-08-05).** `bootstrap-schema --reconcile` now
grandfathers rows that predate a newly added column, so a fresh wheel deployment no longer
strands pre-existing accounts. It does not retroactively repair a database already reconciled
under 2.0.0 — ours was, and needed no repair: **0** accounts created before the upgrade are
unverified (the 12 grandfathered by hand in PR #190 are all `true`). Verified on the live
database 2026-08-05, not assumed.


**apps-monolith ref:** found 2026-08-03 upgrading the live deployment to `aindy-runtime==2.0.0`.

### The symptom

On an existing database, the container crash-looped before serving:

```
error: runtime-owned schema is not ready: Runtime-owned schema requires an explicit
additive reconcile: Runtime table 'users' is missing required column 'is_verified'.;
Runtime table 'users' is missing required column 'verified_at'.
Re-run with --reconcile for an additive column/index fix, or perform the required
offline migration before retrying.
```

`aindy-runtime bootstrap-schema --reconcile` resolved it and stamped `0014`. But afterwards:

```sql
SELECT is_verified, count(*) FROM users GROUP BY 1;
 is_verified | count
-------------+-------
 f           |    12
```

**Every pre-existing account came back unverified** — the exact outcome the model comment
says the migration exists to prevent:

```python
# AINDY/db/models/user.py
# migration, which backfills EXISTING rows to true: those accounts predate verification
# and were never given a chance to confirm, so grandfathering them is the only option
# that does not retroactively lock out every current user.
is_verified = Column(Boolean, default=False, nullable=False, server_default="false")
```

### Why it happens

The backfill lives in Alembic `0014`, and **`0014` is not distributed in the wheel.** Only the
app's own Alembic tree is present in an app-profile image:

```
$ find / -path '*alembic*/versions' -type d
/app/alembic/alembic/versions        # app-owned only — no runtime tree
```

So a wheel-based deployment never runs `0014`. It reconciles from packaged metadata instead,
which applies `server_default="false"` and nothing else. The grandfathering step simply has no
code path on this install shape.

### Why this matters more than it looks

It is not an immediate outage, because `AINDY_REQUIRE_VERIFIED_LOGIN` defaults off. It is a
**latent lockout**: the v2.0.0 handoff invites operators to *"Turn on once your users are
verified"*, and the docs state existing accounts were backfilled. An operator who believes
both statements and flips that flag locks out every pre-existing account at once — including
their own admin.

The handoff's "Run migrations — Alembic 0014, existing accounts are backfilled to verified"
is accurate for a source checkout and silently untrue for a wheel install. Nothing in the
upgrade surfaces the difference.

### The ask (runtime) — sliceable, cheapest first

1. **Make `--reconcile` perform the same backfill `0014` does.** When it adds `is_verified` to
   a table that already has rows, those rows predate verification by definition — set them
   `true` with `verified_at` from `created_at`. This is the one change that makes the
   documented guarantee true on every install shape.
2. Or ship the runtime Alembic tree in the wheel so the documented migration path exists.
3. Failing either, **state the difference in the upgrade notes**: wheel deployments must
   backfill manually, with the SQL to do it, before enabling `AINDY_REQUIRE_VERIFIED_LOGIN`.
4. Consider having `bootstrap-schema` refuse to add a `NOT NULL` column with a security-
   relevant default to a populated table without an explicit acknowledgement — the current
   guard correctly stops *schema* drift but is silent about the *data* consequence.

### What we did app-side

Snapshotted the 12 pre-existing user ids before touching the schema, ran the reconcile, then
applied the grandfathering `0014` would have done, scoped to exactly those ids. Recorded as an
operator note in PR #190.

### References

- Runtime: `AINDY/db/models/user.py` (`is_verified`), `AINDY/runtime_only.py`
  (`_bootstrap_schema`), Alembic `0014`.
- App: PR #190 operator note; `docs/runtime/RUNTIME_DEPENDENCY.md`.

---

## FR-9 — Transactional mail is silently swallowed by any app-registered `email` connector ✅ CLOSED in 2.0.1

**Closed in `aindy-runtime==2.0.1` (2026-08-05)** — resolved as ask (1), the cleanest option:
transactional mail moved to a reserved `transactional_email` type an app connector cannot
intercept. A registered-connector failure on that path now logs at ERROR naming the type,
instead of the single WARNING that made this so hard to find. The no-fallback rule is
unchanged, which is correct.

App-side: we chose to let runtime SMTP carry it (nothing registered under the new type), so
the shape-multiplexing workaround was removed and `_email_connector` is automation-only
again. Verified end to end on the live stack — signup mail and reset mail both deliver.


**apps-monolith ref:** found 2026-08-03 running the 2.0.0 email flows end to end for the
first time.

### The symptom

`POST /auth/register` returned a healthy `202`. No verification mail ever arrived. The only
evidence anywhere:

```
WARNING [connector:email] handler failed: 'payload'
WARNING [email] registered connector failed (no SMTP fallback by design): 'payload'
```

**No verification mail means no new account can complete signup.** Registration reports
success, the user waits for an email that will never arrive, and the deployment looks
healthy. We would not have found this without walking the flow on a live stack — no test,
guard, or boot check surfaces it.

### Why it happens

Two unrelated senders share one connector type.

`apps/automation` registers an outbound `email` connector for user-authored automations
(FR-1). Its actions look like:

```python
{"payload": {...}, "config": {"recipient": ..., "smtp_host": ...}}
```

2.0.0 began routing runtime-owned transactional mail through that same registered type,
with a different shape:

```python
# AINDY/platform_layer/email_channel.py
action = {"type": "send", "to": to, "subject": subject, "body": body}
result = dispatch_connector(CONNECTOR_TYPE, action, user_id=user_id, db=db)
```

Our handler opened with `action["payload"]` → `KeyError`. Combined with the deliberate
no-fallback-on-failure rule, an app-side shape mismatch became *"signup is impossible"*.

### The design tension

The no-fallback rule is **right** and we are not asking for it to change — silently
rerouting mail to a channel the operator did not choose, precisely when the chosen one is
broken, is worse. The problem is that it is paired with a *shared, undocumented* action
contract:

- Registering an `email` connector for automations silently opts you into handling the
  runtime's transactional mail too. Nothing at registration time says so.
- The transactional action shape is not documented anywhere we could code against; we
  learned it by reading `email_channel.py` in site-packages.
- The consequence of getting it wrong is maximal (no signups) and the signal is minimal
  (one WARNING line, no health-check degradation, no startup warning).

### The ask (runtime) — any one of these closes it

1. **Separate the type.** Route runtime transactional mail through its own connector type
   (`transactional_email`), so an app connector for `email` cannot intercept it. Cleanest —
   the two senders have nothing in common but the word "email".
2. **Document and version the action contract.** If the type stays shared, publish the
   transactional action shape as a stable contract, and ideally pass a discriminator app
   handlers can branch on (`action["type"] == "send"` exists but is not documented as the
   discriminator).
3. **Make the failure loud.** A registered-connector failure on an *auth-critical* send
   should degrade the health check or emit a startup/first-failure error, not a lone
   WARNING. "Registration returns 202 but no mail can be sent" should not be a
   log-grepping exercise.
4. **Validate at registration.** Optionally, dispatch a dry-run/probe action at registration
   so a shape-incompatible handler fails fast at boot rather than at the first real signup.

### What we did app-side

`_email_connector` now multiplexes on the action shape: the transactional shape is delivered
over `AINDY_SMTP_*`, the automation path keeps its per-action config behaviour. Three
regression tests cover both shapes and the not-configured error. PR #190.

### References

- Runtime: `AINDY/platform_layer/email_channel.py` (`send_email`, `_send_via_smtp`),
  `AINDY/platform_layer/connector_service.py` (`dispatch_connector`).
- App: `apps/automation/services/automation_execution_service.py`,
  `tests/unit/test_automation_connectors.py`.

---

## FR-10 — Empty string on a typed bool setting crash-loops the container ✅ CLOSED in 2.0.1

**Closed in `aindy-runtime==2.0.1` (2026-08-05)** — resolved as ask (1): an empty value is
treated as unset and falls back to the field default, across **28** typed bool settings
rather than just the two that bit us. Our explicit `:-false` defaults stay as documentation
of intent; reverting them would gain nothing. Verified: `restarts=0`, zero validation errors
on the 2.0.1 container.


**apps-monolith ref:** found 2026-08-03 deploying 2.0.0.

### The symptom

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
AINDY_REQUIRE_VERIFIED_LOGIN
  Input should be a valid boolean, unable to interpret input
  [type=bool_parsing, input_value='', input_type=str]
```

The container restart-looped at `aindy-runtime bootstrap-schema`, before serving, before
health checks — 27 restarts in our case.

### Why it happens

`AINDY_REQUIRE_VERIFIED_LOGIN` is a typed `bool` on `Settings`, and the idiomatic Compose
default for an optional variable produces an **empty string**, not an absent one:

```yaml
AINDY_REQUIRE_VERIFIED_LOGIN: "${AINDY_REQUIRE_VERIFIED_LOGIN:-}"   # -> ""
```

To an operator, `""` reads as "not set" / "leave it off" — which is also what the
documentation recommends for this flag. To pydantic it is an unparseable bool, and the
process dies.

**This is our bug and we fixed it** (`:-false`). We are filing it because the failure mode
is disproportionate and generic, not because the validation is wrong. It is the second time
this exact shape has bitten this deployment — `AINDY_NEXT_ACTION_ACTING` did the same thing
earlier, and our compose file carries a warning comment about it three lines above where we
reintroduced it.

### The ask (runtime) — small, and it prevents a class of outage

1. **Coerce empty string to "unset" for optional typed settings**, so `""` falls back to the
   field default instead of killing the process. This is the fix — empty-means-default is
   what every operator already assumes, and it is what `${VAR:-}` produces.
2. If validation must stay strict, **fail with an actionable message**: name the variable,
   the expected values, and that empty is not accepted — and ideally validate all settings
   at once so an operator sees every bad variable in one restart rather than discovering
   them one crash at a time.
3. Note in the deployment docs which settings are typed `Settings` fields versus plain
   `os.environ` reads. From outside the runtime these are indistinguishable, and only the
   former are lethal. We maintain this distinction by hand in comments today.

### References

- Runtime: `AINDY/config.py` (`Settings`), the `AINDY_REQUIRE_VERIFIED_LOGIN` and
  `AINDY_NEXT_ACTION_ACTING` fields.
- App: `docker-compose.prod.yml`, `.env.example`; PR #190.

---
## FR-11 — `invoke_runtime_callback`: a 10s non-configurable budget around a cold subprocess import ✅ CLOSED in 2.1.0

**Shipped in `aindy-runtime==2.1.0` (2026-08-15).** `AINDY_RUNTIME_CALLBACK_TIMEOUT_SECS`,
default **30s**, resolved at call time — so it can be changed without a restart. We take the
default; nothing app-side to wire.

Two things from the runtime team's response worth keeping:

- **Our filed mechanism was wrong**, as already recorded below in strikethrough:
  `bootstrap_register` fires only for `runtime_agent_defaults`, not a 16-app bootstrap. The real
  cost is a fresh subprocess `import_module` pulling an app's transitive graph.
- **It was also the cause of `FLAKY-1`**, a ~50% runtime-side test failure that had been blocking
  their merges at random. The fragile-shape argument turned out to be understated — it *was*
  failing, just not visibly to us.

---

### Original filing (2026-08-05) — retained for context

**Filed 2026-08-05 while verifying the 2.0.1 upgrade. Read the framing before triaging: nothing
is broken, and this cost us nothing. It is filed because the shape is fragile, not because it
failed.**

### What we saw

Immediately after recreating the api container on 2.0.1, it went `unhealthy` and stopped
answering, with this repeating roughly once a minute:

```
subprocess.TimeoutExpired: Command '['/usr/local/bin/python', '-m',
  'AINDY.platform_layer.runtime_callback_worker']' timed out after 10.0 seconds
RuntimeError: runtime callback command timed out
```

### Why it is not a defect

It self-resolved and does not reproduce once the container is warm:

- **0** callback timeouts in the following 6 minutes.
- `scheduler.reminders` has recorded **19,370** autonomy decisions, latest during the same
  window — the evaluator completes normally.
- `/api/version` steady at 25–740ms across a 3-minute sample; health `healthy`.

**Diagnosis: a cold-start artifact.** The container took ~285s to become responsive on this
host. Scheduler ticks firing into that window each spawned a worker that had to cold-start the
app stack, could not finish inside 10s, and was killed — adding load to precisely the
contention that made them slow. Once warm, every call completes well inside the budget.

We nearly shipped circuit breakers across three apps' scheduler jobs for this before checking
whether it reproduced. It does not. Flagging that explicitly so nobody else spends the
afternoon.

### The shape that is worth changing anyway

```python
# AINDY/platform_layer/runtime_callback_host.py
def invoke_runtime_callback(spec, *, argument=None, timeout_seconds: float = 10.0):
```

Three properties compound:

1. **The budget is hardcoded** — `10.0` as a parameter default, and the caller in
   `registry.py` does not pass one, so there is no env or settings override. A deployment on a
   slower host has no lever.
2. **The work inside it is not small.** ~~The payload carries `bootstrap_register`, so the
   subprocess re-runs app bootstrap — 16 apps here.~~ **Corrected 2026-08-06 by the runtime team,
   and re-verified app-side.** `registry.py:410` sets that flag only for
   `AINDY.platform_layer.runtime_agent_defaults`, and the worker uses it to call that one
   module's `register()` — it is not a 16-app bootstrap. The real per-call cost is a fresh
   subprocess running `importlib.import_module` on an app module and pulling its transitive
   import graph. Expensive for the same reason by a different route, so the ask is unchanged —
   but anyone building the fix should work from the right cause.
3. **It is invoked from scheduled jobs**, so the failure repeats on an interval, and it repeats
   *hardest* exactly when the host is slowest. The failure mode is self-amplifying: the load it
   adds is the load that causes it.

On a genuinely slow host — or a larger app profile, or a smaller container — the cold-start
window widens and this stops being transient.

### The ask (runtime) — small, none urgent

1. **Make the timeout configurable** (`AINDY_RUNTIME_CALLBACK_TIMEOUT_MS` or similar), the way
   `AINDY_NODUS_MAX_EXECUTION_MS` / `AINDY_NODUS_BOOT_ALLOWANCE_MS` already are for the same
   class of problem — that precedent exists precisely because an app-profile cold start does
   not fit a runtime default.
2. **Avoid re-bootstrapping per call** if the callback does not need the full app graph — a
   warm worker, or a narrower registration, removes the cost rather than budgeting for it.
3. **Back off on repeated failure.** A callback that has timed out N times in a row could stop
   being retried on the next tick, so a cold start cannot be amplified by the scheduler.
4. Optionally, log the first occurrence at WARNING with the elapsed time and the fact that a
   cold start is the likely cause. The current traceback per tick reads like a live incident;
   ours was not one.

### App-side

**No change made, deliberately.** The four scheduled call sites
(`apps/tasks/bootstrap.py` ×2, `apps/analytics/bootstrap.py`, `apps/masterplan/bootstrap.py`)
call `evaluate_live_trigger` unguarded, which is fine while the callback completes when warm.
If item 3 lands upstream we need nothing; if this ever reproduces on a warm container we will
add a breaker at those sites and reopen this.

### References

- Runtime: `AINDY/platform_layer/runtime_callback_host.py` (`invoke_runtime_callback`),
  `AINDY/platform_layer/registry.py` (the wrapped-evaluator call site, no timeout passed),
  `AINDY/agents/autonomous_controller.py` (`evaluate_live_trigger`).
- App: `apps/tasks/bootstrap.py` (`_scheduler_check_reminders`,
  `_scheduler_check_task_recurrence`); `docker-compose.prod.yml` (the
  `AINDY_NODUS_*_MS` precedent and its comment).
- Context: `docs/runtime/RUNTIME_2_0_1_UPGRADE.md`.

---
## FR-7 — Memory: four defects that make recall return the wrong things ✅ CLOSED in 2.0.0

**Closed in `aindy-runtime==2.0.0`; flagged by the runtime team 2026-08-06 as stale here, and
verified app-side the same day.** All four fixes are present in the installed 2.0.1 wheel, in
`AINDY/memory/memory_capture_engine.py`:

| Defect | Fix in source |
|---|---|
| MEM-POLICY-KEY-1 | `_policy_base_significance` (line 100) — reads `significance` → `base_score` → `default_significance` |
| MEM-DEDUP-TRACEID-1 | `normalize_for_dedup` (line 130) |
| MEM-FORCE-UNGATED-1 | `_forced_capture_suppressed` (line 150) — an explicit `min_significance` is honoured even for forced captures |
| MEM-IMPACT-IGNORES-SIGNIFICANCE-1 | `blend_impact_with_significance` (line 203) — declared significance floors the read-side score |

**Adoption already happened, ahead of this doc.** PR #192 removed the duplicate
`default_significance` key from all five policy modules once 2.0.0 read `significance` first,
and `apps/automation/memory_policy.py` records why suppressing `flow_completion` previously did
nothing — `force=True` skipped the gate until `_forced_capture_suppressed` landed. So the code
was current and only the status line was behind.

**Consequence worth acting on:** per-domain memory policy work was parked "until FR-7's
impact_score fix ships". It has shipped, and is running in this deployment. That work is
unblocked.

---

### Original filing (2026-08-02) — retained for context

**apps-monolith ref:** found 2026-08-02 while auditing what the system actually remembers.
Measured on a live corpus of 1,799 memory nodes.

### The symptom

Recall (`get_relevant_memories`, which feeds the Infinity loop) returns eight memories for
our only real user. All eight:

```
4.00  Completion finalization failed: Required system event 'execution.completed'...
3.25  Completion finalization failed: Required system event 'execution.completed'...
1.50  Completion finalization failed: Required system event 'execution.completed'...
1.50  Completion finalization failed: Required system event 'execution.completed'...
      Latency spike detected at 5417.09ms
      Repeated failures detected (2 recent failures)
      execution.started from analytics.linkedin.manual
      execution.started from research
```

Four copies of one bug (fixed the same day), two feedback-detector counts, and two
content-free labels. No domain outcome, no decision, nothing a strategy could act on.

### MEM-POLICY-KEY-1 — the validator and the engine disagree on a key name

`validate_memory_policy` **requires** `significance` or `base_score`:

```python
if policy.get("significance") is None and policy.get("base_score") is None:
    _fail(...)
```

`MemoryCaptureEngine._score_significance` **reads** `default_significance`:

```python
base = float(capture_rule.get("default_significance", 0.4))
```

So a policy that satisfies the validator has **no effect on the score** — base always
falls back to 0.4. All five of our domain policies were in this state; every declared
significance was inert. (`register_memory_significance_rule` is not exported either, so
the `get_memory_significance_rule` path is unreachable from an app.)

**Ask:** have the engine read `significance`/`base_score` — the keys the validator
demands — or have the validator demand the key the engine reads. Either is fine; the
present pair cannot both be satisfied. We have worked around it by declaring both keys.

### MEM-DEDUP-TRACEID-1 — dedup is exact-match, and content embeds a trace id

`_is_duplicate` compares content exactly. The four rows above are 4 rows / **4 distinct
contents** — identical except for the trace id inside the message. The same recurring
failure therefore never deduplicates and consumes half the recall budget.

**Ask:** dedup on a normalized form (strip trace/run/correlation ids), or on
`(event_type, source, node_type)` within a window, rather than raw content equality.

### MEM-FORCE-UNGATED-1 — `force=True` system capture bypasses every policy

`capture_system_event_as_memory` captures 8 event types with `context={"significance": 1.0}`
and `force=True`, which skips the `min_significance` gate entirely. Three of those types
(`execution.started/completed/failed`) fire on every pipeline run. Result: **1,076 nodes
with the identical content `"execution.started from async"`** — 60% of the whole corpus —
and the owned subset of them reaches recall as content-free labels.

**Ask:** either exclude `execution.started` from `AUTO_MEMORY_EVENT_TYPES` (a "something
began" record has no recall value), or let a policy gate forced captures too. We cannot
suppress these app-side: `force=True` is checked before the policy is consulted.

### MEM-IMPACT-IGNORES-SIGNIFICANCE-1 — the write lever and the read lever are disconnected 🔴 **the important one**

This is the root cause of the symptom at the top, and it makes the other three secondary.

Recall ranks by `impact_score`. `impact_score` is computed **only** from the causal event
graph:

```python
return round(len(downstream) + (trace_depth * 0.75) + failure_bonus, 4)
```

`significance` — the thing a domain policy declares, the only quality signal an app
controls — **is not a term in it.** And `impact_score` defaults to `0.0` when there is no
`source_event_id`, which is the case for every direct `queue_memory_capture` call.

Measured consequence:

```
impact  node_type  source_agent  content
 4.00   outcome    system        Completion finalization failed: ...
 3.25   outcome    system        Completion finalization failed: ...
 1.50   outcome    system        Nodus worker exceeded 45000ms hard limit
 0.00   decision   genesis       Masterplan locked: V1 (posture: Accelerated)
```

`Masterplan locked` is declared `significance: 1.0`, `node_type: decision`,
`memory_type: decision`, shared to the `genesis` namespace — the single most deliberate
memory the system writes. **It scores 0.00 and is never recalled.** Both `decision` nodes
in the corpus score 0. Every node with non-zero impact has `source_agent = system`.

So an app cannot make a memory recallable. It can decide what to store and how to label
it; it cannot influence what comes back. Everything that surfaces is a runtime-captured
system event, and `failure_bonus` (1.5 vs 0.5) means failures win — which is exactly the
recall we observe.

**Ask:** make `significance` a term in `impact_score` — or rank recall on a blend of the
two. Any weighting is fine; the requirement is only that a domain declaring a memory
important can cause it to be recalled. Without this, domain memory policies are
decorative and the federated model (per-agent memory, `recall_from_agent`,
`shared_namespaces`) has no path into the Infinity loop, which is its main consumer.

**Partial app-side workaround, not a fix:** a domain can pass `trace_id`/`source_event_id`
in `extra` so impact is computed rather than defaulted. That lifts a domain decision from
0.0 to roughly `depth*0.75 + 0.5` — still below any failure at 1.5+. It reorders nothing
that matters.

### Not asked for, noted

There is no decay or invalidation: the top-ranked memory is a defect fixed hours earlier
and still outranks everything. That is a design conversation, not a defect.

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
  `docs/verification/FRONTEND_WALK_LOG.md`; forgot/reset delivery depends on **FR-1**.

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
> `docs/infinity/INFINITY_LEARNED_RECURSION_SCOPE.md`). FR-3 is the *autonomous-acting*
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
  already lives here at `docs/operations/INVARIANTS.md` (section numbers preserved).

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
