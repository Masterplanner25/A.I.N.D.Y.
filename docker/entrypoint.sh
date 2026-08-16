#!/usr/bin/env sh
# Container entrypoint for the aindy-apps-monolith server image.
# Bootstraps schema by OWNERSHIP, then execs the serving command (CMD = `aindy-runtime serve`).
#
# Two Alembic version lines back a deployed app-profile database, each owned by its side:
#   - alembic_version_runtime : runtime-owned tables. Built + stamped by the runtime's own
#                               `aindy-runtime bootstrap-schema` command (aindy-runtime>=1.7.0).
#   - alembic_version         : app-owned tables (this repo's alembic/alembic).
set -e

# Optional runtime pre-serve hook (runs before schema bootstrap).
if [ -n "${PRE_SERVE_CMD}" ]; then
  echo "[entrypoint] pre-serve: ${PRE_SERVE_CMD}"
  sh -c "${PRE_SERVE_CMD}"
fi

# Schema bootstrap (APP-DEPLOY-1) — clean ownership split:
#   1. Runtime builds ITS tables from packaged metadata and stamps alembic_version_runtime,
#      so `aindy-runtime serve`'s startup guard accepts the schema and a later runtime schema
#      upgrade has a baseline. Idempotent (safe on existing DBs; back-fills the runtime baseline
#      on DBs first built by the older app-side create_all-only path).
#   2. App builds ITS tables: fresh DB -> create_all (runtime tables already exist, skipped) +
#      `alembic stamp head`; existing DB -> `alembic upgrade head`. See scripts/deploy_bootstrap.py.
# A bare `alembic upgrade head` on a FRESH DB would replay the 100+ pre-split revisions that build
# the runtime-owned tables at a drifted schema, which the guard rejects — hence this split.
# pgvector must exist before bootstrap-schema (it builds a Vector embedding column and assumes
# the extension is present). compose.prod provisions it via docker/init-pgvector.sql; this makes
# the image self-sufficient where that init hook can't run. Checks-first (safe on managed PG).
#
# AINDY_BOOTSTRAP_RECONCILE (default off) — opt in to additive column/index reconciles.
#
# Bare `bootstrap-schema` REFUSES to alter an existing runtime table and exits non-zero. That is
# correct for production (a deploy should not silently ALTER TABLE), but with `set -e` and
# `restart: unless-stopped` the refusal becomes an infinite crash loop rather than a visible
# failure — which is exactly what adopting aindy-runtime 2.1.0 did here on 2026-08-15, when
# FR-13 added agents.metadata + agents.updated_at:
#
#   error: runtime-owned schema is not ready: Runtime-owned schema requires an explicit additive
#   reconcile: Runtime table 'agents' is missing required column 'metadata'. ...
#
# Set this to 1/true where an unattended additive upgrade is preferable to a stopped stack (local
# and dev). Leave it UNSET in production, so a schema change is a decision someone makes rather
# than a side effect of a container restart. See docs/handoffs/RUNTIME_2_1_0_UPGRADE.md §1a/§7
# and FR-14 in docs/handoffs/RUNTIME_FEATURE_REQUESTS.md.
echo "[entrypoint] ensure pgvector: python scripts/ensure_pgvector.py"
python scripts/ensure_pgvector.py
case "$(printf '%s' "${AINDY_BOOTSTRAP_RECONCILE:-}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    echo "[entrypoint] runtime schema: aindy-runtime bootstrap-schema --reconcile (AINDY_BOOTSTRAP_RECONCILE set)"
    aindy-runtime bootstrap-schema --reconcile
    ;;
  *)
    echo "[entrypoint] runtime schema: aindy-runtime bootstrap-schema"
    if ! aindy-runtime bootstrap-schema; then
      echo "[entrypoint] bootstrap-schema refused. If this is an additive runtime schema change," >&2
      echo "[entrypoint] re-run once with AINDY_BOOTSTRAP_RECONCILE=1, or apply the reconcile" >&2
      echo "[entrypoint] out-of-band:" >&2
      echo "[entrypoint]   docker compose run --rm --no-deps --entrypoint aindy-runtime api bootstrap-schema --reconcile" >&2
      exit 1
    fi
    ;;
esac
echo "[entrypoint] app schema: python scripts/deploy_bootstrap.py"
python scripts/deploy_bootstrap.py

# Serve. `aindy-runtime serve` binds AINDY_HOST:AINDY_PORT and self-migrates the runtime schema;
# from this repo root it discovers ./aindy_plugins.json -> apps.bootstrap (app profile).
echo "[entrypoint] starting: $*"
exec "$@"
