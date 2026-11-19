"""Ensure the pgvector `vector` extension exists BEFORE schema bootstrap.

The runtime's `aindy-runtime bootstrap-schema` builds runtime-owned tables that include a
`Vector` embedding column (AINDY.memory.memory_persistence) and ASSUMES the extension is
already present — the runtime's own deploy scaffold provisions it by mounting
`docker/init-pgvector.sql` into the pgvector container's docker-entrypoint-initdb.d
(docker-compose.prod.yml does this). This script makes the flow self-sufficient where that
init hook can't run (e.g. a Postgres *service* in CI, or a re-used volume), and orders the
extension before bootstrap-schema in the entrypoint.

Checks first so it is safe on a managed Postgres where the extension is pre-provisioned by an
admin and the app role lacks CREATE privilege: it only issues CREATE EXTENSION when absent.
Idempotent. Requires DATABASE_URL.
"""
import os

from AINDY.config import normalize_database_url
from sqlalchemy import create_engine, text

url = (os.environ.get("DATABASE_URL") or "").strip()
if not url or url.startswith("sqlite"):
    raise SystemExit(f"[ensure_pgvector] DATABASE_URL must be a Postgres URL, got {url!r}")

with create_engine(normalize_database_url(url)).begin() as conn:
    present = conn.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if present:
        print("[ensure_pgvector] extension 'vector' already present")
    else:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        print("[ensure_pgvector] created extension 'vector'")
