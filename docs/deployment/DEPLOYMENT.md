---
title: "Server Deployment"
last_verified: "2026-07-15"
api_version: "1.0"
status: current
owner: "apps-team"
---
# Server Deployment

How to deploy the app-profile server (this repo's apps running on top of the
installed `aindy-runtime`). This document belongs to `aindy-apps-monolith`.

## The deploy artifact

The repo ships a self-contained server deploy artifact:

| File | Role |
|---|---|
| `Dockerfile` | Builds the app-profile server image (apps + installed runtime). |
| `docker-compose.prod.yml` | Production-style overlay: `api` + `postgres` (pgvector) + optional `redis`. |
| `docker/entrypoint.sh` | Schema bootstrap by ownership, then `exec` the serving command. |
| `docker/init-pgvector.sql` | Creates the `vector` extension on first Postgres init. |
| `scripts/ensure_pgvector.py` | Idempotent `CREATE EXTENSION IF NOT EXISTS vector` (managed-PG safe). |

### What the entrypoint does

`docker/entrypoint.sh` runs before the server binds, in a clean ownership split:

1. `python scripts/ensure_pgvector.py` — guarantees the pgvector extension exists
   (the runtime's schema build includes a `Vector` embedding column).
2. `aindy-runtime bootstrap-schema` — the **runtime** builds its own tables from
   packaged metadata and stamps `alembic_version_runtime` (aindy-runtime>=1.7.0).
3. `python scripts/deploy_bootstrap.py` — the **app** builds its tables: fresh DB →
   `create_all` + `alembic stamp head`; existing DB → `alembic upgrade head`.
4. `exec aindy-runtime serve` — binds `AINDY_HOST:AINDY_PORT`, discovers
   `./aindy_plugins.json` → `apps.bootstrap` (the 17-app profile), and starts the
   scheduler heartbeat that drives `nodus_vm` continuation.

This split is required: a bare `alembic upgrade head` on a fresh DB would replay the
100+ pre-split revisions at a drifted runtime schema, which the boot guard rejects.
The `deploy-bootstrap-guard` CI workflow regression-locks this ordering.

## Running it

```bash
# From the repo root, with a .env holding the required secrets (see below):
docker compose -f docker-compose.prod.yml up -d

# With the distributed job queue / event bus (adds redis):
EXECUTION_MODE=distributed docker compose -f docker-compose.prod.yml --profile full up -d
```

### Required environment

Set these in your deploy `.env` (see `.env.example` for the full reference — never
commit real values):

| Var | Required | Notes |
|---|---|---|
| `SECRET_KEY` | ✅ | JWT signing key, ≥32 chars. |
| `AINDY_API_KEY` | ✅ | Bearer token for machine-to-machine API calls. |
| `PERMISSION_SECRET` | ✅ | App-layer permission signing key (separate from `SECRET_KEY`). |
| `OPENAI_API_KEY` | ✅ (prod) | Memory embeddings + LLM calls; runtime refuses to boot in prod if unset. |
| `POSTGRES_PASSWORD` | recommended | Overrides the compose default. |
| `MONGO_URL` | optional | Social layer (degradable) — leave unset to run without Mongo. |
| `ANTHROPIC_API_KEY` | optional* | *Required to enable the Claude agent planner — see below. |

`DATABASE_URL` and `REDIS_URL` are wired for you inside `docker-compose.prod.yml`;
override them only for an external/managed datastore.

`AINDY_BOOT_MODE` is defaulted to `app-profile` inside `docker-compose.prod.yml` — this
is what makes the 16 domain apps load. (`aindy-runtime serve` setdefaults it to
`runtime-only`, a platform-only profile with **no** apps, so a bare `serve` outside compose
must set `AINDY_BOOT_MODE=app-profile` explicitly.)

## Enabling the Claude planner (BUILD_PLAN Track 2)

By default the agent planner is `runtime_local` — a deterministic, no-egress engine.
To have **Claude author real multi-step plans**, flip the planner backend. The
mechanism is already proven end-to-end (BUILD_PLAN "Validated foundation"); the only
prerequisite is an environment with model egress.

### Requirements

- **Outbound HTTPS to `api.anthropic.com`.** This is the one thing GitHub-hosted
  runners lack (RTR-1-NODUS-APPTOOL-500), which is why Track 2 is a *deploy*
  concern, not a code one. A self-hosted runner or any cloud Linux box works.
- **`ANTHROPIC_API_KEY`** set in the deploy `.env` (`docker-compose.prod.yml` already
  plumbs it into the `api` service).
- **The `anthropic` SDK** — already a hard dependency of the image (`pyproject.toml`),
  so nothing to install.
- **Stable, long-lived containers** — `nodus_vm` continuation is driven by the
  scheduler heartbeat that `aindy-runtime serve` starts; ephemeral CI runners can't
  provide it. `docker compose` on a persistent host does.

### The flip

Add to your deploy `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...              # your real key
AINDY_AGENT_PLANNER_BACKEND=anthropic_chat
# AINDY_CLAUDE_PLANNER_MODEL=             # optional — pin a model id; default is valid
```

No app code changes — the `anthropic_chat` planner is already registered and
available; this only makes it the default.

### Verifying

Dispatch the `serve-run-completion` workflow (or run the same steps on the host)
with `planner_backend=anthropic_chat`. Its SDK preflight (`client.models.list()`)
checks egress first, so a still-blocked network fails *there*, clearly, instead of as
an opaque create-500. Once it passes, the full loop runs: register → create (**Claude
plans**) → approve → execute → `completed` — the last mile the no-egress
`runtime_local` run cannot cover.

## Tuning for slower / cold-start-heavy hosts

The app profile is heavier than a bare runtime — a full agent run cold-starts the ~17-app
stack in a per-execution Nodus worker, fans out concurrent memory/embedding writes, and
holds DB transactions across multi-step execution. The runtime's *default* limits are tuned
for a bare runtime and are too tight for this profile on a slower host, producing failures
that look unrelated: `register` hangs, executions fail with `Nodus worker exceeded 45000ms
hard limit`, or `QueuePool limit … reached`. `docker-compose.prod.yml` therefore ships more
generous, **env-overridable** defaults for the app profile:

| Var | Compose default | Runtime default | Guards against |
|---|---|---|---|
| `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` / `DB_STATEMENT_TIMEOUT_MS` | `120000` | `30000` | slow requests getting their connection reaped mid-transaction |
| `AINDY_NODUS_MAX_EXECUTION_MS` / `AINDY_NODUS_BOOT_ALLOWANCE_MS` | `120000` / `60000` | `30000` / `15000` | the per-run 17-app cold-start blowing the Nodus budget |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `20` / `40` | `10` / `20` | the embedding fan-out exhausting the pool during execution |

These are floors that let the full run→`completed` loop breathe; raise them further only if a
genuinely slow host still trips a limit. **Note:** the real fix for a *pathologically* slow
datastore (e.g. Docker Desktop on Windows, where each pg round-trip is inflated) is a faster
host, not larger limits — bigger pools against a slow pg make it worse. Use a native-Linux
Docker engine (a Linux box, or `docker-ce` inside a WSL2 distro — **not** Docker Desktop's
VM engine, which WSL integration silently substitutes).

## References

- [BUILD_PLAN.md](../architecture/BUILD_PLAN.md) — Track 2 and the validated foundation.
- `.env.example` — full environment variable reference.
- [MIGRATION_POLICY.md](./MIGRATION_POLICY.md) — schema/migration discipline.
- `TECH_DEBT.md` — RTR-1-NODUS-APPTOOL-500 (egress), APP-DEPLOY-1 (closed).
