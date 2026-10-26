---
title: "Operator notes — what running this stack has taught"
last_verified: "2026-10-25"
api_version: "1.0"
status: current
owner: "app-team"
---

# Operator notes: what running this stack has taught

Things learned by running, testing and releasing A.I.N.D.Y. that the code does not show. Moved here
on 2026-10-25 from `SESSION_HANDOFF.md`, which is gitignored and is for *where we are*, not for what
stays true (owner, 2026-10-25). `CLAUDE.md` holds the rules every change must follow; this holds the
lessons behind running things. Neither repeats the other.

Add a note when something cost time to learn. Delete one when it stops being true.

---

## The local stack (Docker on this Windows host)

- **Never bulk-remove containers by filter.** `docker ps -q --filter … --format …` ignores `--format`
  under `-q`, and on 2026-10-22 it deleted the live api. Use `--rm` and exact IDs.
- **`up -d api` after a build recreates only the api,** ~60–80 s to healthy.
- **A rebuild is slow when the base image's digest moved, not because of the pin.** 2.28.1 took
  53 min because `python:3.11-slim` had moved and the Debian mirror was slow. A pin move alone took
  399 s on 10-09.
- **A variable set in `.env` reaches the container only if compose lists it.**
- **The first requests after an api boot can come back empty** for a few seconds.
- **The api log carries WARNING and above only.** The ledger (`system_events`) is the request log.
  Per-request durations: pair `execution.started` and `execution.completed` by `trace_id`.
- **To time a route without the api's own load,** use a throwaway container from the api image with
  `AINDY_ENABLE_BACKGROUND_TASKS=false`, and yappi across all threads.
- **Cron hours:** 00, 06, 07, 12, 18 UTC.
- **The api is localhost-only,** so no link in an email reaches it away from the desk.
- **A minted token lasts about a day.**
- **To manufacture an authority denial,** mint the token in a `docker exec` under
  `mint_token(capability_ceiling=[…])` without `external_api_call`, then `execute_run`.

## Testing on this host

- **Windows Application Control blocks the venv's `pydantic_core` DLL.** Run Python tests, and
  `scripts/inventory.py`, in a `--rm` container from the api image, on a slim `tar` copy of the repo
  (no venv, `node_modules`, `.git` or `__pycache__`), after `pip install pytest…` (and `pyyaml` for
  `test_compose_memory_bounds.py`).
- **`xdist` is not installed;** run the unit suite serially.
- **A client test that fails under load is usually its timeout,** not its logic. vitest's default is
  20 s since #464; check the duration first, and reproduce with the Python suite running alongside.
- **`npm ci` while Vite is running fails on Windows** and deletes `node_modules`.
- **`python -` (stdin) decodes as cp1252 on this host.** Write scripts to a file.
- **Escapes in a Bash heredoc get mangled.** A `\n` inside Python inside a heredoc became a real newline
  twice on 10-25, and one heredoc would not parse. Write such code with the Write or Edit tool.
- **An em dash in a curl JSON body through Git Bash gives `400`.** Use ASCII, or `--data-binary @file`.
- **Claude Code reaps background tasks when host memory is low.** A detached Vite survives it.
- **A stale repo-root `aindy_apps_monolith.egg-info` shadows installed metadata;** delete it.
- **A runtime default flip breaks tests that encode "unset means off".**
- **Every RippleTrace route wraps its handler in `materialized(...)`.** `test_handler_returns_data_not_rows`
  failed #501's first CI run; run it when you add a RippleTrace route.
- **After a route, syscall, job, flow or table change, rerun `scripts/inventory.py`,** or CI fails.
  After a client API change, run `UPDATE_CLIENT_ROUTES=1 npx vitest run client-routes-manifest` first.
- **App flow graphs register lazily.** `registry.register_flows()` loads them; at boot `FLOW_REGISTRY`
  holds only the runtime's `nodus_execute`.
- **The client build needs `VITE_API_BASE_URL`** (CI uses `https://ci-placeholder.aindy.dev`).

## GitHub and dependencies

- **Branch protection requires up-to-date branches, and auto-merge is off.** Merge PRs one at a time;
  after a merge, `gh pr update-branch` the next one and let CI rerun.
- **A PR that carries another open PR's file conflicts once that one is squash-merged.**
- **Keep any certifi constraint of ours a lower bound.**
- **A new router needs a line in `docs/api/API_CONTRACTS.md`,** and a doc's `status` must be
  `current`, `outdated` or `draft`.

## Releases (the release handoff)

- **Before a runtime release, message the runtime session** (`ListAgents`, then `SendMessage`) to confirm
  the `publish.yml` job names, the `production` gate and the handoff path.
- **A released tag cannot be handed off again** (409). A re-handoff after a failure reuses the open task.
- **The `production` gate:** environment id `15804342446`; one reviewer, Masterplanner25;
  `prevent_self_review: false`. Approving needs **Deployments: write**.
- **The approve token (`AINDY_GITHUB_APPROVE_TOKEN`) is used only by `decide()`.** Check it by status
  code, never by printing it.
- **The Gmail app password also reads IMAP;** `[Gmail]/Sent Mail` holds what A.I.N.D.Y. sent.
- **Never print a secret.** Check tokens and the SMTP password by length or shape. smtplib's `debuglevel`
  leaks the password in base64.

## MCP (another AI reading A.I.N.D.Y.)

- **The `aindy` MCP server disconnects when the api restarts,** and comes back at the next session start.
  It also needs the api container up.
- **Use the MCP tools for the owner's Work facts** instead of asking for a paste.

## Agents, models and content

- **A tool's description steers the planner more than anything else.**
- **Agent planning takes 30–40 s;** a resubmit after a timeout is a second run.
- **`steps_completed` counts successes only** (FR-34).
- **Count what a flag's code path actually runs** (soak row 1's recalls were requests, not agent runs).
- **Answer engines:** the Responses API with `web_search` (not `gpt-4o-search-preview`); Claude's
  `web_search_20250305` and Perplexity `sonar` work.
- **The weekly Resolution Check skips an owner whose last check is under 6 days old,** silently.
- **A draft's look-alikes come from the engines' answers** (`resolution_review.engine_answers`). To edit a
  draft, `PATCH /apps/works/drafts/{id}`, and only on the owner's say-so (it is their account).
- **Feeds flap.** YouTube's RSS gives intermittent 404s; one failed poll is not a broken source.
- **Stored Substack and Medium text has lost its link targets.** `content_archive.to_text` strips the
  `href` with the tag. DEV keeps markdown links (130 of 145).

## Measurement

- **The identity counter (`aindy_payload_identity_mismatch_total`) resets on every api recreate.** Read it
  before a rebuild; window 2 was lost that way.
- **Check a schema change by the column, not the exit code** (FR-43).
