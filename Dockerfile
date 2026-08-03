# syntax=docker/dockerfile:1
# Server image for aindy-apps-monolith — the app profile *consuming* the published
# aindy-runtime framework.
#
# This is deliberately NOT a combined runtime+apps image. It installs the runtime as a
# pinned PyPI dependency (see pyproject.toml: aindy-runtime>=1.7.0,<2.0) and adds the
# app-profile deployment inputs this repo owns: the plugin manifest (aindy_plugins.json),
# the app bootstrap package (apps/), and the app-owned Alembic tree. At startup the runtime
# discovers ./aindy_plugins.json -> apps.bootstrap, which registers the 16 domain apps into
# the runtime via the plugin ABI.
#
# Shape follows the runtime's own `aindy-runtime init` scaffold (libpq-dev, AINDY_HOST=0.0.0.0,
# `aindy-runtime serve`), extended to install this app package so the runtime boots app-profile.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AINDY_HOST=0.0.0.0 \
    AINDY_PORT=8000

# libpq + toolchain: aindy-runtime pins psycopg2 (source build) and may pull sdists.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the app package first (this resolves and installs the pinned aindy-runtime and the
# rest of the dependency tree from PyPI). Layer-cached on source-only changes.
COPY pyproject.toml README.md ./
COPY apps ./apps
#
# The pip cache is a BuildKit cache mount, NOT an image layer: wheels survive between
# builds (so an interrupted or retried build resumes instead of re-downloading the whole
# tree) while staying out of the shipped image, which is what PIP_NO_CACHE_DIR=1 above is
# for. That env is overridden inline here — without the cache this single layer re-fetches
# every dependency from PyPI on each attempt, which on a slow link is the difference
# between a build that finishes and one that never does.
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    PIP_NO_CACHE_DIR=0 python -m pip install --upgrade pip \
 && PIP_NO_CACHE_DIR=0 python -m pip install .

# App-profile deployment inputs owned by this repo. The working directory must be the repo
# root so the runtime discovers aindy_plugins.json, and so Alembic finds alembic.ini
# (script_location = alembic/alembic).
COPY aindy_plugins.json alembic.ini ./
COPY alembic ./alembic
COPY scripts/ensure_pgvector.py scripts/deploy_bootstrap.py ./scripts/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000

# entrypoint applies the app Alembic head, then execs `aindy-runtime serve` (the runtime's
# HTTP server; binds AINDY_HOST:AINDY_PORT and self-migrates the runtime schema at boot).
# Run from this repo root so serve boots the app profile via ./aindy_plugins.json.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["aindy-runtime", "serve"]
