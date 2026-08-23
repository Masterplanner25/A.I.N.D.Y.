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
# Runtime schema, branching on bootstrap-schema's exit code (aindy-runtime>=2.3.0, FR-14).
#
#   0  success
#   1  configuration error        — not automatable, fix the environment
#   2  db layer import failure    — not automatable
#   3  additive reconcile needed  — SAFE to automate; --reconcile adds, never drops
#   4  offline migration required — needs a person (wins over 3 when both apply)
#   5  manual repair required     — needs a person
#
# Before 2.3.0 every one of these was exit 1, so an entrypoint could not tell "add two nullable
# columns" from "your database is broken". Under `set -e` + `restart: unless-stopped` that became
# an infinite crash loop, which is what adopting 2.1.0 did here on 2026-08-15 when FR-13 added
# agents.metadata + agents.updated_at.
#
# AINDY_BOOTSTRAP_RECONCILE (default off) still gates whether exit 3 is applied automatically.
# The runtime now certifies 3 as safe to automate, so defaulting it on would be defensible — we
# keep it opt-in so a production schema change stays a decision someone makes rather than a side
# effect of a container restart. What changed is that the *refusal* is now precise: an exit 3 says
# exactly what to do, and 4/5 no longer masquerade as something a flag could fix.
#
# See docs/runtime/RUNTIME_2_3_0_UPGRADE.md and FR-14 in RUNTIME_FEATURE_REQUESTS.md.
echo "[entrypoint] ensure pgvector: python scripts/ensure_pgvector.py"
python scripts/ensure_pgvector.py

_reconcile_opt_in=false
case "$(printf '%s' "${AINDY_BOOTSTRAP_RECONCILE:-}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on) _reconcile_opt_in=true ;;
esac

echo "[entrypoint] runtime schema: aindy-runtime bootstrap-schema"
set +e
aindy-runtime bootstrap-schema
_schema_rc=$?
set -e

case "$_schema_rc" in
  0)
    ;;
  3)
    if [ "$_reconcile_opt_in" = true ]; then
      echo "[entrypoint] exit 3 (additive reconcile required); AINDY_BOOTSTRAP_RECONCILE is set — applying"
      aindy-runtime bootstrap-schema --reconcile
    else
      echo "[entrypoint] bootstrap-schema exit 3: an ADDITIVE reconcile is required." >&2
      echo "[entrypoint] This is the safe-to-automate case — columns/indexes are added, never dropped." >&2
      echo "[entrypoint] Either set AINDY_BOOTSTRAP_RECONCILE=1 and restart, or apply it out-of-band:" >&2
      echo "[entrypoint]   docker compose run --rm --no-deps --entrypoint aindy-runtime api bootstrap-schema --reconcile" >&2
      exit 3
    fi
    ;;
  4)
    echo "[entrypoint] bootstrap-schema exit 4: an OFFLINE MIGRATION is required." >&2
    echo "[entrypoint] Not automatable, and AINDY_BOOTSTRAP_RECONCILE will not help — 4 wins over 3" >&2
    echo "[entrypoint] precisely so an entrypoint never auto-reconciles a database that needs a person." >&2
    exit 4
    ;;
  5)
    echo "[entrypoint] bootstrap-schema exit 5: MANUAL REPAIR required. Not automatable." >&2
    exit 5
    ;;
  *)
    echo "[entrypoint] bootstrap-schema failed with exit $_schema_rc (1=config, 2=db import)." >&2
    echo "[entrypoint] Not a schema-drift case; fix the environment rather than reconciling." >&2
    exit "$_schema_rc"
    ;;
esac
echo "[entrypoint] app schema: python scripts/deploy_bootstrap.py"
python scripts/deploy_bootstrap.py

# Serve. `aindy-runtime serve` binds AINDY_HOST:AINDY_PORT and self-migrates the runtime schema;
# from this repo root it discovers ./aindy_plugins.json -> apps.bootstrap (app profile).
echo "[entrypoint] starting: $*"
exec "$@"
