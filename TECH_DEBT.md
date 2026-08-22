# Technical Debt

> **Reconciliation note (2026-07-17).** The act-on-insight + Infinity-hygiene arc closed a
> batch of items tracked below; each is updated inline. Resolved this arc: ARM self-tuning
> (#80), Search Execution Layer (#81), Freelance Revenue Intelligence + consumption wires
> (#82/#83), rippletrace LLM content (#88), `register_nodus_workflow` adoption (#90),
> task-completion idempotency (#91), ARM analysis-quality signal → Infinity (#92), social
> metrics read-through (#93). The learned REFLECT recursion shipped **shadow + advisory**
> (#85/#86), default-off (Phase 2 gated on the 3b-full decision + a soak). Runtime feature
> requests filed + triaged (#87/#89, `docs/handoffs/RUNTIME_FEATURE_REQUESTS.md`): FR-2
> (`register_nodus_workflow`) and FR-3 (Next-Action acting) were already shipped upstream;
> **FR-1 (connectors) is the net-new runtime work.** Still open app-side: Search v4, identity
> inference, SYLVA, frontend lint residuals, Freelance agent-tools (Phase 2).

## RUNTIME-PIN-FLOAT-1: an image rebuild no longer reproduces the adopted runtime (app-owned, P2)

**Status: OPEN (found 2026-08-22).** `pyproject.toml` pins `aindy-runtime>=2.4.1,<3.0`. PyPI
published **2.5.0 on 2026-08-20T12:38:14**, so every build since — local *and* CI — resolves to
2.5.0 while the repo's docs, upgrade notes and `RUNTIME_2_4_1_UPGRADE.md` all describe 2.4.1.
Rebuilding the api image on 2026-08-22 installed 2.5.0 unasked; there is no
`RUNTIME_2_5_0_UPGRADE.md`, and every prior minor (2.0.1, 2.1.0, 2.2.0, 2.3.0, 2.4.1) has one.

**Undocumented is not untested here:** CI runs at 13:14 (`main`) and 13:43 on 2026-08-20 both
post-date the publish and both passed. What is missing is the adoption pass, not evidence.

Two consequences: *"matches `main`"* and *"matches what `main` was adopted against"* have
diverged; and trying a new minor is **not** a free experiment, because `docker/entrypoint.sh:99`
has `aindy-runtime serve` **self-migrate the runtime schema at boot** — recreating onto a newer
image migrates the database with no clean path back. (2.3.0 -> 2.4.1 happened to need no
migration; `alembic_version_runtime` stayed at `0016`. That is luck, not a guarantee.)

**Resolve by either:** running the 2.5.0 adoption pass and moving the floor, or making builds
reproducible (constraints file / build arg) so an image stops depending on the date it was built.
The 2.5.0 image is kept locally as `aindy-apps-monolith-api:runtime-2.5.0` so the adoption pass
does not have to rebuild it.

---

## POSTGRES-CRASH-RESIDUAL-1: the cluster still crash-restarts after PR #234 (undiagnosed, P2)

**Status: OPEN (found 2026-08-22).** PR #234 fixed mongo's `mongosh` healthcheck, which was
driving the Docker VM into OOM and taking postgres with it. It helped a great deal — cluster
reinitialisations fell from **76/day** to roughly **11/day** — but it did **not** end them, and
the claim that it did should not be relied on. Reinits per day with the fix demonstrably live:
08-20 **10 after** the 03:40 fix, 08-21 **1**, 08-22 **11**.

**The OOM mechanism is not visible in the evidence.** Across the postgres container's whole life
its log holds **185 `exited with exit code 2`, 4 `terminated by signal 13`, and zero
`terminated by signal 9`.** A kernel OOM-kill is reported as signal 9; exit code 2 is a backend
`_exit(2)` from its `SIGQUIT` handler. The Docker VM's `dmesg` has no OOM records either — but it
resets when the VM restarts, so that is absence of evidence only. Carry the OOM story as
**plausible, not established**, and the residual killer as **unknown**.

Next step is observation, not a fix: catch a burst (they cluster in the morning) with `dmesg`
retained and host paging counters sampled, before theorising.

---

## RUNTIME-GUEST-CONFINE-1: Nodus guest scripts run unconfined (runtime-owned, P0)

**Status: ✅ CLOSED in `aindy-runtime==2.2.0` (2026-08-16).** The guest VM was being built with
none of the confinement arguments it accepts. The fix denies all three classes — **31 builtins**
now raise `SandboxError` naming the flag: 7 subprocess, 18 network (all `http_*` and `_async`
variants), 6 host environment (including the writes `env_set` / `env_unset`).

**Our exposure was zero, verified app-side rather than taken on trust.** Scanned every Nodus
source in this repo — `apps/analytics/nodus/reasoning_apply_v1.nd` and the `.nodus/` tree — for
any denied builtin: no matches. Also confirmed **nothing generates Nodus source at runtime**
(`analytics/bootstrap.py:225` registers packaged `.nd` files from disk and nothing else), which
was the runtime team's one caveat on their own measurement.

**The app-side posture below is therefore retired.** If a future script needs one of the denied
builtins, the mediated seams are `call_tool(...)` for outbound effects (enforces the run's scoped
capability token) or bare `sys(...)` for runtime capabilities; configuration should arrive via
flow state or `input_payload` rather than host env. There is deliberately **no env var to disable
the confinement** — per-execution declaration is `EXEC-ENV-BIND-1`, still open upstream.

---

### Original entry (2026-08-15) — retained for context

**Status:** Open upstream, recorded here 2026-08-15 because **we run Nodus scripts** and the
mitigation until it ships is an app-side posture, not a code change.

Reported by the runtime team in `APP_HANDOFF_v2.1.0.md` §7. A guest script executed through the
runtime reaches `subprocess`, network and the host environment **without passing the syscall
dispatcher, the capability token, the effect ledger or the egress guard**. Demonstrated, not
inferred: a guest script created a file on the host filesystem.

**Do not read the sandbox-escape gate as covering this.** That suite (17/17 PASS) certifies the
Tier-2 extension sandbox reached through `plugin_host.py`. The guest VM is a different seam and
has never been in its scope, so "17/17 PASS" and "the guest runs unconfined" are both true.

**Mitigation until the fix ships: treat Nodus script content as trusted input.** Scripts arrive
through an authenticated route, but they are *data*, not deployed code — the same distinction that
made the ARM file-path issue (#194) a real exposure rather than a theoretical one. Concretely:
do not add a surface that accepts `.nd` content from an untrusted party, and keep
`AINDY_REASONING_NODUS_NATIVE` soak-gated as it already is.

The runtime team reports the fix is three keyword arguments and that no first-party script in
either repository uses the affected modules, so adoption should be a version bump with no app
change. **Revisit on the release that closes it.**

---

## APP-DEPLOY-1: server deploy artifact (app-consuming-the-framework image)

**Status:** Resolved (2026-07-13). App-owned. Scaffold + a real Linux build/boot test done; the
fresh-DB schema-guard bug found and fixed; the clean-ownership split is now wired to the runtime's
`bootstrap-schema` command (shipped in aindy-runtime 1.7.0); and a CI regression guard
(`.github/workflows/deploy-bootstrap-guard.yml`) exercises the fresh-DB path end-to-end on Linux —
`bootstrap-schema` (runtime tables + baseline) → `deploy_bootstrap.py` (app tables + baseline) →
`serve` boots app-profile (guard accepts) → idempotency re-run — on every deploy-path PR. It runs
the entrypoint's exact steps, so a dedicated Docker image rebuild is no longer needed to catch a
regression here.

**Schema-guard bug — FOUND + FIXED (2026-07-11).** A real Linux build/boot test (deploy image on
the test network, driving one agent run over HTTP) showed the entrypoint's `alembic upgrade head`
**fails on a fresh DB**: the 100+ pre-split app revisions rebuild the *runtime-owned* tables
(`agent_runs`, `execution_units`, `users` …) at a drifted schema, and `aindy-runtime serve`'s
startup guard then refuses to boot (`RuntimeError: Runtime-owned schema is incompatible with
packaged metadata`). `alembic/alembic/env.py`'s `include_object` only excludes those tables from
*autogenerate* — replaying the historical revisions still builds them drifted. The runtime is
behaving correctly (the guard is doing its job). **Fix:** the entrypoint now calls
`scripts/deploy_bootstrap.py` — fresh DB → `Base.metadata.create_all` from packaged metadata (so
runtime tables match the guard) + `alembic stamp head`; existing DB → `alembic upgrade head`.
Verified: with `create_all` (skipping the drifted alembic build), serve boots app-profile
(default-apps, 17 apps) and drives a run through plan→approve→execute on Linux.

**Clean-ownership split — WIRED (2026-07-13, aindy-runtime 1.7.0).** The requested runtime command
shipped: `aindy-runtime bootstrap-schema` builds the runtime-owned tables from packaged metadata AND
stamps `alembic_version_runtime` (idempotent; `--reconcile` for additive drift). The entrypoint now
runs it FIRST, then `scripts/deploy_bootstrap.py` handles only the app side (fresh: create_all — the
runtime tables already exist and are skipped — + `alembic stamp head`; existing: `alembic upgrade head`).
This gives both version lines a proper baseline, so a future runtime schema upgrade has a stamped
`alembic_version_runtime` to migrate from (the gap the interim app-side create_all couldn't close).
Running `bootstrap-schema` on an existing DB also back-fills that baseline on DBs first built by the
interim create_all-only path. (Previously-failed old-entrypoint deploys never booted past the guard,
so there are no successfully-deployed pre-fix DBs to migrate; a fresh redeploy picks up the split.)

**Context:** The apps repo shipped only `client/Dockerfile` (frontend) and
`docker-compose.test.yml` (datastores for the test runner). It had no server deployable for the
app profile — an image that installs the pinned `aindy-runtime` and provides the app plugin
manifest so `apps.bootstrap` registers the domain apps into the runtime via the plugin ABI.

**Delivered (this change):**
- `Dockerfile` — installs the app package (pulls `aindy-runtime>=1.9.0,<2.0`), copies the
  app-profile inputs (`aindy_plugins.json`, `apps/`, `alembic/`, `alembic.ini`), and serves via
  `aindy-runtime serve` from the repo root (shape follows the runtime's own `aindy-runtime init`
  scaffold: `libpq-dev`, `AINDY_HOST=0.0.0.0`).
- `docker/entrypoint.sh` — runs `scripts/deploy_bootstrap.py` (fresh DB: `create_all` from
  packaged metadata + `alembic stamp head`; existing DB: `alembic upgrade head`), then execs
  `aindy-runtime serve`. A `PRE_SERVE_CMD` hook is available for a runtime pre-serve step if the
  deploy contract adds one. (Originally a bare `alembic upgrade head`; see the schema-guard fix above.)
- `docker-compose.prod.yml` — `api` (built app image) + Postgres/pgvector (persistent) with a
  `/health` healthcheck; Redis under a `full` profile and Mongo optional, mirroring
  `aindy-runtime init`.

**Verified so far (2026-07-05):** against the pinned runtime `1.5.3` (the local venv was stale at
`1.5.1` and was upgraded), the app boots app-profile (boot_profile=default-apps,
app_plugin_count=17) and `scripts/check_api_reference.py` reports 0 drift. The Docker image itself
is still unbuilt/untested here (no Docker in the dev env).

**Open items:**
1. **App-tree migration ordering — RESOLVED (2026-07-13).** The entrypoint splits ownership:
   `aindy-runtime bootstrap-schema` (1.7.0) builds + stamps the runtime tables first, then the app
   builds its own — no ordering hazard vs the runtime guard, and both Alembic baselines are stamped.
2. **Build/boot test — DONE (2026-07-11).** Built the image and ran it against a live
   Postgres/Redis/Mongo stack on Linux: serve boots app-profile (`/api/version` → default-apps,
   17 plugins) and drives a real agent run register→plan(Claude)→approve→execute over HTTP. This
   surfaced (and fixed) the fresh-DB schema-guard bug above.
3. **Env-name/driver confirmation.** `DATABASE_URL` uses the psycopg2 scheme; `REDIS_URL` /
   `EXECUTION_MODE=distributed` are assumed from the runtime scaffold — confirm against the
   runtime config surface.
4. **CI + hardening.** Add a container build-smoke to CI (mirroring the frontend one); consider a
   multi-stage build to drop the toolchain; the listen port is `AINDY_PORT`.

**Related doc fix (2026-07-05, done):** the pinned runtime exposes `aindy-runtime serve`, not
`aindy-runtime-api` (which ships in no package). Corrected across `CLAUDE.md`, `README.md`,
`docs/apps/RUNTIME_DEPENDENCY.md`, `docs/apps/APPS_MONOLITH_REPO_SHAPE.md`,
`LIVE_VERIFICATION_SCOPE.md`, the `apps/agent/bootstrap.py` comment, and `.env.example`
(the last three `.env.example` occurrences swept 2026-07-15).

**Reopen trigger:** productionizing the app profile, or a runtime release that changes the boot
entrypoint / migration contract.

---

## INFINITY-COMPLETION-HOOK-BOUNDARY-1: agent completion hook no-op'd across the extension boundary — RESOLVED (aindy-runtime 1.6.1)

**Status:** **RESOLVED (2026-07-09).** Fixed runtime-side in aindy-runtime 1.6.1 (PR #209);
the app hook was adapted to the boundary-preserving contract and the Next-Action ledger work
landed on top. See Resolution below.

**Symptom (as found):** `apps/agent/agents/runtime_extensions.py::handle_agent_run_completed`
(registered via `register_agent_completion_hook("default", …)`) returned immediately at its
`if run is None or db is None: return None` guard, so it never ran the `analytics.infinity_execute`
orchestrator on agent completion — post-agent-completion Infinity loop enforcement was silently
dead, and the runtime recorded its default NextAction instead of the app's decision.

**Root cause (runtime-owned; NOT a 1.6.0 regression):** the runtime invokes completion hooks
through `run_agent_completion_hooks`, which passes the context through `sanitize_extension_context`
(`AINDY/platform_layer/extension_boundary.py`) — dropping `db` (a `_BLOCKED_ROOT_KEYS` entry) and
redacting the `run` ORM object. Per the runtime team this sanitize has been latent **since v1.0.0**
(commit 93d9c84, 2026-05-20); before 1.6.0 the hook ran with `db=None` too, but its return was
discarded, so nothing surfaced. 1.6.0's Gap-4 change (`execution.py:220` began *consuming* the
hook's returned NextAction) is what made the long-standing gap **visible** — the app's "dead since
we adopted 1.6.0" was right about visibility, wrong about cause. Compounding it, the
`agent_completion_hook` surface was not in `_STATEFUL_IN_PROCESS_CALLBACK_SURFACES`, so it was also
subprocess-isolated (PLANNER-SUBPROC-1) — the same gap already closed for `run_tool_provider` /
`planner_context` (which survive because they read live registry state, not the DB). Completion
hooks are the one surface that genuinely needs the run + a session.

**Resolution — runtime (aindy-runtime 1.6.1 / PR #209, Option A: boundary-preserving):**
- the completion-hook context now carries `run_id` (a string → survives the sanitizer;
  `execution.py:231`); the hook re-fetches the run with its own session;
- `agent_completion_hook` is added to `_STATEFUL_IN_PROCESS_CALLBACK_SURFACES` (runs in-process,
  no longer subprocess-isolated);
- the sanitizer is untouched — the runtime still never hands out a `db`/session/ORM handle; only a
  string id crosses.

**Resolution — app (this change):** floor bumped to `>=1.6.1`; `handle_agent_run_completed` now
reads `run_id` + `user_id`, opens its own `SessionLocal()`, re-fetches the `AgentRun`, runs the
orchestrator, stamps `run.result`, and returns a runtime-coercible NextAction — mapping the loop's
4 decision verbs to canonical verbs (continue / reprioritize / create_new_task →
`trigger_execution`, review_plan → `ask_user`) so `NEXT_ACTION_CHOSEN` records the app's real
decision. Verified end-to-end on 1.6.1 through the real `compat._run_completion_hooks` path.

**Reopen trigger:** any change to the completion-hook context contract, or the runtime moving from
record-first Next-Action to autonomous pre-dispatch action.

---

## RIPPLETRACE-CONTENT-LLM-1: rippletrace content generation is template-only (LLM path dropped in the port)

**Status:** RESOLVED (2026-07-17). App-owned. Found comparing the standalone RippleTrace MVP
(`C:\dev\Rippletrace`) against this app's port; the LLM path was restored 2026-07-17 (Resolution below).

**Context:** The standalone `content_generator` generated post drafts via OpenAI
`gpt-4o-mini` (platform-aware prompt: LinkedIn short-form / Medium long-form / general) with
a deterministic template **fallback** and a `source` provenance field, and
`generate_variations` produced genuinely different variants. This app's
`apps/rippletrace/services/content_generator.py` kept only the template path
(`_build_title` / `_build_hook` / `_build_body` string templates), and `generate_variations`
merely appends "(1)/(2)/(3)" to the title/CTA (cosmetic, not real variation). The
`/generate_content*` and `/generate_variations` endpoints therefore return canned copy, not
model-authored drafts. Documented in `docs/apps/RIPPLETRACE.md` §7.

**Fix when triggered:** route generation through the runtime LLM abstraction rather than a
direct `openai` call — register a rippletrace content tool via `register_tool` (as
analytics/search/arm do) or call the runtime LLM primitive, keeping the existing template
output as the deterministic fallback (and under `settings.is_testing`) so app-profile runs
stay offline/deterministic. Preserve a `source` field so callers can distinguish model vs
template output.

**Resolved (2026-07-17):** `apps/rippletrace/services/content_generator.py` now authors
`generate_content` / `generate_variations` through the runtime LLM abstraction
(`perform_external_call` + `chat_completion`, the same seam search/ARM use), with the
existing template as a deterministic fallback and a `source` field ("llm" | "template") on
every response. The LLM path is skipped under `settings.is_testing` (app-profile / CI stay
offline + deterministic) and on any LLM error. `generate_variations` produces genuinely
distinct model variants when the base is model-authored, else the template "(1)/(2)/(3)"
behavior. Covered by `tests/unit/test_rippletrace_content_generator.py`. No agent-tool
surface was added (rippletrace has none); a `register_tool` content tool remains an optional
follow-up. `narrative_engine.generate_story_summary` (a factual timeline summary, not
creative copy) is intentionally left as deterministic assembly.

**Reopen trigger:** productizing rippletrace content generation beyond post drafts, or
adding an agent-invocable content tool.

---

## TASK-COMPLETE-IDEMPOTENCY-1: `complete_task` has no prior-status guard — repeated completion re-fires side effects

**Status:** RESOLVED (2026-07-17). App-owned correctness issue in `apps/tasks`; guard added
2026-07-17 (Resolution below). Flagged during the Infinity docset review.

**Context:** `complete_task` (`apps/tasks/services/task_service.py:568`) sets
`task.status = "completed"` without checking the task's current status. A second completion
call on an already-completed task re-runs the full side-effect chain: downstream unlock
(`_unlock_downstream_tasks`), a `TASK_COMPLETED` `SystemEvent`, the `ExecutionUnit` status
update, and — via the task-completion orchestration path — an Infinity re-score and memory
capture. Only the `time_spent` accrual is guarded (runs solely when `start_time` is set).
Documented in `docs/apps/INFINITY_ALGORITHM_FORMALIZATION.md` (State Transition Diagram:
"Completed → Completed … repeated completion is allowed by implementation").

**Impact:** duplicate `TASK_COMPLETED` events, duplicate downstream-unlock effects, and
duplicate Infinity loop runs / memory writes for one logical completion — double-counting the
signal substrate the Infinity Algorithm depends on. Low frequency (needs a repeated complete
call) but a real skew in analytics/loop signal counts.

**Resolved (2026-07-17):** `complete_task` (`apps/tasks/services/task_service.py`) now early-returns
`"Task already completed: <name>"` when `task.status == "completed"`, before any mutation or emit —
so a repeated completion re-fires none of the side-effect chain (TASK_COMPLETED event, downstream
unlock, ExecutionUnit update, the Infinity re-score + memory capture, and the `time_spent`
re-accrual). The `sys.v1.task.complete` syscall and `/tasks/complete` route pass the string through
unchanged, so the idempotent return is non-breaking. Regression coverage in
`tests/unit/test_task_complete_idempotency.py` asserts side effects fire exactly once per logical
completion, an already-completed task is an immediate no-op, and `time_spent` is not re-accrued.

**Reopen trigger:** a need to treat other terminal states (e.g. `cancelled`) as idempotent, or a
completion path that bypasses `complete_task`.

---

## INFINITY-RUNTIME-HANDOFF-1: runtime-side Infinity loop closure + cross-doc linkage (handoff to aindy-runtime)

**Status:** **RESOLVED (2026-07-08).** Items 1 & 2 were runtime-side done (PR #160);
item 3's runtime half shipped in **aindy-runtime 1.6.0** (`sys.v1.observability.support_metrics`,
INFINITY-RUNTIME-1 item 3) and the app lever is now wired — `dependency_adapter`
fetches the aggregate into the Infinity support state. See Verification below. The app-side
Infinity docs (`docs/apps/INFINITY_ALGORITHM{,_CANONICAL,_FORMALIZATION,_SUPPORT_SYSTEM}.md`)
were reviewed to complete-or-tracked.

**Context:** The Infinity scoring/orchestrator/loop is app-owned
(`apps/analytics/services/{scoring,orchestration}/`). The runtime owns a complementary audit at
`aindy-runtime/docs/runtime/INFINITY_LOOP_AUDIT.md` covering loop closure at the execution
altitude (`Intent→Plan→Execute→Observe→Memory→Recall→Score→Improve`). Neither docset
cross-references the other, and the runtime-side gaps gate the app-side "force execution through
Infinity" phases.

**Handoff items (all in `aindy-runtime`):**
1. **Reciprocal cross-links** — link `INFINITY_LOOP_AUDIT.md` ↔ the app docset so the two
   altitudes (runtime loop closure vs app KPI/scoring/support layer) are navigable. The app side
   points at the runtime audit; the runtime side now points back (done — see Verification below).
2. **The 5 structural runtime gaps** named in `INFINITY_LOOP_AUDIT.md` — recall→planning link
   broken (Gap 1); event ledger missing `RecallUsed` / `ScoreComputed` / `NextActionChosen`
   (Gap 2); no execution-level score record (Gap 3); no runtime-owned Next-Action engine
   primitive (Gap 4); async jobs outside the loop (Gap 5). Gap 4 in particular gates the
   app-side Infinity Phase 2 ("force major execution through the orchestrator" / pre-dispatch
   control). Confirm they are tracked in `aindy-runtime`'s own TECH_DEBT.
3. **Runtime-gated support inputs** (`INFINITY_ALGORITHM_SUPPORT_SYSTEM.md` Steps 3 & 4) —
   observability aggregates (`AINDY/routes/observability_router.py`) and agent/async execution
   metrics (`AINDY/agents/agent_event_service.py`, `AINDY/platform_layer/async_job_service.py`)
   have no app-facing aggregate syscall/job. The app lever is a `dependency_adapter` fetch once
   the runtime exposes the aggregate — a runtime feature request.

**App-side dependencies:** the app-owned loop-depth residual is tracked separately in
**APP-DEBT-MIGRATED-1** ("Infinity loop autonomy still shallow"); the watcher (a core support
signal) is runtime-owned (`aindy-runtime`: `AINDY/platform_layer/watcher_service.py` +
`AINDY/routes/watcher_router.py`).

**Verification (2026-07-05, updated):** the runtime reciprocated this session — items 1 & 2 are
now **runtime side done**; item 3 remains open.
- #1: **Runtime side done.** `docs/runtime/INFINITY_LOOP_AUDIT.md` now cross-links the app
  docset, so the two altitudes are navigable both ways.
- #2: **Runtime side done.** The 5 structural gaps are now tracked runtime-side as
  **INFINITY-RUNTIME-1** in `aindy-runtime/TECH_DEBT.md` (PR #160 merged). Gap 4 (Next-Action
  engine primitive) — which gates app-side Infinity Phase 2 — is on that board.
- #3: **Resolved (2026-07-08).** aindy-runtime 1.6.0 exposes the aggregate as the
  `sys.v1.observability.support_metrics` syscall (capability `execution.read`; Step 3 request/
  health + Step 4 agent-run/async-job/Infinity-loop-event distributions over an optional
  `window_hours`). The app lever is wired: `dependency_adapter.fetch_observability_support_metrics`
  dispatches it and `orchestration/support_state.gather_support_state` threads the rollup into
  `SupportState.support_metrics` → `loop_context` → `run_loop` → the reasoning engine. It degrades
  to `{}` on an older runtime lacking the syscall, so the floor bump to `>=1.6.0` (not the code)
  is what guarantees the signal.

**Reopen trigger:** a re-triage of the app-side Infinity phases as further runtime loop-closure
capabilities land (e.g. the runtime moving from record-first Next-Action to autonomous
pre-dispatch action — see `AINDY/core/next_action.py`), which would let the app consume the
`NEXT_ACTION_CHOSEN` ledger and align its completion-hook return to the runtime NextAction
contract (app-side Infinity Phase 2 follow-on, not yet scoped).

---

## SOCIAL-IDENTITY-1: social profile ↔ canonical user (username bound; metrics/lifecycle deferred)

**Status:** Username-binding slice DONE (2026-06-28); metrics-duplication slice DONE
(2026-07-17, #93 — `metrics_snapshot` now a read-through projection of analytics, see
Deferred item 1). Remaining items 2–3 deferred (below).

**Context:** Three stores key off the same user UUID — `users` (SQL, runtime-owned:
`id`, `email`, unique-but-nullable `username`), `UserIdentity` (SQL, runtime-owned:
inferred behavioral prefs — *not* a profile), and `SocialProfile` (Mongo, social app:
username, tagline, bio, `metrics_snapshot`, tags). The social username and the
denormalized post `author_username` were set independently of the canonical
`users.username` and could drift/collide.

**Done (apps-only):** `users.username` is now the source of truth. On profile upsert
and post creation the social username is sourced from it (lazy reconcile on write);
when `users.username` is null the social value is kept and flagged
`username_verified=false`. The social app never writes the runtime-owned `users`
table. See `apps/social/services/identity_binding_service.py`.

**Deferred:**
1. **Metrics duplication — RESOLVED (2026-07-17).** The analytics-owned scores
   (`infinity_score` = analytics `master_score`, `execution_speed_score`) are now
   projected **read-through** from `apps.analytics.public.get_user_score` when the
   social profile is served (`social_router._project_profile_metrics`, applied in
   `get_profile` + `upsert_profile`), and `apps/tasks/services/task_service.py` no
   longer writes those into the Mongo profile — it keeps only the task-owned
   `execution_velocity` `$inc` counter (which analytics does not own). The
   social/task-owned fields (`twr_score`, `trust_score`, `execution_velocity`) are
   left untouched. Covered by `tests/unit/test_social_metrics_read_through.py`.
2. **Profile lifecycle** — no `SocialProfile` is created at signup (only `users` +
   `UserIdentity`). Ensure one exists per user; coordinate with the runtime signup
   path (`signup_initialization_service`).
3. **Full canonical profile (cross-repo)** — a runtime-owned canonical profile both
   social and identity project from; requires `aindy-runtime` changes.

**Reopen trigger:** any of the three deferred items, or a runtime task to make
`users.username` non-nullable / guaranteed at signup (which would let the social
layer drop the unverified path).

---

## TASK-TIME-SPENT-UNITS-1: `Task.time_spent` is seconds, not hours (documented; normalization deferred)

**Status:** Documented (2026-06-30). The column stays in **seconds**; the misleading
"hours" comment and a name-colliding metric were corrected. True-hours
normalization is deferred (below).

**Context:** `apps/tasks/models.py::Task.time_spent` was commented `# in hours` but
the write path accrues **seconds** (`time_spent += (now - start_time).total_seconds()`
in `task_service.py`), and every consumer already treats it as seconds — the client
shows `time_spent / 60` as minutes, and completion memory labels it `"s"` /
`"time_spent_seconds"`. There is no live miscalculation: the analytics TWR/effort
formulas read `TaskInput.time_spent` (a **caller-supplied API payload in hours**), a
separate path that never touches the DB column; and the Infinity `execution_speed`
KPI is a 0-100 velocity score computed in `infinity_service.py`, unrelated.

**Done (2026-06-30):** Corrected the model comment to state seconds and cross-ref
`duration` (estimated **hours**, added for continuous-time ETA) and the analytics
hours input; added a clarifying note to `TaskInput`; renamed the completion-time
`save_calculation` metric from `"Execution Speed"` (collided with the KPI) to
`"Task Time Spent (seconds)"`. No behavior/data change.

**Deferred (Option B — normalize to true hours):** convert the write path to hours
(`/ 3600`), update the client display (drop the `/60` minutes rendering), fix the
completion memory labels, and add an Alembic migration converting existing rows
seconds→hours. User-visible and touches the integration-tier timing path (not
app-profile testable), so it was not taken now.

**Reopen trigger:** any consumer needing `Task.time_spent` in hours (e.g. feeding
it into the analytics TWR/effort formulas), or a decision to unify the effort unit
across `duration` (hours) and `time_spent` (seconds).

---

## RTR-1-NODUS-COMPLETION: nodus_vm execute-to-completion — RESOLVED (aindy-runtime 1.5.3)

**Status:** **RESOLVED in aindy-runtime 1.5.3 (2026-07-05).** nodus_vm execute-to-completion
was blocked by two stacked, PG-only, transaction-poisoning runtime bugs (SQLite masked both);
both are now fixed and published, and Gate 2 of `tests/integration/test_nodus_vm.py`
hard-asserts the resumed run reaches a terminal state (pin floor `aindy-runtime>=1.9.0,<2.0`):

1. **#152** (PR #155, v1.5.2) — `ExecutionPipeline.run()` emitted its own `execution.started`
   *before* marking itself active, so the nested flow-runner pipeline reached during a
   scheduler-driven resume tripped the ExecutionContract guard at `system_event_service.py:453`
   ('execution.started emitted outside pipeline'); the swallowed error poisoned the PG txn.
   Fixed by setting `pipeline_active` before the first emit. Verified: zero occurrences in CI
   run 28734012605 on 1.5.2.
2. **#157 / RTR-1-NODUS-IDEMPOTENCY-UUID** (PR #158, v1.5.3) — with #152 cleared, the syscall
   dispatcher's **idempotency gate** cast the run-scoped `execution_unit_id` (`run_<uuid>`, e.g.
   `run_897ef792-...`) to the `ExecutionUnit.id` UUID column
   (`psycopg2.errors.InvalidTextRepresentation`, `syscall_dispatcher.py:511`); the caught error,
   lacking a savepoint, left the txn aborted, so the subsequent `INSERT INTO flow_runs` failed
   with `InFailedSqlTransaction` (`syscall_dispatcher.py:591` → `nodus_execution_service.py:871`)
   and the run never completed. Fixed by only looking up bare-UUID ids and SAVEPOINT/rollbacking
   the lookup. Reproduced on CI runs 28734012605 + 28734198382 (1.5.2); closed in 1.5.3.

**Gate 1 (app-manifest tool in the subprocess) — RESOLVED, full hard pass (2026-07-05):**
reworked from an LLM-driven proof to the deterministic `stub_app_tool` planner (emits a
high-risk `task.create` step — an app-manifest-only tool with no runtime default),
mirroring Gate 2's park→resume→scheduler-drive path with no LLM/key/network. It
**hard-asserts** that `task.create` resolves, dispatches to its syscall, AND its DB write
**completes end-to-end** inside the `nodus_worker` subprocess — the core §5 question,
answered YES. The DB-visibility artifact (`tasks_user_id_fkey`) was closed by committing the
test user via `testing_session_factory` so the subprocess's committed-only connection sees
it (`_login_committed_user`). See **RTR-1-NODUS-APPTOOL-500** below.

**History (the reopened-then-fixed arc for #152):** on 1.5.1 the symptom looked gone on
the passive re-run (run 28727775436) only because, with no scheduler heartbeat, the
resume callback was never dispatched. Driving the scheduler in-process
(`get_scheduler_engine().schedule()`, run 28728594828, 2026-07-05) actually RAN the
resumed segment — and it **still raised** `execution.started emitted outside pipeline`
(`pipeline.py:326` → `system_event_service.py:453`). The 1.5.1 fix wrapped the resume
*callback* in an async-execution context (`nodus_execution_service.py:617-631`), but the
inner **flow-runner pipeline** that emits `execution.started` ran in a context that did
not inherit it. 1.5.2 closed exactly that gap — and surfaced the idempotency-gate bug
above.

**Context:** RTR-1 shipped the opt-in `nodus_vm` agent-execution backend
(`AINDY_AGENT_EXECUTION_BACKEND=nodus_vm`). §5 asked whether tools registered via
this repo's plugin manifest resolve **and execute** inside the `nodus_worker`
subprocess. The first live-Postgres CI run (2026-07-04, runtime 1.5.0) established:

- ✅ Plan generation under nodus_vm (stub + `anthropic_chat` planners).
- ✅ WAIT parking — `AINDY_AGENT_WAIT_BEFORE_HIGH_RISK` inserts an approval WAIT before
  the first high-risk step; the run parks at `status="waiting"` with `wait_state` /
  `correlation_id` / `granted_tools` set.
- ✅ The app-owned resume route (`POST /apps/agent/runs/{id}/resume`, §4) returns 200
  and publishes `agent.approval.granted` scoped to the run's correlation.
- ✅ No tool-resolution failure surfaced in the subprocess (no `"tool not found"`),
  i.e. the app manifest loaded there.
- ❌ **Execute-to-completion does not run under the TestClient integration harness.**
  After resume the run stays `waiting`, and the runtime repeatedly raises
  `RuntimeError: ExecutionContract violation: execution event 'execution.started'
  emitted outside pipeline` (`AINDY/core/system_event_service.py:453`, from
  `AINDY/core/execution_pipeline/pipeline.py:326`). The plan continuation appears to
  run outside the ExecutionPipeline wrapper.

**Root cause (confirmed — runtime-owned bug):** the resumed segment is dispatched by
the scheduler and runs **inline with no enclosing `ExecutionPipeline` context**
(`AINDY/runtime/nodus_execution_service.py` `_execute_agent_segment_chain` never calls
`execute_with_pipeline` / `set_pipeline_active` / `activate_async_execution_context`,
unlike the initial run which enters via `ExecutionPipeline().run`). When the resumed
segment emits `execution.started`, the guard at `AINDY/core/system_event_service.py:453`
sees neither `is_pipeline_active()` nor `is_async_execution_active()` and, with the
default `ENFORCE_EXECUTION_CONTRACT=True`, raises. A live server (scheduler running)
fixes event *delivery* but **not** this — the callback still runs without a pipeline
context. This is not a harness limitation; it is an `aindy-runtime` defect.

**Filed:** `aindy-runtime` issue **#152** (full file:line diagnosis and repro). Local
report: `HANDOFF-runtime-nodus-resume-pipeline-context-bug.md`.

**Partial fix in aindy-runtime 1.5.1 (INCOMPLETE):** the resume callback now wraps
`_execute_agent_segment_chain` in `activate_async_execution_context()`
(`AINDY/runtime/nodus_execution_service.py:617-631`, comment cites #152). But the
`execution.started` that raises is emitted one layer deeper — the inner flow-runner
`ExecutionPipeline` reached via `run_nodus_script_via_flow` → `sys.v1.nodus.execute`
(`nodus_execution_service.py:482,239`) — and that pipeline runs in a context where
`is_async_execution_active()` is still False, so the guard at
`system_event_service.py:453` fires. The async context must be established at (or
propagated into) the inner flow-runner emission, not only around the outer callback.
Empirically shown by driving the scheduler (run 28728594828). **Reopened upstream.**

**Current handling:** `test_nodus_vm.py` Gate 2 (deterministic `stub` planner →
`memory.recall`) hard-asserts parking + resume acceptance + delivery
(`waiters_notified>=1`), then drives the scheduler in-process to run the resumed segment
and **hard-asserts** it reaches a terminal status. On `aindy-runtime>=1.5.3` (both #152
and #157 fixed) this passes end-to-end; a regression of either fix would poison the run's
PG transaction and fail it red. Tool *resolution* in the subprocess and
execute-to-completion are both now proven.

**RTR-1-NODUS-APPTOOL-500 — §5 resolution PROVEN; two blockers retired, one harness
artifact remains (2026-07-05).** Gate 1 (deterministic `stub_app_tool` planner,
`apps/agent/agents/runtime_extensions.py`, emitting a high-risk `task.create` step) now
**hard-asserts** that an app-manifest-only tool (no runtime default) resolves AND dispatches
to its syscall inside the `nodus_worker` subprocess — the core §5 question, answered YES,
with no LLM/key/network. Two things this retired:
- the **egress blocker** (the old LLM-driven Gate 1's create-500 was an
  `anthropic.APIConnectionError` — the runner can't reach `api.anthropic.com`; plan-gen is
  in-process so an LLM was never needed — see History below). The
  `nodus-vm-integration.yml` `ANTHROPIC_API_KEY` preflight gate is removed; the job runs
  unconditionally.
- the **subprocess-boundary hypothesis** (debunked — plan-gen never enters the subprocess).

**`RTR-1-NODUS-APPTOOL-500-DBVIS` — RESOLVED (2026-07-05).** After resolving+dispatching,
`task.create`'s DB write initially failed on `tasks_user_id_fkey` (CI run 28744121782). Root
cause was in the integration harness (`tests/fixtures/client.py`), **not** the product: on
PostgreSQL it registers the test user in a **transactional session that rolls back**
(`db_session_factory` → `db_connection.rollback()`) and monkeypatches `SessionLocal`
**in-process** to that transaction. The `nodus_worker` subprocess uses a **separate,
committed-only** DB connection the in-process monkeypatch cannot reach, so the uncommitted
test user was invisible to it → FK violation. (Same cause as the non-fatal
`system_events_user_id_fkey` violations seen in every completion run — masked there because
those events are non-fatal and `memory.recall` writes no user-FK'd row. In production users
are committed, so a real subprocess sees them.) **Fix:** Gate 1 now creates the test user
**committed** via `testing_session_factory` (engine-bound, commits independently of the
app's rolled-back outer transaction) in `_login_committed_user`, then logs in — so the
subprocess connection sees the user and the write completes. `cleanup_committed_test_state`
TRUNCATEs it between tests. The `task.create` step is now a **hard assert**.

**History — why the old LLM-driven Gate 1 skipped:** it drove `task.create` via the
`anthropic_chat` planner, but `POST /apps/agent/run` returned a generic **500**
`{"message":"Failed to generate plan"}` (`AINDY/agents/runtime_api.py:146` — `create_run`
returned falsy), so it `skip`ped.

**ROOT CAUSE (confirmed 2026-07-05, runtime 1.5.3, CI run 28743569180):** the create-500
is `anthropic.APIConnectionError` — **the CI runner cannot open an outbound HTTPS
connection to `api.anthropic.com`.** The exact skip-surfaced reason:
`AnthropicPlannerError: Anthropic API connection error for model 'claude-opus-4-8':
Connection error.` The SDK already retries connection errors twice by default, so this is
a hard egress block, not a transient blip. The app backend IS entered, constructs the
client (key present, else `_make_client` raises a different error), and the outbound call
fails.

**The prior subprocess-boundary hypothesis is WRONG.** Runtime trace (aindy-runtime 1.5.3):
`create_run` → `compat.generate_plan` runs plan generation **in-process** on the request
thread (`AINDY/agents/agent_runtime/creation.py:36`); the execution backend only affects
`apply_wait_policy` **after** the plan is generated (`planning.py:307`). Plan-gen for
`anthropic_chat` therefore never enters the `nodus_worker` subprocess, and this 500 would
occur identically under `agent_flow` — it is **not** nodus_vm-specific.

**Why the reason stayed invisible across three sessions (triple blind spot):**
1. `generate_plan` catches all backend exceptions and stores the reason on a
   `threading.local` (`_plan_failure`, `AINDY/agents/agent_runtime/shared.py:19`), set on
   the FastAPI threadpool worker and unreadable from the test thread.
2. Its backup `required` `agent_plan_generation` SystemEvent (`creation.py:39-49`) can be
   lost to the `system_events_user_id_fkey` violation observed in the same runs.
3. pytest discards captured logs for **skipped** tests, so the app backend's entry-log
   (PR #48) never displayed — which is why "backend never entered" was recorded, wrongly.

The model id (`claude-opus-4-8`) and forced-tool request shape are valid (claude-api
reference: current `/v1/messages` model; `planner_anthropic.py` omits the
`temperature`/`top_p`/`budget_tokens` that 400 on Opus 4.8). Gate 2's `stub` planner works
because it needs no key/network; `anthropic_chat` needs egress the runner doesn't have.

The model id (`claude-opus-4-8`) and forced-tool request shape were themselves valid
(claude-api reference: current `/v1/messages` model; `planner_anthropic.py` omits the
`temperature`/`top_p`/`budget_tokens` that 400 on Opus 4.8) — the failure was purely the
runner's lack of egress. **How it was diagnosed:** a temporary in-thread diagnostic
(`_diagnose_anthropic_planner`, since removed with the LLM path) called the backend
directly and folded the real exception into the skip reason (CI run 28743569180). The fix
sidesteps it entirely — the `anthropic_chat` backend and `planner_anthropic.py` stay
registered/available for real use, but the §5 gate no longer depends on them.

**nodus_vm is now the app default (2026-07-05).** §5 is fully proven (both gates
hard-assert), so `nodus_vm` was promoted to this monolith's default agent-execution backend:
`apps/agent/bootstrap.py::_select_execution_backend()` does
`os.environ.setdefault("AINDY_AGENT_EXECUTION_BACKEND", "nodus_vm")` on every **non-test** boot
(`settings.is_testing` gate — the integration harness runs no scheduler heartbeat, so it stays
on `agent_flow`; the §5 suite opts in via `pytest.nodus.ini`). An explicit env value (ops, or a
pytest ini) always wins. Production `aindy-runtime serve` boots run the scheduler heartbeat
(`AINDY.startup._start_scheduler_and_jobs`), which drives nodus_vm continuation to completion;
approval-parking stays off unless `AINDY_AGENT_WAIT_BEFORE_HIGH_RISK=true` (runtime default
`False`). Documented in `.env.example`; the `settings.is_testing` gate is regression-locked by
`tests/unit/test_agent_execution_backend_default.py` (if it broke, the test suite would flip to
nodus_vm and hang for lack of a scheduler). The `anthropic_chat` LLM planner remains available
for real (non-CI) use; exercising it in CI would require runner egress to `api.anthropic.com`.

**Reopen trigger:** any regression of either §5 gate (CI red); a decision to revert the default
to `agent_flow` (set the env explicitly, or drop `_select_execution_backend`); or broadening
nodus_vm validation beyond the two §5 gates to the full agent surface (real multi-step LLM
plans, completion hooks, infinity orchestration) under nodus_vm-as-default.

**LITERAL CLAUDE-PLANNED RUN → `completed` — PROVEN (2026-07-19).** The one thing the CI gate
cannot cover (egress) was driven end-to-end on a provisioned host: `docker-compose.prod.yml`
booted with `AINDY_AGENT_PLANNER_BACKEND=anthropic_chat` on a **native-Linux Docker engine**,
and the full loop ran `register → create (Claude 6-step plan) → approve → execute →`
**`completed`** — 6× `AGENT_STEP_COMPLETED`, real side-effects (3 tasks in Postgres). So the
mechanism is now proven *with the real LLM planner*, not just `runtime_local`. The CI-runner
egress block itself is unchanged (GitHub-hosted runners still can't reach `api.anthropic.com`);
the literal loop belongs on a self-hosted/cloud egress host, per `DEPLOYMENT.md`.

---

## NODUS-WARMPOOL-1: per-execution Nodus worker cold-starts the full app stack — RUNTIME FIX SHIPPED (1.10.0)

**Status:** **Runtime fix SHIPPED in aindy-runtime 1.10.0** (warm `nodus_worker` pool, Phases
1–3) — opt-in via `AINDY_NODUS_WARM_POOL=true` (default off). App-side had already mitigated
(2026-07-19) by widening the per-execution budget/pool in the prod compose. **Follow-up (ops,
post-soak):** flip `AINDY_NODUS_WARM_POOL=true` on the deployed stack, then the app-side budget
inflation (`AINDY_NODUS_MAX_EXECUTION_MS`/`_BOOT_ALLOWANCE_MS`, `DB_POOL_SIZE`) can be relaxed
back toward the runtime defaults. Original diagnosis + the app-side mitigation retained below.

`nodus_runtime_adapter` spawns a **fresh `nodus_worker` subprocess per agent execution**, and on
the app profile that subprocess **cold-starts the whole ~17-app stack (~12s+ of imports)** before
the script runs. Against the runtime's default budget (`AINDY_NODUS_MAX_EXECUTION_MS=30000` +
`AINDY_NODUS_BOOT_ALLOWANCE_MS=15000`) a real run on any non-fast host fails with
`Nodus worker exceeded 45000ms hard limit — worker or plugin cold-start hung`. A second amplifier:
every `execution.started` fires memory auto-capture → an embedding-enqueue DB write, and the
fan-out **exhausts the connection pool** (`QueuePool limit … reached`) when each pg round-trip is
slow (the Docker-Desktop-on-Windows failure mode — its VM pg is slow enough that even 20+40
connections can't drain).

**App-side mitigation (shipped in `docker-compose.prod.yml`):** widen the budgets + pool for the
app profile — `AINDY_NODUS_MAX_EXECUTION_MS=120000`, `AINDY_NODUS_BOOT_ALLOWANCE_MS=60000`,
`DB_POOL_SIZE=20`/`DB_MAX_OVERFLOW=40`, and the DB reap timeouts to 120s (see "Tuning for slower /
cold-start-heavy hosts" in `DEPLOYMENT.md`). With those + a **native-Linux** pg (fast round-trips),
the full run reaches `completed`. Bigger pools against a *slow* pg make it worse — a faster
datastore, not larger limits, is the real lever.

**Runtime-owned fix (the real one):** a **warm `nodus_worker` pool** (or a persistent worker) so
executions don't each pay the app-stack cold-start, making the tight default budgets adequate and
removing the per-run import storm. Filed as a runtime feature request. Referenced from
`BUILD_PLAN.md` (validated foundation).

**Reopen trigger:** runtime ships a warm-pool / persistent worker (then the app-side budget
inflation can be relaxed back toward the runtime defaults).

---

## MASTERPLAN-CONNECTOR-RUNTIME-1: automation connectors registration + capability-enforcement surface (FR-1) — ADOPTED

**Status:** RESOLVED (2026-07-18). The runtime shipped the FR-1 surface in
aindy-runtime **1.8.0** (`register_connector` + `connector_service.dispatch_connector`
+ `authorized_external_call`), and the app has adopted it.

**What shipped app-side:** the hardcoded `if/elif` ladder in
`apps/automation/services/automation_execution_service.py::execute_automation_action`
is gone. The six outbound connectors (social, crm, email, webhook, stripe,
subscription) are registered via `register_automation_connectors()` (called from
`apps/automation/bootstrap.py::_register_connectors`) with capabilities
`outbound.<type>`, and dispatched through `dispatch_connector`, which runs each
handler under its capability's authorization scope (recipient/domain allowlist, rate
limit, socket-level egress guard, JIT credential vaulting). Each handler performs
outbound I/O through `ctx.call` (the enforcement-enabled successor to
`perform_external_call`). `execute_automation_action` unwraps the `{success, result,
error, denied}` envelope: success → result; `denied` → `PermissionError`; other
failure → `ValueError` (preserving the pre-FR-1 caller contract).
`content_generation` stays internal (no outbound I/O), handled locally rather than as
a connector.

**Behavior unchanged by default:** enforcement is vacuous until an operator registers
a `CapabilityPolicy` / secret scope / enables egress for a capability — registering a
connector changes dispatch routing only. Adopting policies per capability is an
operator/ops step, not app code.

**Original gaps (all now closed by 1.8.0):** (1) connector registration hook; (2)
capability-enforced outbound I/O; (3) shared authorized outbound path replacing raw
`perform_external_call` observe-only wrapping.

**Tests:** `tests/unit/test_automation_connectors.py` (registration, per-connector
branch/auth/payload, envelope→exception contract incl. capability denial).

---

## MONGO-DB-NAME-1: social layer split across two Mongo databases (RESOLVED)

**Status:** RESOLVED (2026-06-27). Code unified; no data migration required
(production runs `MONGO_DB_NAME=aindy_social_layer`, confirmed with the owner).

**Context:** The social layer selected its Mongo database two different ways. The
`social_router` endpoints (profile/post/feed/interact/comments) used the runtime
dependency `get_optional_mongo_db`, which yields `client[MONGO_DB_NAME]`
(`MONGO_DB_NAME` defaults to `aindy_default`). Four services instead hardcoded
`client["aindy_social_layer"]`: `social_performance_service`,
`social_metrics_history_service`, `automation_execution_service` (apps/automation),
and `task_service` (apps/tasks). `MONGO_DB_NAME` was never set in the repo and
undocumented in `.env.example`.

**Impact (when `MONGO_DB_NAME` is unset):** `posts` and `profiles` were written
and read under two different databases — analytics read an empty
`aindy_social_layer.posts` while user posts lived in `aindy_default.posts`;
masterplan-automation posts and task-completion profile velocity bumps landed in
`aindy_social_layer` but were invisible to the router serving `aindy_default`.
The system only worked if an operator separately knew to set
`MONGO_DB_NAME=aindy_social_layer`.

**Fix:** All four call sites now resolve `client[MONGO_DB_NAME]` (single source of
truth, matching the router). Safe in both directions: with the prod value
`aindy_social_layer` it is a no-op; if unset, services now agree with the router on
`aindy_default`. `MONGO_DB_NAME` is documented in `.env.example`.

**Residual / reopen trigger:** If any environment historically ran with
`MONGO_DB_NAME` unset *and* accumulated Mongo data, that data is split across
`aindy_default` and `aindy_social_layer` and needs a one-time merge of the `posts`
and `profiles` collections. Production was confirmed on `aindy_social_layer`, so no
merge is needed there; revisit only if a split-data environment surfaces.

---

## LINT-VERSION-GAP-1: eslint trails @aindy/ui-kit by one major version

**Status:** RESOLVED (2026-06-27, PR #4). `eslint` ^9.36 → ^10.4, `@eslint/js` → ^10.0.1,
`eslint-plugin-react-hooks` ^5.2 → ^7.1.1 (required for eslint 10 — 5.x peers cap at eslint 9),
`react-refresh` → 0.4.24. Frontend lint is now gated in CI (`npm run lint` in the Frontend Unit
Tests job) and `main` is branch-protected requiring it.

The upgrade surfaced a pre-existing, un-enforced lint debt (frontend lint had never been green or
CI-gated): 612 problems at the start. Errors were driven to zero — notably **94 rules-of-hooks**
violations fixed by extracting the bodies of 7 admin-gated platform pages into inner components so
hooks run unconditionally (behavior preserved; 121 unit tests + production build pass). Two new
react-hooks 7.x rules and the HMR-only `only-export-components` rule were set to `warn` rather than
adopted wholesale, per the original scoping below. Residual non-blocking warnings are tracked as
**LINT-WARNINGS-RESIDUAL-1**.

Original context retained below for history.

**Context:** `aindy-apps-monolith` is on `eslint@^9.36.0`. The `@aindy/ui-kit` library it consumes is on `eslint@^10.4.0`. Both use flat config; shared plugin overlap is `eslint-plugin-react-hooks` (this repo on `^5.2.0`, ui-kit on `^7.1.1` — independent version tracks).

**Posture:** Consumer trails library by one major version. The library's choice to lead is structurally correct; this entry is the consumer's side of the same finding.

**Cross-ref:** Same finding tracked in `aindy-runtime/TECH_DEBT.md` as LINT-VERSION-GAP-1 (runtime side, covering ui-kit).

**Upgrade scope when triggered:**
1. Bump `eslint` from `^9.36.0` to `^10.x` in `client/package.json`.
2. Verify `eslint-plugin-react-refresh@^0.4.22` is compatible with eslint 10 — this is the plugin most likely to require a coordinated bump.
3. Verify `eslint-plugin-react-hooks@^5.2.0` continues to work under eslint 10 (it should — react-hooks 5.x supports both eslint 9 and 10).
4. Verify the custom `no-restricted-syntax` rule enforcing `safeMap()` over `.map()` still parses under eslint 10's rule-config schema (flat config shape is stable across 9 → 10, low risk).
5. Run lint against the full `client/` source. Fix any new rule findings or silence with documented inline disables.

**Reopen trigger:** (a) any maintenance pass in this repo with budget for ~30 minutes of side-task work, OR (b) a desired ui-kit rule or react-hooks rule becomes eslint-10-only and back-pressures the upgrade.

**Estimated effort:** ~30 minutes assuming no plugin breakage. Add 30–60 minutes if `eslint-plugin-react-refresh` requires its own upgrade for compatibility.

**Out of scope for this entry:**
- Adopting `eslint-plugin-react-hooks@^7.x` is independent of the eslint version bump and should be evaluated separately. Hooks 7.x dropped support for eslint 8, so it's only available after this upgrade lands.
- Porting the `safeMap()` invariant to ui-kit was considered and rejected — ui-kit's `"strict": true` TypeScript config handles the bug class the rule guards in plain-JS apps-monolith code.

---

## LINT-WARNINGS-RESIDUAL-1: frontend lint passes with 68 deferred warnings

**Status:** Tracked, accepted. Address opportunistically; no single forcing event.

**Context:** The eslint 10 upgrade (LINT-VERSION-GAP-1) drove lint errors to zero, but three
rule categories were set to `warn` rather than fixed wholesale, leaving `npm run lint` green
(exit 0) with 68 warnings. These are intentionally non-blocking — the CI lint gate fails only
on errors.

**Breakdown:**
- `react-hooks/set-state-in-effect` (38) — new in react-hooks 7.x. Flags `setState` called
  synchronously inside an effect body (mostly mount-time data-loading effects: `useEffect(() =>
  { load() }, [load])`). Fixing each requires per-effect review; some are legitimate. Adopt
  incrementally.
- `react-hooks/exhaustive-deps` (17) — pre-existing missing-dependency warnings (existed under
  react-hooks 5.x; never enforced because frontend lint wasn't gated until now).
- `react-refresh/only-export-components` (11) — HMR-only DX rule. Context/primitive files
  (`AuthContext`, `SystemContext`, `SurfacePrimitives`, `button`, `AdminApiErrorBoundary`)
  co-locate a hook/helper with a component. "Fixing" means splitting files — churn for no
  runtime benefit.
- `react-hooks/immutability` (2) — new in react-hooks 7.x; flags mutating values defined
  outside a component (e.g. `window.location.href = …` in a redirect component).

**Reopen trigger:** (a) a render-performance issue traced to a `set-state-in-effect` cascade,
(b) a stale-closure bug traced to a missing dependency, or (c) a deliberate pass to ratchet any
of these rules back to `error` (would pair well with `--max-warnings 0` in the CI lint step).

**Estimated effort:** `exhaustive-deps` and `immutability` are small (~1–2h). `set-state-in-effect`
is the bulk (38 sites, each needs judgment); budget a half-day if driving to zero.

---

## UIKIT-ROUTE-DRIFT-1: client called 18 backend routes that 404 (missing router prefix) — RESOLVED

**Status:** RESOLVED (2026-07-18). 17 app-domain routes corrected app-side (`_routes.js`); the 1
runtime/platform route fixed upstream in `@aindy/ui-kit@1.0.6` and adopted here (dep bumped
`^1.0.0` → `^1.0.6`). 1.0.6 also broadened the platform fix (all `OPERATOR.*` → `/platform/*`) and
moved `AGENT.*` → `/apps/agent/*`; the app's existing `/tasks/*`, `/leadgen/`, etc. still resolve.
**Effective client→backend drift is now 0** (139 routes cross-checked vs the live `/openapi.json`;
frontend build + 136 tests green). Found by the live-frontend verification.

**Context:** The client reaches the backend via `@aindy/ui-kit`'s `ROUTES`. A cross-check of all
135 client route definitions against the live backend (566 routes from `/openapi.json`) found
**18** that resolve — through `buildApiUrl` (verbatim `API_BASE` prepend, no domain routing) — to a
path the backend never registers. All 18 **omit their router-prefix segment**. The other 117 resolve
correctly (routes with no intermediate prefix like `/tasks/list`, `/agent/run` work).

**Ownership split (runtime-side review):** 17 of 18 are **app-domain** routes (this monolith's
own endpoints, not runtime routes); 1 is **runtime/platform**:
- `ROUTES.ANALYTICS.CALCULATE_*` (14) — `/calculate_twr` → `/compute/calculate_twr`, etc. **App-owned.**
- `ROUTES.SEARCH.{ANALYZE_SEO,GENERATE_META,SUGGEST_IMPROVEMENTS}` (3) — `/analyze_seo/` → `/seo/analyze_seo/`, etc. **App-owned.**
- `ROUTES.OPERATOR.FLOW_STRATEGIES` (1) — `/flows/strategies` → `/platform/flows/strategies`. **Runtime-owned.**

**Confirmed live break (now fixed):** `AiSeoTool` (mounted at `/search/seo`) called all three SEO
wrappers → 404. The 14 compute routes back the KPI panels.

**Resolution (app-side):** per the runtime/app split applied at the frontend layer — the shared kit
owns runtime/platform routes, each app owns its own app routes — the 17 app-domain routes are
corrected in this repo's **app-owned route map**, `client/src/api/_routes.js` (re-exports ui-kit
`ROUTES`, overrides the app-domain paths; self-healing — only prepends a missing prefix, so a future
ui-kit that drops these app routes makes it a no-op; frozen-map contract preserved). This is the
**correct end-state**, not a stopgap — the app owning its own routes mirrors the backend split.
Guarded by `client/src/api/__tests__/routes-app-owned.test.js`.

**Remaining (upstream):** `/platform/flows/strategies` is a genuine runtime/platform route — fixed in
`@aindy/ui-kit` (every consumer benefits), then bump the dependency here. Spec + the optional ui-kit
hygiene ask (remove the app-domain paths from the shared `ROUTES`) in `docs/handoffs/UIKIT_ROUTE_FIXES.md`.

**Reopen trigger:** ui-kit ships the `/platform/flows` fix (bump the dep), or a new app-domain route
family lands behind a backend router prefix (extend the `_routes.js` override).

---

## CLIENT-DEAD-SIDEBAR-1: orphaned `Sidebar.jsx` with stale nav links — RESOLVED

**Status:** RESOLVED (2026-07-18). Deleted. Found by the live-frontend verification.

**Context:** `client/src/components/shared/Sidebar.jsx` was **not imported anywhere** — the app
renders `AppShell.jsx`'s own `<nav>` (28 links, all map to mounted routes). The orphaned component
carried 5 links matching no mounted route and never rendered.

**Resolution:** deleted `Sidebar.jsx` (its only local helper, `SubNavItem`, was unused elsewhere).
Two test files referenced it: the two `Sidebar` describe blocks in `components.test.jsx` were removed,
and `search-nav.test.jsx` (which guarded the previously-orphaned `/search/*` nav links against the
*dead* Sidebar) was **retargeted to the live `AppShell` nav** — a stronger guard testing the surface
users actually see. Frontend build + 136 tests green.

**Reopen trigger:** a decision to revive a sidebar nav (rebuild against current routes, not the stale copy).

---

## SEARCH-RANKING-EMBEDDINGS-1: hybrid semantic (embedding) ranking — RESOLVED

**Status:** RESOLVED (2026-06-28). The hybrid embedding seam scoped here is now implemented:
semantic relevance via the runtime embedding stack, opt-in, with automatic lexical fallback. The
v3 Ranking Unification (PR #16) had intentionally shipped lexical-only with this pluggable seam;
this pass wired the seam.

**Context (original):** Phase v3 of the Search System (`docs/apps/SEARCH_SYSTEM.md`) added a shared
ranking layer: `lexical_relevance()` + `composite_score()` in
`apps/search/services/search_scoring.py`, applied by `rank_items()` in
`apps/search/schemas/search_schema.py` so every surface (leadgen, research, SEO) ranks
`SearchResponse.results` on one composite axis (0.6 relevance / 0.4 surface quality). Lexical
relevance (token-overlap + saturating term-frequency) captures lexical overlap but not **semantic**
similarity (synonyms, paraphrase, query intent).

**Resolution — what shipped (all four scoped items):**
1. `embedding_relevance()` and the caching `EmbeddingRelevanceProvider` in `search_scoring.py`
   compute cosine similarity over the runtime embedding stack the app already reaches
   (`AINDY.memory.embedding_service.generate_query_embedding` / `cosine_similarity`) — the same
   backend behind `search_service.search_memory`. No new external dependency on the app side.
2. `rank_items()` gained a `relevance_fn` parameter and defaults to `default_relevance_provider()`:
   lexical unless the `AINDY_SEARCH_EMBEDDING_RANKING` flag opts into embeddings. The embedding
   provider degrades to lexical on its own when the backend is unavailable, so the default is
   always safe and the surface adapters required no changes.
3. Determinism preserved: the seam is off by default, and even when enabled the runtime embedding
   service returns a zero vector under `settings.is_testing` (no OpenAI client) — detected by
   `_is_zero_vector()` and routed to lexical. SQLite/app-profile/CI runs therefore stay lexical and
   deterministic. The embedding path is covered separately with the service mocked
   (`tests/unit/test_search_ranking.py`).
4. Within a ranking pass, `EmbeddingRelevanceProvider` embeds the query once and caches each
   document embedding, so `rank_items` does not recompute per item.

**Follow-up (not blocking):** cross-request / persistent embedding caching (current cache is
per-pass only), and cosine-score calibration for ada-002's compressed similarity range if semantic
ordering proves too flat in production. Reopen if either is needed.

**Tests:** `tests/unit/test_search_ranking.py` — fallback-on-zero-vector, active cosine path,
per-pass caching, flag-gated provider selection, and embedding-driven reordering through
`rank_items`.

**Cross-ref:** Completes the v3 design seam noted in `SEARCH_SYSTEM.md` Phase v3; supersedes the
"richer provider-backed ranking" clause of APP-DEBT-MIGRATED-1's search row.

---

## DOCS-MIGRATION-1: app-owned docs recovered from pre-split archive

**Status:** RESOLVED (2026-06-27). 18 docs moved + path-fixup sweep complete. Residuals noted below.

**Context:** When `aindy-runtime` and `aindy-apps-monolith` were split out of the original combined
repo (`masterplan-infiniteweave-monday-node-2025-0411`), 18 app-owned docs were left behind in the
archive. They were copied into this repo on 2026-06-27, preserving subtree paths, per the ownership
map in `aindy-runtime/docs/runtime/RUNTIME_DOCSET_BOUNDARY.md`:

- `docs/apps/`: `RIPPLETRACE.md`, `AUTONOMOUS_REASONING_MODULE.md`, `SEARCH_SYSTEM.md`,
  `SOCIAL_LAYER.md`, `FREELANCING_SYSTEM.md`, `INFINITY_ALGORITHM{,_CANONICAL,_FORMALIZATION,_SUPPORT_SYSTEM}.md`,
  `ABSTRACTED_ALGORITHM_SPEC.md`, `FORMULA_AND_ALGORITHM_OVERVIEW.md`
- `docs/architecture/`: `PUBLIC_SURFACE_AUDIT.md`, `PUBLIC_SURFACE_CONTRACTS.md`,
  `PUBLIC_SURFACE_MIGRATION_GUIDE.md`, `USER_ID_AUDIT.md`
- `docs/api/API_REFERENCE.md`, `docs/apps/IMPLEMENTATION_DOCS_AUDIT.md`,
  `docs/apps/MASTERPLAN_SAAS.md`

**Fixup performed (2026-06-27):** The pre-split docs referenced a flat monolith layout
(`services/foo.py`, `routes/foo.py`, `db/models/foo.py`, `AINDY/services/foo.py`). Every code-path
token was Glob-verified against the current tree and rewritten:
- app modules → `apps/<domain>/...` (e.g. `services/infinity_service.py` →
  `apps/analytics/services/scoring/infinity_service.py`; the flat `apps/analytics/services/*.py`
  files are compat shims — docs point at the canonical `scoring/`/`orchestration/`/`calculations/`
  implementations).
- runtime modules → confirmed in sibling `aindy-runtime` and written as their real `AINDY/...`
  paths (e.g. `services/agent_runtime.py` → `AINDY/agents/agent_runtime.py`).
- The architecture docs (`PUBLIC_SURFACE_*`, `USER_ID_AUDIT`) and `API_REFERENCE`,
  `IMPLEMENTATION_DOCS_AUDIT`, `MASTERPLAN_SAAS`, `ABSTRACTED_ALGORITHM_SPEC` were already clean
  (no stale flat paths) — left untouched.

**Also fixed in the same pass — AGENTICS.md:** `docs/apps/AGENTICS.md` was already present before the
migration (one of the original 3 app docs, not part of the 18 moved) but carried the same stale flat
paths. It got the identical Glob-verified rewrite — mostly runtime-owned (`AINDY/agents/...`,
`AINDY/routes/...`), with `db/models/agent_run.py`/`agent_event.py` → `apps/agent/models/...`.

**Residuals (intentionally left, annotated inline in the docs):**
- `db/models/agent_run_event.py` (ARM) resolves to no file in either repo (renamed/merged or
  never standalone) — carries `_(path unverified after split)_`. **Update (2026-07-05):**
  `services/deepseek_arm_service.py` (FORMULA) is RESOLVED — the ARM analysis logic moved to the
  app layer at `apps/arm/services/deepseek/deepseek_code_analyzer.py` (verified against the runtime
  checkout, which no longer has it); `FORMULA_AND_ALGORITHM_OVERVIEW.md` was repointed accordingly.
- "Files to create" / roadmap tokens (e.g. `services/freelance/intake_service.py`,
  `services/reasoning/*`, `db/models/client_account.py`, `services/infinity_state_service.py`) carry
  `_(planned; not yet present)_` or sit under explicit "Potential files to create" headings — they
  describe future work, not moved code.
- Note: `services/flow_engine.py` (the most common stale token, ~13 refs) WAS resolved — the flow
  engine is a package, not a `flow_engine.py` basename; all refs now point at
  `AINDY/runtime/flow_engine/runner.py` (home of `PersistentFlowRunner`).

**Reopen trigger:** Any doc relying on an unverified residual token above, or live-code verification
of the `deepseek_arm_service` / `agent_run_event` references.

---

## DOCS-MIGRATION-2: shared pre-split docs — triaged and app slice extracted

**Status:** App-facing slice DONE (2026-06-27). Runtime-owned + deferred buckets recorded below.

**Context:** Beyond the 18 clearly app-owned docs (DOCS-MIGRATION-1), the archive held 17 docs that
the boundary review treated as "shared." A per-doc content analysis showed most are **runtime-owned**,
not app-owned — the apps-monolith slice was small. Disposition:

- **Bucket A — runtime-owned (NOT this repo; belong in `aindy-runtime`):** `architecture/DATA_MODEL_MAP.md`,
  `architecture/MODEL_OWNERSHIP_POLICY.md`, `platform/governance/AGENT_WORKING_RULES.md`,
  `platform/governance/ERROR_HANDLING_POLICY.md`, `platform/governance/CHANGELOG.md`, and all 4
  `tutorials/*` (they teach runtime primitives — memory bridge, flow WAIT/RESUME, scheduler, Nodus —
  no app-domain workflow). Tracked as a future `aindy-runtime` task; out of scope here.
- **Bucket B — stale/archive-only:** `platform/governance/NEXT_PHASE_PLAN.md` (completed pre-split
  sprint narrative). Not migrated.
- **Bucket C — app-facing slice extracted into this repo (DONE):**
  1. `docs/platform/engineering/TECH_DEBT.md` → the app-domain debt items it carried (a real
     tracking gap) migrated below as **APP-DEBT-MIGRATED-1**.
  2. `docs/architecture/ANALYTICS_BOUNDARY.md` → added as the app-owned half of the analytics boundary.
  3. `docs/api/CHANGELOG.md` → app-route (`/apps/*`, `/masterplans/*`, `/bridge/*`) history extracted
     into this repo's `CHANGELOG.md`; runtime routes (`/platform/*`, `/agent/*`,
     `/observability/*`) left to the runtime changelog.
- **Bucket D — living governance (triaged 2026-06-27; author fresh, not copy-split):**
  - `platform/GOVERNANCE_INDEX.md` → **AUTHORED** fresh as `docs/GOVERNANCE_INDEX.md` (indexes
    only docs this repo owns; runtime contracts referenced as upstream authority).
  - `architecture/SYSTEM_SPEC.md` → **SKIP (redundant)** — app-facing content already covered by
    `ARCHITECTURE_MAP` + `BOOT_PROFILES` + `PLUGIN_REGISTRY_PATTERN` + `APPS_MONOLITH_REPO_SHAPE`;
    runtime content belongs to `aindy-runtime`.
  - `platform/governance/release_notes.md` → **ARCHIVE-ONLY** — completed pre-split sprint history;
    app release tracking starts fresh from the split (git history + `CHANGELOG.md`).
  - `platform/governance/EVOLUTION_PLAN.md` → **BROUGHT OVER** as `docs/apps/EVOLUTION_PLAN.md`.
    It's an existing, current roadmap (not synthesized): Phases 1–4 are completed runtime hardening
    (kept as historical context, owned upstream by `aindy-runtime`), Phase 5 is the current
    cross-repo phase, and Phases 6–7 + the named phases are app-facing. Brought over with
    cross-repo reference hygiene (runtime-owned governance links flagged; moved app-doc paths fixed)
    and an ownership preamble.

- **`platform/governance/INVARIANTS.md` (late finding — was pre-classified runtime-only, actually
  mixed ~50/50):** the app-domain invariants were extracted to
  `docs/platform/governance/INVARIANTS.md` — masterplan/genesis (single-active, locking,
  synthesis-ready gate, audit-draft gate, atomic creation, non-null columns), analytics canonical-
  metrics uniqueness, rippletrace DropPoint-before-Ping, freelance non-null columns, and the
  JWT/API-key/rate-limit invariants whose protected surfaces are app routers (enforcement mechanism
  stays runtime-owned). Original section numbers preserved for traceability. The runtime invariants
  (PostgreSQL/UTC/session-isolation/memory-graph/embedding/schema-drift) remain runtime-owned —
  **author the runtime half in `aindy-runtime`** (fold into the Bucket A handoff).

**Status:** RESOLVED (2026-07-18). The two open `aindy-runtime` items — the **Bucket A**
relocation and the **runtime half of `INVARIANTS.md`** — shipped upstream with
aindy-runtime 1.8.0 (DOCS-BUCKET-A-1 / FR-4). App-side reciprocal cross-links updated:
`docs/GOVERNANCE_INDEX.md` Level 0 lists the relocated runtime governance docs,
`docs/platform/governance/INVARIANTS.md` points at the now-authored runtime half (via
`RUNTIME_DOCSET_BOUNDARY.md`), and `docs/apps/EVOLUTION_PLAN.md`'s cross-repo preamble
notes the relocation. Nothing further app-side.

**Reopen trigger:** A re-triage of `EVOLUTION_PLAN` phases as they complete, or a new
shared-doc split.

---

## APP-DEBT-MIGRATED-1: domain debt recovered from the pre-split register (2026-06-27)

**Status:** Tracked. Migrated from the pre-split `docs/platform/engineering/TECH_DEBT.md`
(triaged 2026-04-25) under DOCS-MIGRATION-2 Bucket C. These app-domain items were never carried into
this repo's register — a genuine tracking gap. Runtime/infrastructure items from the same source stay
with `aindy-runtime`. Verify each against current code before acting; the source triage is ~2 months old.

### APP-DEBT-MIGRATED-1a: Genesis session locking enforced only in application logic (production-blocking)

**Status:** RESOLVED — already fixed in this repo before migration; verified 2026-06-27.
**Severity:** High  **Effort:** M  **Files:** `apps/masterplan/services/masterplan_factory.py`,
`apps/masterplan/masterplan.py`

**Original concern (from the pre-split triage, 2026-04-25):**
`create_masterplan_from_genesis()` prevents double-locking by reading `GenesisSessionDB.status` in
application code, but the schema enforces no DB-level uniqueness/lock invariant for the
lock/plan-creation transition. Concurrent lock requests can create duplicate or inconsistent
masterplan state from one genesis session — a correctness bug in a primary planning workflow.

**Resolution:** The fix landed in this repo on 2026-04-26 (the day after the source triage) and was
carried in unverified during the DOCS-MIGRATION-2 migration. Both transaction-boundary layers the
item asked for are present:
- DB backstop: partial unique index `uq_masterplan_genesis_session_id` on
  `master_plans.linked_genesis_session_id` — declared in `apps/masterplan/masterplan.py` and created
  by migration `2d4f6a8b0c1d_add_masterplan_genesis_session_uniqueness.py` (wired into the head chain;
  PostgreSQL partial-index branch, plain unique index on other dialects).
- Row-locking: `create_masterplan_from_genesis()` reads the session under `with_for_update()` and
  catches `IntegrityError` on commit, surfacing a clean `ValueError`.

Concurrent lock requests can no longer create duplicate masterplan state: the row lock serializes the
common path and the unique index is the hard backstop if two transactions both pass the status check.
Regression coverage added 2026-06-27 in `tests/unit/test_masterplan_genesis_locking.py` (asserts the
application guard, the DB unique-index rejection, and that distinct sessions remain unconstrained).

### Deferred app-domain items

| Item | Domain | Effort | When to revisit |
|------|--------|--------|-----------------|
| Search orchestration unified (Steps 1–6 + v3 ranking + semantic seam, 2026-06-28) — shared `search_service`, unified `SearchResponse` contract, agent tool + `unified_search` workflow, shared lexical ranking, and the hybrid embedding-ranking seam (**SEARCH-RANKING-EMBEDDINGS-1**, RESOLVED) all shipped. No remaining search-ranking debt. SEO *improvement* suggestions (§3.1) DONE (2026-07-17): `seo_services.seo_improvement_suggestions` derives deterministic, severity-tagged suggestions (thin content, readability, keyword stuffing / weak focus) surfaced in `seo_analysis`. Phase v4 outcome→query-weighting (§8) — DONE (2026-07-17). Capture (#98): `SearchResultFeedback` + `feedback_service` capture both implicit (click/dwell/convert/dismiss) and explicit (thumbs_up/thumbs_down) signals, deduped per (user, query, result_ref, signal) with explicit latest-vote-wins, aggregated into a blended per-query outcome weight (`get_result_outcome_weights`); exposed via `POST /apps/search/feedback` + `GET /apps/search/feedback/weights` and syscall `sys.v1.search.record_feedback`. Consumption (#99): behind `AINDY_SEARCH_OUTCOME_WEIGHTING` (default off), `sys.v1.search.query` looks up the weights and passes them to `rank_items`, which nudges each result's composite by a small, bounded amount (`outcome_nudge`, tanh-saturated at ±0.15) — relevance+quality stays dominant; applied weight/nudge recorded on item metadata; default off = ranking byte-for-byte unchanged. **Residual:** none functional — soak on live feedback, then flip the flag default (same soak-then-flip posture as the embedding-ranking and learned-recursion seams) | search | — | soak, then flip `AINDY_SEARCH_OUTCOME_WEIGHTING` default |
| Freelance commercial workflow incomplete — payments/refunds/webhooks/idempotency/subscriptions and now lead→client→order lineage (Phase 1, 2026-06-28: `ClientAccount` + intake_service) exist; agent-driven execution (Phase 2 — DONE 2026-07-17: `apps/freelance/agents/tools.py` registers `freelance.optimize_pricing` (gated/revertible pricing, dry-run default) + `freelance.performance` (read)), client workflow automation (Phase 3 — DONE 2026-07-17: two multi-step, state-threaded flows in `apps/freelance/flows/freelance_flows.py` via `register_flow` — `freelance_client_onboarding` (lead→client+order→delivery dispatch, `POST /apps/freelance/clients/onboard`) and `freelance_order_fulfillment` (deliver→refresh metrics, `POST /apps/freelance/orders/{id}/fulfill`); freelance-specific Nodus `.nd` workflows remain gated on the runtime execute-to-completion work — see the "Nodus-native reasoning execution deferred (runtime)" row), and the autonomous optimization loop (Phase 5) is now partially shipped (2026-07-17) — the Revenue Intelligence Loop (feedback + realized revenue → gated, revertible pricing recommendations, #82) and the consumption wires (order price defaults from the `ServicePrice` catalog; intake converts Search-actioned leads, #83) landed; order-lifecycle tools (create/deliver) are deliberately **not** agent-exposed (payment / real-world side effects) pending a risk posture; all app-doable freelance phases (1/2/3, and the shipped slice of 5) are now complete — the only remaining freelance work is runtime-gated (native `.nd` execution) or product-risk-gated (agent-exposing order-lifecycle side effects) | freelance | — | before exposing freelance as a primary autonomous revenue path |
| RippleTrace productization incomplete — execution-causality, graph edges, UI, and now end-to-end causal-graph validation (backend + frontend, Steps 1–2, 2026-06-28) exist; deeper insight generation and broader scenario coverage do not | rippletrace | M | before using RippleTrace as a primary incident/audit surface |
| Masterplan dependency cascade + execution automation — anchor/ETA debt closed; ETA is now plan-scoped + cascade/critical-path aware (MASTERPLAN_SAAS Step 1, 2026-06-30, `apps/masterplan/services/eta_service.py`). task completion now returns the refreshed projection (Step 3, `_recalculate_active_masterplan_eta` → `task_orchestration.masterplan_projection`). the plan's ETA panel now surfaces the cascade metrics directly — basis chip, critical-chain depth, ready/blocked — and adopts the completion-response projection reactively via a `MasterplanProjectionProvider` context so completing a task refreshes the plan panel without a refetch (MASTERPLAN_SAAS Step 2, 2026-06-30, `client/src/components/app/MasterPlanDashboard.jsx`, `client/src/context/MasterplanProjectionContext.jsx`). ETA is now continuous-time: per-task `estimated_hours` drives a remaining-effort + effort-weighted-critical-path projection (`projection_basis="duration"`), reducing to count-based cascade when estimates are absent (2026-06-30, `apps/tasks/services/task_service.py`, `apps/masterplan/services/eta_service.py`). external automation connectors now reach external surfaces — CRM (stub → provider-agnostic outbound POST) and social (additive external delivery on top of the internal feed) join email/webhook/stripe, now registered via `register_connector` and dispatched through the runtime's capability-enforced connector boundary (FR-1 adopted 2026-07-18 on aindy-runtime 1.8.0 — see MASTERPLAN-CONNECTOR-RUNTIME-1, RESOLVED) (`apps/automation/services/automation_execution_service.py`, `tests/unit/test_automation_connectors.py`). No remaining app or runtime connector debt | masterplan | L | closed |
| ARM self-tuning — RESOLVED (2026-07-17, #80). `auto_apply_safe` is now consumed by a guarded auto-apply loop (`apps/arm/services/arm_autotune_service.py`): a pure gate (numeric-knob whitelist / absolute bounds / min-sessions / cooldown) applies the safe subset with an auditable, revertible trail (`ArmAutoTuneLog`), plus syscall `sys.v1.arm.autotune` + `/arm/config/auto-tune` endpoints (dry-run default). ARM's Reflect→Adjust loop is closed | arm | — | closed |
| Infinity loop autonomy still shallow — reasoning extracted into a reusable engine + dedicated `reason()` service (strategy_selector/feedback_analyzer) the loop consumes, plus `reasoning.*` observability events, agent integration (planner consumes the `analytics.reasoning_recommendation` job; completion hook → reasoning-backed orchestrator), reasoning `execution_intent` + a registered `reasoning` flow strategy / `reasoning_apply` flow, and the `reasoning.evaluate` agent tool (`apps/analytics/services/reasoning/`, `apps/analytics/agents/`, ARM/Reasoning Phases 1–5 + tool follow-up, 2026-06-28/29). All app-ownable reasoning phases are complete. Learned threshold/weight calibration is now underway (2026-07-17): the REFLECT expected-score calibrator ships in **shadow** (Phase 0, #85) + **advisory** (Phase 1, #86), default-off (`AINDY_INFINITY_LEARNED_SHADOW` / `_ADVISORY`), scoped in `docs/architecture/INFINITY_LEARNED_RECURSION_SCOPE.md` — Phase 2 (learned model *drives* canonical scoring) + the 3b-full weighting call remain. The bounded autonomous controller is the runtime **FR-3** Next-Action acting — shipped in aindy-runtime 1.8.0 (`next_action.dispatched` outcome contract, gated on `AINDY_NEXT_ACTION_ACTING`, default off). App-side adoption DONE (2026-07-18): the dispatch outcome is read back via `apps/agent/agents/next_action_outcomes.py` + `GET /apps/agent/next-action/outcomes` (disposition + CHOSEN→DISPATCHED chain + per-disposition summary — the soak observability). Remaining is ops-only: soak, then flip `AINDY_NEXT_ACTION_ACTING` on | analytics | M | Phase 2 needs the 3b-full decision + a soak; FR-3 flip is ops |
| Nodus-native reasoning execution — RESOLVED (2026-07-18). `register_nodus_workflow` adopted in 1.7.0 (the `.nd` registers at boot); FR-5 (native workflows reach app callables) shipped in aindy-runtime 1.9.0, and the app now **routes reasoning-apply through the Nodus VM**, flag-gated. `reasoning_apply_v1.nd` calls `sys("sys.v1.analytics.get_reasoning_recommendation", …)` (the `get_` verb makes `_infer_dispatch_capability` grant `analytics.read`, matching the syscall's required capability — the capability-inference gotcha that first denied a `reasoning_recommendation`-named syscall). `apps/analytics/services/reasoning/nodus_apply.py::run_reasoning_apply` executes it via `run_nodus_workflow` behind `AINDY_REASONING_NODUS_NATIVE` (default off) and normalizes `data.nodus_output_state.reasoning_apply_result` to the existing `{data: recommendation}` envelope; `reasoning_apply_node` delegates to it; any Nodus failure falls back to the Python path. Behavior-neutral substrate swap — verified end-to-end on the app-profile VM (`tests/unit/test_reasoning_nodus_apply.py`). Remaining is ops-only: soak, then flip `AINDY_REASONING_NODUS_NATIVE` | analytics | — | soak, then flip the flag |
| Infinity support-system depth — explicit `UserFeedback` nudges per-user KPI **weights** (Step 5), support inputs are centralized into one `SupportState` snapshot (Step 1), and the support → decision seam has behavioral coverage (Step 6) (2026-06-29). Remaining: weight feedback into the KPI **score formulas** (deliberately deferred — risks conflating measurement with sentiment; weights are the principled lever); the full DB-backed loop E2E (integration-tier); fold `identity_boot_service` state into the snapshot; and consume observability + agent/async execution aggregates (Steps 3/4) — runtime-gated, need a runtime aggregate syscall/job. ARM's analysis-quality signal is now consumed from the ARM domain (DONE 2026-07-17): `arm_metrics_service.analysis_quality_signals` (exposed via `apps.arm.public.get_analysis_quality_signals`) computes usage + architecture/integrity quality avg + trend, and Infinity's `ai_productivity_boost` / `decision_efficiency` KPIs consume it — analytics no longer re-parses ARM's `result_full` schema (same scoring math, single source of truth) | analytics | M | when deepening Infinity optimization |
| Agentics completion is runtime-owned — the doc that defined the `aindy-runtime` split. App-side decision levers (autonomy trigger policy, agent ranking strategy, completion hook) are now tested (AGENTICS hardening, 2026-06-29). Phases B (Nodus VM/`.nd`) and E (durable workers), and most of D (delegation/registry/conflict), are runtime work in `aindy-runtime`, not app edits; the registerable D lever (ranking) is done | runtime/agent | L | when `aindy-runtime` advances Agentics execution |
| Identity inference — RESOLVED (2026-07-18). Rules-only single-observation flips are replaced by a probabilistic evidence model: `observe()` records each event as a weighted, provenance-tagged vote (`IdentitySignal`, app-owned; the runtime `UserIdentity` model is untouched), and dimensions are re-derived by `identity_inference_service` — a transparent, recency-decayed multinomial over evidence. A value is committed only when the leading share clears a confidence floor (0.6) with enough support (2.0) and beats an already-set value by a margin (0.15 hysteresis), so one off-pattern event can't churn the profile and sustained counter-evidence still moves it. Inspectable via `GET /apps/identity/inference` (per-dimension confidence/support/distribution). `arm_analysis` score now yields both quality *and* speed evidence (counter-evidence, both directions), not a one-way flip | identity | — | closed |
| SYLVA reserved agent — REMOVED (2026-07-17). The inactive `agent-sylva-001` seed row (reserved namespace, never activated, no ORM model / code / test refs) is deleted by migration `f5a6b7c8d9e0`; the lone docstring example dropped | agent | — | closed |

**Reopen trigger:** Per-item "when to revisit" above, or substantial work in the named domain.
