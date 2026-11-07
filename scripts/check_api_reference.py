#!/usr/bin/env python3
"""
check_api_reference.py

Drift guard for ``docs/api/API_REFERENCE.md``.

Boots the app-profile server, dumps its OpenAPI schema, and asserts that the
**app-owned** HTTP surface — every ``/apps/*`` route — is documented exactly:
no routes missing from the doc, no stale routes left in the doc.

Runtime-owned routes (``/platform/*``, ``/auth``, ``/health``, ``/``, ...) live
in the ``aindy-runtime`` repo; the reference keeps a curated inventory of them
for convenience, so they are intentionally **not** enforced here.

Usage:
  python scripts/check_api_reference.py
  python scripts/check_api_reference.py --warn-only
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "api" / "API_REFERENCE.md"
HTTP_METHODS = {"get", "post", "put", "delete", "patch"}
ENTRY_RE = re.compile(r"^#### (GET|POST|PUT|DELETE|PATCH) (\S+)", re.MULTILINE)
APP_PREFIX = "/apps/"


def _live_app_routes() -> set[tuple[str, str]]:
    """Boot the app-profile server and return its ``/apps/*`` (method, path) pairs."""
    # Self-contained boot env so the check runs identically in CI and locally.
    # setdefault lets a caller (e.g. the CI job) override the datastore config.
    # The runtime's legacy-root mounts are forced on so they are compared too. (RippleTrace's
    # own legacy compatibility surface was retired 2026-11-07 and is no longer documented.)
    for key, value in {
        "DATABASE_URL": "sqlite://",
        "AINDY_ALLOW_SQLITE": "1",
        "MONGO_URL": "",
        "OPENAI_API_KEY": "sk-test-placeholder",
        "DEEPSEEK_API_KEY": "ds-test-placeholder",
        "SECRET_KEY": "apps-apiref-secret",
        "AINDY_API_KEY": "apps-apiref-api-key",
        "PERMISSION_SECRET": "apps-apiref-permission-secret",
        "AINDY_SKIP_MONGO_PING": "1",
        "SKIP_MONGO_PING": "1",
    }.items():
        os.environ.setdefault(key, value)
    os.environ["AINDY_ENABLE_LEGACY_SURFACE"] = "true"

    from fastapi.testclient import TestClient
    import AINDY.main as main

    spec = TestClient(main.app, raise_server_exceptions=False).get("/openapi.json").json()

    routes: set[tuple[str, str]] = set()
    for path, methods in spec.get("paths", {}).items():
        if not path.startswith(APP_PREFIX):
            continue
        for method in methods:
            if method.lower() in HTTP_METHODS:
                routes.add((method.upper(), path))
    return routes


def _documented_app_routes() -> set[tuple[str, str]]:
    text = DOC_PATH.read_text(encoding="utf-8")
    return {(m, p) for m, p in ENTRY_RE.findall(text) if p.startswith(APP_PREFIX)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify docs/api/API_REFERENCE.md matches the live /apps/* route tree."
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Report drift without failing the process.",
    )
    args = parser.parse_args(argv)

    live = _live_app_routes()
    documented = _documented_app_routes()
    missing = sorted(live - documented)  # in live code, absent from the doc
    stale = sorted(documented - live)  # in the doc, absent from live code

    if not missing and not stale:
        print(f"API_REFERENCE.md OK — {len(live)} app routes documented, 0 drift.")
        return 0

    if missing:
        print(f"MISSING from docs/api/API_REFERENCE.md ({len(missing)}):")
        for method, path in missing:
            print(f"  + {method:6} {path}")
    if stale:
        print(f"STALE in docs/api/API_REFERENCE.md ({len(stale)}):")
        for method, path in stale:
            print(f"  - {method:6} {path}")
    print()
    print("Reconcile docs/api/API_REFERENCE.md with the live /apps/* surface, then bump last_verified.")
    return 0 if args.warn_only else 1


if __name__ == "__main__":
    sys.exit(main())
