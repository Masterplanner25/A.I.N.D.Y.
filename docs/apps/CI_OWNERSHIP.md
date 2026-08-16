---
title: "Apps CI Ownership"
last_verified: "2026-05-17"
api_version: "1.0"
status: current
owner: "platform-team"
---
# Apps CI Ownership

This document defines which GitHub Actions checks are authoritative for
`aindy-apps-monolith`.

## Authoritative Apps Checks

Primary workflow:

- `.github/workflows/app-ci.yml`

These checks are app-owned and should live in `aindy-apps-monolith`:

- explicit runtime dependency installation for CI
- app-profile `/api/version` smoke validation on top of installed runtime
- cross-app import boundary checks
- bootstrap dependency validation for `apps/`
- docs frontmatter lint and API contract drift checks for app-owned/shared docs
- extracted app-profile pytest coverage for `tests -m app_profile`
- frontend unit tests
- frontend production build smoke
- client container build smoke from `client/Dockerfile`

## Runtime Install Strategy

`aindy-runtime` is published on PyPI, so app CI installs it as a normal pinned
dependency (`pip install -e .[test]`) and verifies the installed version at boot.
No runtime-repo checkout or source install is involved.

The dependency contract is:

- `aindy-runtime>=2.3.0,<3.0`

(The earlier source-checkout CI strategy was a pre-publication staging step and is
no longer used; `PYPI-PUBLISH-1` is closed.)

## Checks That Do Not Belong Here

These are not app-owned and should not move back into `aindy-apps-monolith` CI:

- runtime-only import-boundary guards against `apps.*`
- runtime package build and `twine check`
- runtime-only pytest
- runtime docs ownership validation
- runtime release-staging artifact workflow

## Historical Monolith Checks

The archived combined repo previously bundled some of the following together:

- runtime-only checks
- app-profile checks
- frontend tests
- monolith Docker build
- broader multi-service integration and infra-matrix validation

Only the app-owned subset is authoritative here now.

## Current Gaps

Remaining gaps in apps CI are intentional or still deferred:

- Playwright E2E is not part of the default push/PR workflow yet
- strict frontend lint is not yet a passing gate for the current client tree
- no separate app-owned backend service-matrix job with Redis/PostgreSQL/Mongo
  in the extracted repo workflow yet

Those can be added later if they become stable, repo-owned checks rather than
monolith-era integration carryover.
