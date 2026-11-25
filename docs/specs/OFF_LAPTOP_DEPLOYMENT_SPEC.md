---
title: "Off the laptop"
last_verified: "2026-11-25"
api_version: "1.0"
status: draft
owner: "app-team"
---

# Off the laptop: A.I.N.D.Y. runs on a server, the laptop goes back to being a laptop

**Status:** scoped 2026-11-23. §8's decisions are open except 3 (taken 2026-11-25). **Phases A–C built 2026-11-25** (§4; `DEPLOYMENT.md` is the runbook); D–F are not.

**Origin.** The owner, 2026-11-23: *"right now the limit to developing and/or using my laptop fully is that I need to
keep the app running."* The whole stack (api, `mcp`, postgres, mongo, redis, mailpit, the ngrok tunnel) runs in Docker
on a 7.7 GB Windows laptop. It has to stay up, so the laptop's memory is never fully the owner's: on 2026-11-23 the
runtime 2.41.0 build was killed for host memory, with the api already down. Buying a second machine would fix that
too. The owner chose a deployment instead: **"it will get us some practice where we'll end up needing it."**

**Not the goal:** going live. No public web app, no other users, no TLS front door. The api stays private, as it is
today. The one public path stays the read-only MCP tunnel, which moves with the stack.

**What the owner gets beyond a free laptop:** every scheduled job runs on time. Today the weekly Resolution Check, the
release watcher, the 06:00 Infinity recalculation and the owner notices run only while the laptop is awake.

---

## 1. What exists (read 2026-11-23)

- **The stack:** `docker-compose.prod.yml` + `docker-compose.mongo.yml`, profiles `full` (redis), `mail` (mailpit) and
  `public-mcp` (`mcp` + `mcp-tunnel`). Ports are bound to `127.0.0.1`. Memory caps: api 1,536 MB, `mcp` 768 MB, mongo
  768 MB, tunnel 128 MB; postgres, redis and mailpit uncapped. About 3.5–4 GB in all.
- **The data:** postgres `aindy` 712 MB (volume 854 MB), mongo 518 MB, `nodus_state` under 1 MB. A stale
  `aindy-runtime_postgres_data` volume (142 MB, from before the split) is not in use.
- **The secrets:** `.env`. Among them the **provider-key master key** (startup refuses `AINDY_PROVIDER_KEYS=per_user`
  without it, and without it the per-user keys stored in the database cannot be decrypted), the ngrok token and
  domain, SMTP and IMAP, `AINDY_GITHUB_TOKEN` and `AINDY_GITHUB_APPROVE_TOKEN`, the model keys.
- **How a release goes live today:** `docker compose … build api` on the laptop, then recreate `api` and `mcp`. Nothing
  publishes an image: no workflow pushes to a registry (`app-ci`, `codeql`, `deploy-bootstrap-guard`,
  `nodus-vm-integration`, `security-audit`, `serve-run-completion`).
- **What proves a fresh deploy already:** `deploy-bootstrap-guard` builds a blank Postgres on every PR and runs the
  real entrypoint (pgvector, runtime `bootstrap-schema`, app schema, `serve`). The runtime is pinned exactly
  (`constraints.txt`) and migrates itself at boot.
- **What is tied to the laptop and must stay there:**

  | Piece | Points at | How |
  |---|---|---|
  | `aindy-watcher` (activity) | `http://127.0.0.1:8000` | `~/.aindy/start-watcher.ps1`, `AINDY_WATCHER_API_URL` |
  | Directing hook (Claude Code prompts) | `http://127.0.0.1:8000` | `scripts/directing_hook.py`; `api_url` in `~/.aindy/directing.json` |
  | Vite (the client in development) | `http://127.0.0.1:8000` | **hard-coded** proxy targets in `client/vite.config.ts` |
  | Claude Code's `aindy` MCP | the local container | stdio, `docker exec -i …` in `~/.claude.json` |

- **What starts at sign-in on the laptop** (`laptop-sign-in-startup`): the Docker stack, the watcher, Vite, and the
  owner's separate Nodus MCP server and its tunnel (not A.I.N.D.Y.'s; it stays).
- **Not in the deployment guide:** `docs/operations/DEPLOYMENT.md` was last verified 2026-07-15. It says redis is
  optional (it is not: `COMPOSE-REDIS-URL-UNCONDITIONAL-1`, every rate-limited route 500s without it, `/health`
  included), and it does not cover the profiles, the mongo overlay, the master key or the tunnel.
- **No backups.** Nothing in the repo dumps or restores the data.

## 2. The shape

```
 laptop (development, and the person)              server (the instance)
 ─────────────────────────────────────             ─────────────────────────────────────
 aindy-watcher ──┐                                 api ─ postgres ─ mongo ─ redis ─ mailpit
 directing hook ─┼── private link (tailnet) ─────▶ mcp ─ mcp-tunnel ──▶ ngrok ──▶ claude.ai / ChatGPT
 Vite (dev UI) ──┤                                 nightly backup ──▶ off-server copy
 Claude Code ────┘   (MCP: docker over ssh)
 tests, CI, editing; a local stack only on demand, in dev mode (§5)
```

- **The server runs the stack exactly as compose describes it**, from a published image, not a local build.
- **The laptop keeps what watches the laptop:** the watcher, the hook, Vite, Claude Code. They post to the server over
  a private link. When the laptop is off they post nothing, as now; the hook's backfill catches up at sign-in.
- **Nothing new is public.** The api is reachable only over the private link. The ngrok tunnel to `mcp` moves to the
  server unchanged.

## 3. Deploying: CI publishes, the server pulls

The practice the owner asked for is mostly here.

- **CI builds the api image on every merge to `main`** and pushes it to GitHub's container registry, tagged with the
  commit SHA (and `main`). **The package is public** (decision 3): the image holds the code (public anyway), the
  runtime from PyPI, and no secrets, so a host pulls it without a token.
- **Compose takes the image from a variable** (`AINDY_IMAGE`, defaulting to today's local build), so the laptop can
  still build locally and the server names a tag.
- **A deploy is:** `AINDY_IMAGE=ghcr.io/…:<sha> docker compose … pull api && … up -d api mcp`, wrapped in one script on
  the server that reads the counters first (OPS-041), recreates, waits for `healthy`, and prints the confirm line. A
  rollback is the same command with the previous SHA.
- **The runtime self-migrates at boot**, so a deploy that moves the runtime pin migrates the server's database. That
  was already true on the laptop; the adoption record stays the gate.
- **Later, not now:** a manual `workflow_dispatch` that runs the deploy over SSH. Manual first, so the steps are known
  before they are automated.
- **Builds leave the server.** A small server never builds the image, so the memory kill cannot recur there.

## 4. Backups

- **Nightly on the server:** `pg_dump` (custom format) of `aindy`, `mongodump` of the social database, and a tar of
  `nodus_state`, written to a dated folder; keep 14.
- **Copied off the server** (decision 5). A backup on the same disk is not a backup.
- **A restore is tested,** not assumed: into a scratch database, with row counts compared, by the same script that
  will do the migration (§6). A backup that has never been restored does not count.
- **The same scripts move the data** from the laptop to the server, so the migration is the restore's first real use.

**Built 2026-11-25 (phase A).** `scripts/backup_stack.py` and `scripts/restore_stack.py`, stdlib only (a server runs them
with its system python3), reaching the databases by `docker exec` on the containers' compose labels, so they need
neither the compose files nor `.env`.

- **Backup:** `python scripts/backup_stack.py` writes `$AINDY_BACKUP_DIR` (default `~/aindy-backups`)`/<UTC stamp>/`:
  `postgres.dump` (`pg_dump -Fc`), `mongo.archive.gz`, `nodus_state.tar.gz` and `manifest.json` (sha256s, schema heads,
  row counts). It keeps 14. The stack stays up: postgres is counted before and after the dump, and a table that moved
  during it must restore to a count between the two; every other table must restore exactly. First run: 134 tables,
  974,843 rows, 130 MB, 45 s.
- **Restore test (the default):** `python scripts/restore_stack.py [latest|<stamp>]` restores into
  `aindy_restore_check` and `aindy_default_restore_check`, compares, and drops them; about a minute. Passed on the
  first backup.
- **Live restore (§6):** `--live --yes` refuses while `api` or `mcp` runs, tests the backup first, takes a
  `-before-restore` safety backup (never pruned), restores postgres into `aindy_incoming` and swaps it in only after
  its counts pass (the old database is renamed `aindy_replaced_<stamp>`, not dropped), then mongo and nodus_state.
  Proven against a throwaway postgres and mongo standing in for a fresh server: everything matched on a second
  backup taken from it.
- **The social database is `aindy_default`,** the runtime's `MONGO_DB_NAME` default. The `/aindy` in compose's
  `MONGO_URL` names a database nothing writes to, and the 518 MB in §1 is the volume, not data: 2 posts and 14
  metric rows.
- **Nightly on the laptop until the move:** the Windows task "A.I.N.D.Y. backup" (03:00, runs on wake if missed)
  calls `~/.aindy/backup-stack.ps1`, outside the repo; Sundays it also runs the restore test. Log
  `~/.aindy/backup.log`.

## 5. Two environments, kept apart

After cutover the server is the instance and the laptop is development.

- **Day to day, development needs no running stack:** the unit suite, the docs checks and CI do not.
- **When a local stack is wanted, it runs in dev mode.** This is the trap: a laptop stack restored from a copy of the
  real data would run the same scheduled jobs against it. It would pay for the weekly Resolution Check again
  (`masterplan_resolution_weekly`), email owner notices (`owner_notices_tick`), poll GitHub and could act on runtime
  release approvals (`release_handoff_watch`), and spend on RippleTrace's jobs (`rippletrace_share_drafts`,
  `rippletrace_piece_answers`, …). Dev mode turns off:
  - **the outward-facing scheduled jobs:** anything that spends, mails, or calls GitHub. The list is the jobs registered
    today; a new job declares which side it is on, and a test fails if one does not;
  - **real mail:** mail goes to mailpit only;
  - **the tunnel:** no `public-mcp` profile.

  Whether this is one flag of ours (`AINDY_ENVIRONMENT=dev`) or needs the runtime's scheduler to skip jobs is checked
  in phase D; a runtime switch, if needed, is an FR.
- **The parallel run uses dev mode too.** While the server is being checked (§6), the laptop is still the instance, so
  the server runs in dev mode until the moment it takes over.
- **The laptop's sign-in tasks stop starting the stack** at cutover. Otherwise two instances run on two copies of the
  data, and both act.

## 6. The move (runbook outline; the full runbook is `DEPLOYMENT.md`, phase B)

1. **Provision.** Linux, native `docker-ce` (not Docker Desktop), 8 GB RAM, about 40 GB disk. Tailscale. Firewall:
   nothing inbound but SSH, and SSH only from the tailnet once it works.
2. **Install.** Clone the repo (compose files, scripts), write `.env` from the laptop's (§1's list), log in to the
   registry, pull the image.
3. **Restore a recent backup and start in dev mode,** with the laptop still the instance. Check: `/health`, the
   confirm line, schema heads, the Collaborator, a few real reads, row counts against the dump.
4. **Cut over,** in one sitting:
   1. Read the counters on the laptop, then stop the laptop's `api`, `mcp` and tunnel. The data stops changing.
   2. Take the final backup and restore it on the server.
   3. Leave dev mode on the server, start the `public-mcp` profile there (only one ngrok agent can hold the domain).
   4. Point the laptop's clients at the server (§7), then check: a watcher post, a directing prompt, the client signing
      in through Vite, Claude Code's `aindy` MCP, claude.ai's connector.
   5. Remove the stack from the laptop's sign-in tasks.
5. **Keep the laptop's volumes** untouched for two weeks as the fallback. Delete them only after a restore from the
   server's own backups has worked.

## 7. Reaching the server from the laptop

The api stays bound to loopback on the server. Two ways to reach it, decision 2:

- **Tailscale, recommended.** The laptop and the server join one tailnet. The compose port binding becomes a variable
  (`AINDY_BIND_ADDR`, default `127.0.0.1`), set on the server to its tailnet address, so the api answers only there.
  The laptop's three URLs (watcher, hook, Vite) take one setting, `AINDY_API_URL`; Vite's proxy target stops being
  hard-coded.
- **An SSH tunnel** (`ssh -L 8000:127.0.0.1:8000 server`) keeps every laptop URL as it is and needs no new setting,
  but it has to be running for anything to post, and a dropped tunnel looks like a dead server.

Claude Code's `aindy` MCP keeps its `docker exec` and gains `DOCKER_HOST=ssh://<server>` in its config.

## 8. Decisions: the owner's

1. **Where.** A VPS (**recommended**: the practice is the point, and it is resizable) or a box at home. 8 GB of RAM,
   native Linux.
2. **The private link.** Tailscale (**recommended**) or an SSH tunnel (§7).
3. **The registry.** ✅ **Taken 2026-11-25 (owner): GitHub's container registry, public package**,
   `ghcr.io/masterplanner25/aindy-api`. Scoped as private; checked before deciding: the repo is public and the image
   carries no `.env` (the Dockerfile copies named folders only), so private would have bought a pull token on the
   server and, if GitHub bills private packages, a cleanup job under the free plan's 500 MB. Also weighed: Docker
   Hub (a second account, pull limits), the VPS provider's registry (ties it to decision 1), no registry (CI holds
   an SSH key to the server).
4. **How a deploy is triggered.** A script run by hand on the server first (**recommended**), a dispatched workflow
   once the script has run a few releases.
5. **Where backups go off the server.** Object storage at the same provider, or pulled to the laptop nightly while it
   is on. **Recommended: object storage**: the laptop is the machine being freed.
6. **What dev mode turns off** (§5). Recommended: every scheduled job that spends money, sends mail or calls GitHub,
   plus real mail and the tunnel. Everything else runs, so a local stack still behaves like the real one.
7. **The laptop stack afterwards.** Kept as the dev stack, not started at sign-in (**recommended**), or removed.

## 9. Phases

Each phase is a PR, or a session on the server. A–D are repo work and need no host.

- **A. Backup and restore.** `scripts/backup_stack.*` and `restore_stack.*` (postgres, mongo, `nodus_state`), a
  restore tested into a scratch database with row counts compared. Run nightly on the laptop until the move.
- **B. The bring-up, written down.** ✅ 2026-11-25: redis out of its profile, `AINDY_BIND_ADDR`, `DEPLOYMENT.md`
  rewritten as the runbook (the deploy script is phase C's, with the image). Fix `COMPOSE-REDIS-URL-UNCONDITIONAL-1`; rewrite `DEPLOYMENT.md` as the runbook
  for §6 (profiles, overlay, the `.env` checklist, the tunnel, the deploy script); `AINDY_BIND_ADDR`.
- **C. Images from CI.** ✅ 2026-11-25: `.github/workflows/publish-image.yml` (builds and smokes on a PR that
  touches the image's inputs; pushes `:<sha>` and `:main` on merge, plain docker commands with the job's own token),
  `AINDY_IMAGE` for `api` and `mcp`, `scripts/deploy_stack.py` (pull, counters, backup, `.env`, recreate, health,
  confirm line, `~/aindy-deploys.jsonl`).
- **D. Dev mode.** The switch, the job classification with its test, mail to mailpit only; `AINDY_API_URL` for the
  watcher, the hook and Vite.
- **E. The server.** Provision (decision 1), install, restore, run in dev mode beside the laptop, check.
- **F. Cutover.** §6 step 4, then two weeks with the laptop's volumes kept. The handoff and `OPERATOR_NOTES` say where
  the instance lives.

## 10. Risks

- **Two instances acting at once:** the laptop's sign-in tasks restart the stack, or the server leaves dev mode while
  the laptop still runs. Both pay twice and mail twice. Guarded by §5 and §6's order.
- **The master key not copied, or copied wrong:** every stored per-user key becomes unreadable; only the owner's
  server-key path keeps working. Checked in §6 step 3 by a key read, before cutover.
- **A runtime pin move on the first deploy:** the server migrates on boot. The move uses the image the laptop already
  runs; the first pin move after it follows the adoption record as always.
- **Latency:** the directing hook has a 3-second timeout. A hook post that times out is caught up from the transcript
  by the next prompt, as today when the api is down.
- **Cost:** a monthly bill that the laptop did not have.
