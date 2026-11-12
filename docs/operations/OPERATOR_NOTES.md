---
title: "Operator notes — what running this stack has taught"
last_verified: "2026-11-11"
api_version: "1.0"
status: current
owner: "app-team"
---

# Operator notes: what running this stack has taught

The repo's working experience: problems met while running, testing and releasing A.I.N.D.Y., how they showed, and
what resolved them. The code does not show these. `CLAUDE.md` holds the rules every change must follow; this holds the
experience behind them. `SESSION_HANDOFF.md` (gitignored) holds only *where we are*.

**Before troubleshooting an unfamiliar failure, look here.** Each entry starts with when it applies, so you need not
read them all:

```bash
grep -n -A1 "^### OPS-" docs/operations/OPERATOR_NOTES.md
```

## How entries work

```
### OPS-NNN: what goes wrong, in a phrase
**Applies when:** the task or symptom that should bring you here. **Seen:** date(s). **Retire when:** what would end it.
What it looks like, why, and the fix that worked.
```

- **One problem, one entry.** Before adding, search for it; if it is there, add the new date to **Seen** and sharpen
  the text instead of writing a second entry. IDs are never reused.
- **Record a problem when it cost time to learn and could happen again.** A one-off typo is not experience.
- **Experience is not policy.** An entry becomes a `CLAUDE.md` rule only once it has been seen twice or reproduced on
  purpose, and the rule then stays one line that points back here (`OPS-NNN`) for the story. Rules carry *what to
  do*; the incident that taught it lives here.
- **A symptom-led diagnosis with several steps becomes a skill** (`.claude/skills/`), as `api-hang-triage` did,
  because a skill loads when its symptom comes up and this file loads only when someone remembers it.
- **When an entry stops being true, move it to *Obsolete* with one line saying why.** It is kept so the old lesson is
  not re-learned from git history. Most retire when a `TECH_DEBT.md` item closes or a runtime adoption changes the
  behaviour; check the **Retire when** of the entries a change touches.

Facts with no failure behind them (ids, timings, recipes) sit in each section's **Reference** list.

---

## The local stack (Docker on this Windows host)

### OPS-001: `/health` 500s and the api sits `unhealthy` without `--profile full`
**Applies when:** bringing the stack up, or `/health` fails while `/api/version` answers. **Seen:** 2026-09-16
(26 minutes, first read as a runtime regression). **Retire when:** `COMPOSE-REDIS-URL-UNCONDITIONAL-1` closes.
`docker-compose.prod.yml` sets `REDIS_URL` unconditionally while `redis` is in profile `full`, and the runtime's rate
limiter uses Redis with no fallback. Every rate-limited route raises, `/health` included; `/api/version` has no limit,
so it looks fine. The scheduler-saturation line shows up too, as a victim. **Fix:** always up and down with
`--profile full --profile mail --profile public-mcp`.

### OPS-002: a filtered `docker rm` deleted the live api
**Applies when:** removing containers. **Seen:** 2026-10-22.
`docker ps -q --filter … --format …` ignores `--format` under `-q`, so the filter matched more than it showed.
**Fix:** never bulk-remove by filter; use `--rm` and exact IDs.

### OPS-003: after a reboot the api fails once or twice, and a new image is not live
**Applies when:** the laptop has rebooted, or `RestartCount` is above 0. **Seen:** 2026-11-11.
Docker Desktop starts at sign-in and `restart: unless-stopped` brings every container back at once, ignoring
`depends_on`, so the api fails ("the database system is starting up") while postgres runs crash recovery, then boots.
`RestartCount` 2 is normal there. **A restarted container keeps the image it was created from**: an image built since
goes live only when an `up` recreates the container. The watcher and Vite return through their sign-in tasks
(`scripts/CLAUDE.md`).

### OPS-004: a rebuild takes 10+ minutes
**Applies when:** an api build is slow. **Seen:** 2026-09-20, 2026-10-09, 2026-10-22.
A source-only change rebuilds in about a minute: the dependency layer is keyed on `pyproject.toml` and
`constraints.txt` only (#395). If a source change takes 10+ minutes the layer order regressed
(`DOCKER-PIP-LAYER-INVALIDATION-1`). A pin move re-downloads the tree (399 s on 10-09). 2.28.1 took 53 minutes because
`python:3.11-slim`'s digest had moved and the Debian mirror was slow: a moved base image, not the pin.

### OPS-005: a variable set in `.env` never reaches the process
**Applies when:** a setting in `.env` seems to have no effect. **Seen:** 2026-09-26 and since.
Compose passes only the variables it lists in the service's `environment`. **Fix:** add it to the compose file.

### OPS-006: the first requests after an api boot come back empty
**Applies when:** probing right after a restart. **Seen:** recorded 2026-10-25.
Wait a few seconds and ask again before suspecting the route.

### OPS-007: a scheduled job's output never reaches the api log
**Applies when:** checking whether a scheduled job ran. **Seen:** recorded 2026-10-25.
The callback runs in a subprocess whose stdout and stderr the runtime captures (`runtime_callback_host.py`); only a
callback that *fails* shows, as the error the api process raises. **Fix:** check the job is registered
(`GET /platform/observability/system`, `scheduled_job_count`), run the function once by hand with `PYTHONPATH=/app`,
or have it leave a row.

### OPS-008: the Vite dev server serves a stale `vite.config.ts` after a branch switch
**Applies when:** a proxied prefix answers 404 through `localhost:5173` but not from the api. **Seen:** 2026-11-09.
A checkout reverted the file for a moment, Vite reloaded that version and missed the pull that restored it.
**Fix:** `touch client/vite.config.ts`. Check a proxied prefix through `localhost:5173` after switching branches.

### OPS-009: a route test's second request sees none of the first one's writes
**Applies when:** writing a route test with more than one request. **Seen:** 2026-11-08 (runtime 2.34.0 handoff §4).
Under the shared test transaction a request's commit is not a real commit. **Fix:** test a lifecycle at the service
level, and each route with one request.

### OPS-010: an api wedge blamed on the scheduler was postgres being killed
**Applies when:** the api hangs or logins time out. **Seen:** 2026-08-20 (155 postgres reinitialisations).
`skipped a run (max_instances)` names the victim, never the culprit. **Fix:** load the `api-hang-triage` skill.

**Reference**
- `up -d api` after a build recreates only the api, about 60–80 s to healthy.
- The api log carries WARNING and above only. The ledger (`system_events`) is the request log: pair
  `execution.started` and `execution.completed` by `trace_id` for durations.
- To time a route without the api's own load: a throwaway container from the api image with
  `AINDY_ENABLE_BACKGROUND_TASKS=false`, and yappi across all threads.
- Cron hours: 00, 06, 07, 12, 18 UTC.
- The api is localhost-only, so no link in an email reaches it away from the desk.
- A minted token lasts about a day.
- To manufacture an authority denial: mint the token in a `docker exec` under
  `mint_token(capability_ceiling=[…])` without `external_api_call`, then `execute_run`.

## Testing on this host

### OPS-011: Python tests fail to import `pydantic_core` in the venv
**Applies when:** running Python tests or `scripts/inventory.py` locally. **Seen:** 2026-10-22 and since.
**Retire when:** Windows Application Control stops blocking the venv's DLLs.
**Fix:** run them in a `--rm` container from the api image, on a slim `tar` copy of the repo (no venv,
`node_modules`, `.git` or `__pycache__`), after `pip install pytest…` (and `pyyaml` for
`test_compose_memory_bounds.py`). `xdist` is not installed there; run the unit suite serially.

### OPS-012: a client test fails under load
**Applies when:** a vitest test fails in CI or alongside other work but passes alone. **Seen:** recorded 2026-10-25.
Usually its timeout, not its logic (vitest's default is 20 s since #464). Check the duration first, and reproduce
with the Python suite running alongside.

### OPS-013: `npm ci` deleted `node_modules`
**Applies when:** reinstalling client dependencies. **Seen:** recorded 2026-10-25.
On Windows it fails while Vite is running and leaves `node_modules` gone. **Fix:** stop Vite first.

### OPS-014: an em dash prints as `â€”` and looks like a data bug
**Applies when:** text read through `python -` or piped into Python looks corrupted. **Seen:** 2026-10-25, 2026-11-11.
Python reads stdin as cp1252 on this host, so `curl … | python -c "json.load(sys.stdin)"` mangles the api's UTF-8.
**Fix:** write scripts to a file, and check the stored value in postgres before believing it.

### OPS-015: code or search strings written through the shell come out mangled
**Applies when:** writing code inside a heredoc, or matching text copied from a shell example. **Seen:** 2026-10-25
(twice).
A `\n` inside Python inside a Bash heredoc became a real newline, and one heredoc would not parse. A backslash ending a
line in a Python string is a line continuation, so a search string ending in `\` never matches. **Fix:** use the Write
and Edit tools for such text.

### OPS-016: a curl JSON body with an em dash returns `400`
**Applies when:** posting JSON through Git Bash. **Seen:** recorded 2026-10-25.
**Fix:** use ASCII, or `--data-binary @file`.

### OPS-017: a background task vanished
**Applies when:** a long background command in Claude Code disappears. **Seen:** recorded 2026-10-25.
Claude Code reaps background tasks when host memory is low. A detached Vite survives it.

### OPS-018: installed package metadata looks wrong
**Applies when:** the version Python reports disagrees with what was installed. **Seen:** 2026-10-02 (#442).
A stale repo-root `aindy_apps_monolith.egg-info` shadows the installed metadata. **Fix:** delete it. For the runtime,
trust `import AINDY._version` and `AINDY.__path__`, never `pip show` (the venv imported 2.6.0 under a 2.11 pin on
2026-09-12).

### OPS-019: tests that encode "unset means off" break on a runtime adoption
**Applies when:** adopting a runtime release that flips a default. **Seen:** 2026-10-09 (2.26.0, three tests).
**Fix:** read the release's default changes first, and pin the setting in tests that depend on it.

### OPS-020: CI fails on a new RippleTrace route
**Applies when:** adding a RippleTrace route. **Seen:** 2026-10 (#501's first CI run).
Every RippleTrace handler is wrapped in `materialized(...)`, and `test_handler_returns_data_not_rows` checks it. Run it
before pushing.

### OPS-021: CI fails on the inventory check
**Applies when:** a route, syscall, job, flow or table changed, or the runtime pin moved. **Seen:** 2026-10-25,
2026-11-11 (#596).
**Fix:** rerun `scripts/inventory.py` and commit it. After a client API change, run
`UPDATE_CLIENT_ROUTES=1 npx vitest run client-routes-manifest` first.

### OPS-022: `FLOW_REGISTRY` holds only `nodus_execute` at boot
**Applies when:** looking for an app flow in the registry. **Seen:** recorded 2026-10-25.
App flow graphs register lazily. `registry.register_flows()` loads them.

### OPS-023: the client build fails without an api URL
**Applies when:** building the client outside CI. **Seen:** recorded 2026-10-25.
**Fix:** set `VITE_API_BASE_URL` (CI uses `https://ci-placeholder.aindy.dev`).

## Code and the registries

The stories behind the shorter rules in `CLAUDE.md`.

### OPS-024: syscalls registered through `platform_layer.registry` never dispatch
**Applies when:** registering a syscall. **Seen:** 2026-08-22.
`platform_layer.registry` exports a `register_syscall` that writes into a dict the `SyscallDispatcher` never reads.
The `CLAUDE.md` example block used to show that path. **Fix:** `from AINDY.kernel.syscall_registry import
SyscallContext, register_syscall`; every app syscall here uses it.

### OPS-025: invented registry names read as "no app uses this hook"
**Applies when:** checking whether an app uses a registration hook. **Seen:** before 2026-08-20.
An earlier `CLAUDE.md` listed plural names (`register_scheduler_jobs`, `register_syscalls`) that do not exist.
Grepping for them returned nothing, which read as "unused" rather than "wrong name", and that misreading went into two
specs. **Fix:** check names against `AINDY/platform_layer/registry.py`, and count registrations by booting, never from
a written number.

### OPS-026: a "make it async" remedy that registered a synchronous job
**Applies when:** choosing a job mechanism. **Seen:** 2026-08-19 (a shipped defect doc).
`register_job` is a synchronous callable looked up later; registering it does not make anything async. Background
dispatch is `register_async_job` in `AINDY.platform_layer.async_job_service`, outside the registry, so the registry's
import block is the wrong place to look, and "this domain already uses it" can be true of the app while false of the
module doing the slow work.

### OPS-027: a planner step fails at execution because the tool's args were guessed
**Applies when:** adding or changing an agent tool. **Seen:** 2026-09-13 (`arm.analyze`, 4 of 4 runs).
A tool without `args_schema` gives the planner only prose: `arm.analyze`'s description said "or a topic", the planner
passed a topic, and the tool took `file_path`. Schemas went on every tool (#389); `enforce` has been on since
2026-09-26, after 38 steps in 11 runs showed zero `invalid`. **Retire when:** never, while tools are hand-described.

### OPS-028: a FAILED flow fell through to the success path
**Applies when:** reading a `run_flow` result. **Seen:** 2026-09-05 (18 sites in 4 routers, #271).
`CLAUDE.md` once said a flow's status could be `"error"`; it never is, so `== "error"` checks never matched.
`APP-FLOW-STATUS-DEADBRANCH-1`. **Fix:** `run_flow_or_raise` / `run_flow_data` from `apps/_shared/flow.py`.

### OPS-029: a route never appears in the execution ledger
**Applies when:** a route's requests are missing from `system_events`. **Seen:** 2026-09-19 (eight routes),
2026-09-20 (80 call sites).
A `route_name` over 32 characters fails the `system_events.source` INSERT and the runtime carries on at WARNING
(`ROUTE-NAME-EVENT-SOURCE-1`, FR-41). A pipeline call without `metadata={"db": db}` runs outside the ledger
(`ROUTE-PIPELINE-NO-SESSION-1`, #393). Both are guarded by tests now.

### OPS-030: a page full of `{}` and a 15-minute wedge after giving the pipeline a session
**Applies when:** a pipeline route returns empty objects. **Seen:** 2026-09-20 (RippleTrace, 214 rows).
With the session in metadata the pipeline commits after the handler and `expire_on_commit` empties every loaded
instance, so returned ORM rows serialise as `{}` (`ROUTE-PIPELINE-ORM-RETURN-1`). **Fix:** return data, or wrap the
handler in `materialized(...)`.

## GitHub and dependencies

### OPS-031: a PR conflicts right after another one merges
**Applies when:** two open PRs touch the same file. **Seen:** recorded 2026-10-25.
A PR carrying another open PR's file conflicts once that one is squash-merged. **Fix:** keep files in one PR, or
rebase the second after the first merges.

### OPS-032: a certifi pin blocked a runtime adoption
**Applies when:** constraining certifi. **Seen:** 2026-10-22 (FR-54).
**Fix:** keep any certifi constraint of ours a lower bound.

**Reference**
- Branch protection requires up-to-date branches and auto-merge is off: merge PRs one at a time, then
  `gh pr update-branch` the next and let CI rerun.
- A new router needs a line in `docs/api/API_CONTRACTS.md`; a doc's `status` must be `current`, `outdated` or `draft`.
  A docs change runs `scripts/lint_docs.py` and `scripts/check_api_contracts.py` before pushing.

## Releases (the release handoff)

### OPS-033: a release handoff answers `409`
**Applies when:** handing off a release again. **Seen:** recorded 2026-10-25.
A released tag cannot be handed off again. A re-handoff after a failure reuses the open task.

**Reference**
- Questions for the runtime side go in `docs/runtime/` (the FR register or the adoption record), never a message to
  its session (owner, 2026-11-02; see OPS-901).
- The `production` gate: environment id `15804342446`; one reviewer, Masterplanner25; `prevent_self_review: false`.
  Approving needs **Deployments: write**.
- The approve token (`AINDY_GITHUB_APPROVE_TOKEN`) is used only by `decide()`. Check it by status code.
- The Gmail app password also reads IMAP; `[Gmail]/Sent Mail` holds what A.I.N.D.Y. sent.
- **Never print a secret.** Check tokens and the SMTP password by length or shape. smtplib's `debuglevel` leaks the
  password in base64.

## MCP (another AI reading A.I.N.D.Y.)

### OPS-034: the `aindy` MCP tools are gone mid-session
**Applies when:** the `aindy` server stops answering. **Seen:** recorded 2026-10-25.
It disconnects when the api restarts and comes back at the next session start. It also needs the api container up.

**Reference**
- Use the MCP tools for the owner's Work facts instead of asking for a paste.
- The public `/mcp` can be checked end to end from Claude Code: the owner's claude.ai connector appears as
  `mcp__claude_ai_A_I_N_D_Y_mcp_server__*` tools, and a call goes claude.ai → tunnel → `mcp`. The stdio `aindy`
  server checks only the api container.

## Agents, models and content

### OPS-035: a resubmitted agent run became a second run
**Applies when:** an agent request seems to time out. **Seen:** recorded 2026-10-25.
Planning takes 30–40 s; a resubmit after a client timeout starts another run. Wait for the first.

### OPS-036: a run's `steps_completed` looks too low
**Applies when:** reading run totals. **Seen:** 2026-09-17 (FR-34).
`steps_completed` counts successes only.

### OPS-037: a soak counted the wrong thing
**Applies when:** measuring a flag's effect. **Seen:** 2026-09-30 (soak row 1).
Row 1's recalls were requests, not agent runs. **Fix:** count what the flag's code path actually runs.

### OPS-038: the weekly Resolution Check did nothing
**Applies when:** a Resolution Check run is missing. **Seen:** recorded 2026-10-25.
It skips an owner whose last check is under 6 days old, silently.

### OPS-039: a feed source looks broken
**Applies when:** a feed poll fails. **Seen:** recorded 2026-10-25.
Feeds flap: YouTube's RSS gives intermittent 404s. One failed poll is not a broken source.

### OPS-040: Substack and Medium pieces have no links
**Applies when:** reading stored text's links. **Seen:** recorded 2026-10-25; backfill built 2026-11-08.
`content_archive.to_text` strips the `href` with the tag, so stored Substack and Medium text lost its link targets;
DEV keeps markdown links (130 of 145). `content_archive.backfill_links` recovers them by one re-fetch.

**Reference**
- A tool's description steers the planner more than anything else.
- Answer engines: the Responses API with `web_search` (not `gpt-4o-search-preview`); Claude's `web_search_20250305`
  and Perplexity `sonar` work.
- A draft's look-alikes come from the engines' answers (`resolution_review.engine_answers`). Edit a draft with
  `PATCH /apps/works/drafts/{id}`, and only on the owner's say-so (it is their account).

## Measurement

### OPS-041: a counter window was lost before it was read
**Applies when:** about to rebuild, recreate or restart the api while a counter window is open. **Seen:** 2026-10-22,
2026-11-11.
`aindy_payload_identity_mismatch_total` and `tenant_mismatch` reset on every api recreate and on a reboot. **Fix:**
read them before a rebuild.

### OPS-042: a schema change passed but the column did not change
**Applies when:** checking a migration or `bootstrap-schema`. **Seen:** 2026-09-23 (FR-43).
A column widening is invisible to `bootstrap-schema`'s exit code. **Fix:** check the column, not the exit code.

---

## Obsolete

Kept so the old lesson is not re-learned. Each says what replaced it.

- **OPS-901 (was "before a runtime release, message the runtime session").** Replaced 2026-11-02 by the owner: the
  runtime session is often not open, and a message to it bounces or expires. Questions go in `docs/runtime/`.
