---
title: "Server Deployment"
last_verified: "2026-11-25"
api_version: "1.0"
status: current
owner: "apps-team"
---
# Server Deployment

How A.I.N.D.Y. runs on a host, and how it moves to a new one. Rewritten 2026-11-25 as the runbook for
`docs/specs/OFF_LAPTOP_DEPLOYMENT_SPEC.md` §6 (phase B). **Since 2026-11-26 the instance is the server** (Hetzner,
Ubuntu 26.04, reached over Tailscale; §6 was run end to end). The laptop keeps a dev stack (§6, dev mode).

**Not for going live.** The api is private: bound to loopback, or to a tailnet address on a server. The only public
path is the read-only MCP tunnel (`public-mcp`, below).

## 1. What runs

Two compose files and three profiles. **Every `up` and `down` names all of them**: an `up` or `down` without a
profile leaves that profile's services as they were.

```bash
COMPOSE="docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml --profile full --profile mail --profile public-mcp"
$COMPOSE up -d
```

| Service | From | Memory cap | Notes |
|---|---|---|---|
| `api` | `docker-compose.prod.yml` | 1,536 MB | the app; port 8000 on `AINDY_BIND_ADDR` (default `127.0.0.1`) |
| `postgres` | `docker-compose.prod.yml` | none | pgvector, pg16; volume `postgres_data` |
| `redis` | `docker-compose.prod.yml` | none | **always runs** (since 2026-11-25): the rate limiter and wait registry need it |
| `mongo` | `docker-compose.mongo.yml` | 768 MB | the social layer's database, `aindy_default`; volume `mongo_data` |
| `mailpit` | profile `mail` | none | a mail sink on 127.0.0.1:8025; the api sends real mail unless `.env` points it here |
| `mcp`, `mcp-tunnel` | profile `public-mcp` | 768 MB, 128 MB | read-only MCP for claude.ai and ChatGPT, over ngrok (`scripts/CLAUDE.md`) |

The `full` profile gates nothing any more; it stays in the commands so older ones still read the same. Before
2026-11-25 it gated redis, and an `up` without it served 500 on every rate-limited route, `/health` included
(`COMPOSE-REDIS-URL-UNCONDITIONAL-1`).

**Only one ngrok agent can hold the public domain.** Never run `public-mcp` on two hosts at once.

### The image and what its entrypoint does

`Dockerfile` builds the app image (apps + the pinned runtime from `constraints.txt`); `mcp` uses the same image.
`docker/entrypoint.sh` runs before the server binds:

1. `python scripts/ensure_pgvector.py`: the `vector` extension exists.
2. `aindy-runtime bootstrap-schema`: the **runtime** builds or migrates its own tables (`alembic_version_runtime`).
   **A runtime pin move therefore migrates the database at boot**; the adoption record (`docs/runtime/`) is the gate.
3. `python scripts/deploy_bootstrap.py`: the **app's** tables (fresh database: `create_all` + `stamp head`; existing:
   `alembic upgrade head`).
4. `exec aindy-runtime serve`: binds, loads `./aindy_plugins.json` (16 domains), starts the scheduler.

The `deploy-bootstrap-guard` CI workflow runs this against a blank Postgres on every PR.

## 2. The host

- **Linux with native `docker-ce`**, not Docker Desktop (whose VM inflates every postgres round trip; see §8).
- **8 GB of RAM, about 40 GB of disk.** The stack takes 3.5–4 GB; builds do not happen here once images come from CI
  (phase C). Until then a build needs about 2 GB free on top.
- **Tailscale**, and nothing inbound but SSH, from the tailnet once it works.
- A clone of this repo (compose files, `docker/`, `scripts/`), and Python 3 for the backup scripts (stdlib only).

**`scripts/server/setup_host.sh` does all of that** on a fresh Ubuntu VPS (phase E; first run 2026-11-26 on Hetzner's
Ubuntu 26.04, whose `resolute` packages Docker and Tailscale both publish), and can be run again:

```bash
curl -fsSLO https://raw.githubusercontent.com/Masterplanner25/A.I.N.D.Y./main/scripts/server/setup_host.sh
sudo bash setup_host.sh              # docker-ce, tailscale, restic, ufw (SSH only), user aindy, ~aindy/aindy, the timer
sudo tailscale up                    # sign in; `tailscale ip -4` is the AINDY_BIND_ADDR
# from the laptop, `ssh aindy@<tailnet address>` works? then, keeping the old session open:
sudo bash setup_host.sh --lock-ssh   # SSH from the tailnet only
```

Docker publishes ports past ufw, through its own iptables rules. What keeps the stack private is compose binding every
host port to `127.0.0.1` and the api to `AINDY_BIND_ADDR`; the VPS provider's own firewall, if it has one, can also
allow nothing but SSH.

## 3. `.env`

Copy it from the laptop, file to file, never through a chat or an issue. Compose reads it from the repo root.

| Group | Keys | On a new host |
|---|---|---|
| **Must match the data** | `AINDY_SECRET_PROVIDER_KEY_ENCRYPTION_KEYS` | **Copy exactly.** It decrypts the per-user provider keys stored in the database; without it every stored key is unreadable, and startup refuses `AINDY_PROVIDER_KEYS=per_user` (the compose default). |
| Signing | `SECRET_KEY`, `PERMISSION_SECRET`, `AINDY_API_KEY` | Copy. A new `SECRET_KEY` signs everyone out. |
| Model keys | `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `PERPLEXITY_API_KEY` | Copy. |
| Mail | `AINDY_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM`, `_STARTTLS` | Copy. This is real mail (owner notices, the release handoff gate). On a host that must not send, point them at `mailpit` (port 1025, STARTTLS false). |
| GitHub | `AINDY_GITHUB_TOKEN`, `AINDY_GITHUB_APPROVE_TOKEN` | Copy. The approve token acts on runtime releases: only the instance holds it. |
| Public MCP | `NGROK_AUTHTOKEN`, `AINDY_MCP_PUBLIC_URL` | Copy; used only with `public-mcp`. |
| Links in mail | `AINDY_EMAIL_VERIFY_URL_TEMPLATE`, `AINDY_PASSWORD_RESET_URL_TEMPLATE`, `ALLOWED_ORIGINS` | Copy. They name the client on the laptop (`localhost:5173`), which is where the owner signs in. |
| Behaviour flags | every other `AINDY_*` | Copy as they are. |
| **Server only** | `AINDY_BIND_ADDR` | The server's tailnet address (§6). Never `0.0.0.0`. |
| **Server only** | `COMPOSE_PROJECT_NAME=aindy-apps-monolith` | The laptop's project is named after its folder; the server's clone is `~/aindy`. Without this the server's containers and volumes get another name, and the backup scripts (which look for `aindy-apps-monolith`) find nothing. |
| **Server only** | `FORWARDED_ALLOW_IPS=<the server's compose subnet>` | `mcp` trusts `X-Forwarded-For` only from this range, and compose's default (`172.19.0.0/16`) is the laptop's. Read the server's with `docker network inspect aindy-apps-monolith_default -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}'` (it was `172.18.0.0/16`). Wrong, the consent page's rate limit counts every caller as one. |
| Server only, before the first `up` | `POSTGRES_PASSWORD` | Optional (postgres has no host port), but it can only be set before postgres first initialises its volume. |
| Laptop only | `DATABASE_URL` | For host-side tools; compose sets the containers' own. Leave it out on a server. |

`.env.example` lists the rest of what the runtime reads.

## 4. Backups

`scripts/backup_stack.py` and `scripts/restore_stack.py` (phase A, built 2026-11-25; the spec's §4 has the detail).

```bash
python3 scripts/backup_stack.py                 # postgres + mongo + nodus_state -> ~/aindy-backups/<UTC stamp>/, keeps 14
python3 scripts/restore_stack.py                # TEST the newest: scratch databases, counts compared; changes nothing
python3 scripts/restore_stack.py <stamp> --live --yes   # replace the stack's data (api and mcp must be stopped)
```

A backup is about 130 MB and 45 s. The live restore keeps the database it replaced (`aindy_replaced_<stamp>`) and a
`-before-restore` backup; drop them once the restored stack is checked. On the laptop the task "A.I.N.D.Y. backup"
runs it nightly.

**On a server**, systemd's `aindy-backup.timer` (from `setup_host.sh`; 03:00 UTC, caught up after downtime) runs
`scripts/server/nightly_backup.sh` as `aindy`: the backup, the restore test on Sundays, then **the copy off the
server** (decision 5) with restic, encrypted before it leaves. It reads `~aindy/.aindy/offsite.env` (mode 600):

```bash
RESTIC_REPOSITORY=s3:https://<endpoint>/<bucket>/aindy     # any S3-compatible object storage
RESTIC_PASSWORD_FILE=/home/aindy/.aindy/restic-password    # generate it once; keep a copy in a password manager
AWS_ACCESS_KEY_ID=...                                       # a key limited to that bucket
AWS_SECRET_ACCESS_KEY=...
AINDY_BACKUP_PING_URL=https://hc-ping.com/<uuid>            # optional: a dead-man's switch that mails when a night is missed
```

It keeps 14 daily, 8 weekly and 6 monthly copies, and on Sundays `restic check` reads back 5% of them. Without
`offsite.env` it backs up locally and logs that it skipped the copy. Check it: `systemctl list-timers aindy-backup.timer`,
`journalctl -u aindy-backup -n 50`. **Getting a backup back from the copy** (the server is gone, or its disk is):

```bash
restic snapshots                                           # with offsite.env's variables exported
restic restore latest --target /tmp/from-offsite           # -> /tmp/from-offsite/home/aindy/aindy-backups/<stamp>/
mv /tmp/from-offsite/home/aindy/aindy-backups/<stamp> ~/aindy-backups/ && python3 scripts/restore_stack.py <stamp>
```

**Without the restic password the copies cannot be read**: it is the one secret that must live somewhere other than
the server.

## 5. Checking a running stack

```bash
API=$($COMPOSE ps -q api)
curl -s http://$AINDY_BIND_ADDR:8000/health                      # 200; a 500 with /api/version 200 means redis is down
docker exec $API python -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
#   -> the pinned runtime, from site-packages
curl -s http://$AINDY_BIND_ADDR:8000/api/version | python3 -m json.tool | grep -E 'boot_profile|app_plugin'
#   -> default-apps, 16 plugins
docker exec $($COMPOSE ps -q postgres) psql -U aindy -Atc \
  "select version_num from alembic_version_runtime union all select version_num from alembic_version"
#   -> the heads the latest adoption record names
docker logs $($COMPOSE ps -q postgres) 2>&1 | grep -c "terminating any other active server processes"   # 0
```

**Before any recreate of the api, read the counters** the open adoption record names (OPS-041: they reset on every
recreate), e.g. `curl -s http://127.0.0.1:8000/metrics/ | grep -E 'mismatch|gated'`.

## 6. Moving to a new host

The order matters more than any one command: **two instances acting on two copies of the data both spend, both mail,
and both act on GitHub.** So exactly one stack runs without dev mode (below) at any time: the laptop until step 4,
the server after it.

1. **Provision** (§2: `setup_host.sh`). Join the tailnet. Note the server's tailnet address.
2. **Install.** Clone the repo; write `.env` (§3) with `AINDY_BIND_ADDR=<tailnet address>`,
   `COMPOSE_PROJECT_NAME=aindy-apps-monolith`, Unix line endings (a laptop `.env` has CRLF: `sed -i 's/\r$//' .env`)
   and `AINDY_IMAGE=ghcr.io/masterplanner25/aindy-api:<sha>`; `docker pull` it. **The image must be from #640 or
   later** (`17ece86`): an older one has no dev mode, so `AINDY_ENVIRONMENT=dev` does nothing and the server runs the
   paid jobs. Same runtime pin as the laptop, so the restored data needs no migration.
3. **Restore a recent backup, without the api:**
   ```bash
   $COMPOSE create                       # every container and volume, nothing started
   $COMPOSE up -d postgres mongo redis
   scp -r laptop:~/aindy-backups/<stamp> ~/aindy-backups/
   python3 scripts/restore_stack.py <stamp>                 # the test first
   python3 scripts/restore_stack.py <stamp> --live --yes
   ```
   Then start the server **in dev mode** (`-f docker-compose.dev.yml`, no `public-mcp`; below) and check it: §5, the
   boot warning, the Collaborator through an SSH tunnel or `AINDY_API_URL`, a few real reads, a stored provider key
   read.
4. **Cut over, in one sitting:**
   1. On the laptop: read the counters, then `$COMPOSE stop api mcp mcp-tunnel`. The data stops changing.
   2. `python scripts/backup_stack.py` on the laptop; copy that folder over; `restore_stack.py <stamp> --live --yes`
      on the server.
   3. On the server: `python3 scripts/deploy_stack.py <sha> --instance --services api,mcp,mcp-tunnel`, with the
      image the server already runs. **Name `mcp-tunnel`**: the default recreates `api,mcp` only, and the tunnel is
      not running yet. Check §5, that the api has no `[dev mode]` line, and through the public URL that
      `/.well-known/oauth-protected-resource/mcp` is 200 and `/health` is 404.
   4. Point the laptop's clients at the server (spec §7: the watcher, the directing hook, Vite's proxy, Claude Code's
      `aindy` MCP with `DOCKER_HOST=ssh://<server>`), then check each: a watcher post, a directing prompt, signing in
      through Vite, an MCP read, claude.ai's connector.
   5. Remove the stack from the laptop's sign-in, so the laptop never brings a second instance back. Done on
      2026-11-26 by `$COMPOSE stop` of the whole laptop stack (`restart: unless-stopped` keeps it stopped through
      reboots; the volumes stay) and disabling the laptop's nightly backup task, which the server's replaces.
5. **Keep the laptop's volumes for two weeks**, untouched. Delete them only after a restore from the server's own
   backups has passed.

**To go back** within those two weeks: stop the server's stack, back it up, restore that onto the laptop with
`--live --yes`, start the laptop's stack.

### Dev mode: any stack that is not the instance

`docker-compose.dev.yml` (phase D, 2026-11-25), layered on, and **without** `public-mcp`:

```bash
DEV="docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml -f docker-compose.dev.yml --profile full --profile mail"
$DEV up -d
docker logs $($DEV ps -q api) 2>&1 | grep "\[dev mode\]"   # no line, no dev mode
```

It sets `AINDY_ENVIRONMENT=dev`, under which the nine outward scheduled jobs (anything that spends, mails, calls
GitHub or fetches new data the instance acts on; the list is `tests/unit/test_dev_mode.py`) return
`{"skipped": true, "reason": "dev_mode"}` on every run. It also sends all mail to mailpit (`127.0.0.1:8025`), blanks
both GitHub tokens and the ngrok token, and turns off durable agent continuation. Everything else runs.

**Where a dev stack is used:** the server between steps 3 and 4 of the move; the laptop after it (decision 7), never
started at sign-in. A recreate must keep naming the overlay: an `up` without `-f docker-compose.dev.yml` takes dev
mode away. **`deploy_stack.py` keeps the mode it finds**: it reads `AINDY_ENVIRONMENT` from the running api and
recreates in the same mode (with the overlay and without `public-mcp` for a dev stack), then fails if the api came up
in any other. `--dev` or `--instance` changes it on purpose; with no api running, it asks for one of them. The first
deploy after the restore (§6 step 3) is therefore `deploy_stack.py <sha> --dev`, and cutover (step 4) is
`--instance`.

**A new scheduled job** registers with `schedule_job(..., outward=True|False)` from `apps/_shared/environment.py`;
an outward one also carries `@outward_job` on its function. `test_dev_mode.py` fails otherwise.

### Pointing the laptop's clients at a server

One setting, `AINDY_API_URL` (a Windows user environment variable, e.g. `http://<tailnet address>:8000`), read by
Vite's dev proxy (`client/vite.config.ts`), the directing hook and backfill (`scripts/directing_ingest.py`; an
`api_url` in `~/.aindy/directing.json` still wins), and the watcher's sign-in script (`~/.aindy/start-watcher.ps1`).
Unset, all three use `http://127.0.0.1:8000`. The hook sends only to loopback or to a host whose every address is a
Tailscale address. Restart Vite and the watcher, and open a new Claude Code session, after changing it.

## 7. Releasing to a running host

**From CI's image (phase C, since 2026-11-25).** Every merge to `main` publishes
`ghcr.io/masterplanner25/aindy-api:<full sha>` (`.github/workflows/publish-image.yml`; public, so no login). On the
host:

```bash
git pull                                       # compose files and scripts at the commit being deployed
python3 scripts/deploy_stack.py <sha>          # or a ref this clone resolves: HEAD, main, a short sha
```

It keeps the stack's mode (§6, dev mode), pulls first (a failed pull changes nothing), reads the counters, backs up (`--no-backup` to skip), writes
`AINDY_IMAGE=<image>` into `.env`, recreates `api` and `mcp`, waits for healthy, and prints the confirm line and
the rollback command. **A rollback is the same command with the previous sha.** Each deploy appends a line to
`~/aindy-deploys.jsonl`. A runtime pin move still migrates the database at boot: the adoption record is the gate,
and the backup is the way back.

**A host that deploys CI's images does not build.** With `AINDY_IMAGE` set, `$COMPOSE build api` would tag a local
build with the CI image's name. To go back to local builds, delete the `AINDY_IMAGE` line from `.env`.

**A local build** (no `AINDY_IMAGE`; the laptop until it switches):

```bash
git pull
$COMPOSE build api                 # a source change ~1 min; a runtime pin move 10-15 min (OPS-004)
# read the counters (§5)
$COMPOSE up -d api mcp             # recreates both: mcp shares the image
```

On the laptop a build can be killed for memory: stop Vite and drop the Docker VM's page cache first
(`wsl -d docker-desktop sh -c "sync; echo 3 > /proc/sys/vm/drop_caches"`). Pulling CI's image avoids that.

## 8. Tuning for slower / cold-start-heavy hosts

The app profile is heavier than a bare runtime: a full agent run cold-starts the 16-domain stack in a per-execution
Nodus worker, fans out concurrent memory/embedding writes, and holds DB transactions across multi-step execution. The
runtime's *default* limits are too tight for it on a slow host, and the failures look unrelated: `register` hangs,
`Nodus worker exceeded 45000ms hard limit`, `QueuePool limit … reached`. `docker-compose.prod.yml` ships
**env-overridable** defaults:

| Var | Compose default | Runtime default | Guards against |
|---|---|---|---|
| `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` / `DB_STATEMENT_TIMEOUT_MS` | `120000` | `30000` | slow requests getting their connection reaped mid-transaction |
| `AINDY_NODUS_MAX_EXECUTION_MS` / `AINDY_NODUS_BOOT_ALLOWANCE_MS` | `120000` / `60000` | `30000` / `15000` | the per-run cold-start blowing the Nodus budget |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `20` / `40` | `10` / `20` | the embedding fan-out exhausting the pool during execution |
| `AINDY_RUNTIME_CALLBACK_TIMEOUT_SECS` | `90` | `30` | scheduled-job callbacks cold-importing the app in a subprocess, several at once on the hour |

Raise them only if a genuinely slow host still trips a limit. The real fix for a *pathologically* slow datastore
(Docker Desktop on Windows inflates each postgres round trip) is a faster host, not larger limits: bigger pools
against a slow postgres make it worse. Use a native-Linux Docker engine.

## 9. Enabling the Claude planner (BUILD_PLAN Track 2)

By default the agent planner is `runtime_local`, a deterministic, no-egress engine. For Claude to author multi-step
plans, the host needs outbound HTTPS to `api.anthropic.com` (GitHub-hosted runners lack it: RTR-1-NODUS-APPTOOL-500),
`ANTHROPIC_API_KEY` in `.env`, and long-lived containers (continuation is driven by the scheduler `serve` starts).
Then add to `.env`:

```bash
AINDY_AGENT_PLANNER_BACKEND=anthropic_chat
# AINDY_CLAUDE_PLANNER_MODEL=             # optional; the default is valid
```

To verify, dispatch the `serve-run-completion` workflow with `planner_backend=anthropic_chat`: its SDK preflight
checks egress first, then the full loop runs (register → create → approve → execute → `completed`).

## References

- `docs/specs/OFF_LAPTOP_DEPLOYMENT_SPEC.md`: the move, its decisions (§8) and phases.
- `docs/operations/OPERATOR_NOTES.md`: OPS-004 (slow builds), OPS-041 (counters).
- [MIGRATION_POLICY.md](./MIGRATION_POLICY.md): schema and migration discipline.
- `.env.example`: the environment the runtime reads.
- `TECH_DEBT.md`: COMPOSE-REDIS-URL-UNCONDITIONAL-1 (closed), RTR-1-NODUS-APPTOOL-500 (egress).
