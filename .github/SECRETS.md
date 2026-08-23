# Apps Repo Secrets

This document defines the secrets and configuration expectations for
A.I.N.D.Y..

Use it for:

- GitHub Actions configuration in this repo
- app-profile deployment environment setup
- frontend/app deployment ownership boundaries

## GitHub Actions In This Repo

Current workflow:

- `.github/workflows/app-ci.yml`

### Secrets Required For CI

App CI uses safe placeholder values in workflow `env` for:

- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `SECRET_KEY`
- `PERMISSION_SECRET`
- `AINDY_API_KEY`
- `DATABASE_URL`
- `MONGO_URL`

These are intentionally mocked or local-only in CI:

- no real OpenAI or DeepSeek key is required for the current default CI path
- SQLite in-memory is used for Python smoke and app-profile tests
- frontend build smoke uses a placeholder `VITE_API_BASE_URL`

### Runtime Install (No Secret Required)

App CI installs `aindy-runtime` from PyPI as a normal pinned dependency
(`aindy-runtime>=1.9.0,<2.0`), so **no runtime-checkout secret or variable is
needed**. The previously-used `AINDY_RUNTIME_REPO` / `AINDY_RUNTIME_CHECKOUT_TOKEN`
config was for the pre-publication source-checkout strategy and is no longer
referenced by the workflow (`PYPI-PUBLISH-1` is closed).

## App Deployment Secrets

These are app-owned deployment environment requirements, not GitHub Actions
requirements.

App-profile deployments typically need:

- `SECRET_KEY`
- `PERMISSION_SECRET`
- `AINDY_API_KEY`
- `DATABASE_URL`
- `ALLOWED_ORIGINS`

App-owned startup inputs:

- repo-root `aindy_plugins.json`
- `apps.bootstrap`

App-specific or feature-specific values may also be required depending on the
enabled app surface. Example:

- `STRIPE_WEBHOOK_SECRET`
  - needed for `apps.freelance.bootstrap` payment/webhook automation

If the deployed app profile uses runtime/provider-backed features, it also
depends on runtime-side env such as:

- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `MONGO_URL`

Those are listed here only because app-profile deployments run on top of the
runtime package, not because this repo owns the runtime contract itself.

## Safe Placeholder Guidance

Placeholder values such as:

- `sk-test-placeholder`
- `ds-test-placeholder`
- `ci-apps-secret-key`
- `https://ci-placeholder.aindy.dev`

are acceptable in CI only because:

- provider calls are not exercised as real external integrations
- the workflow validates app/profile wiring, not production credentials
- frontend build smoke only needs a syntactically valid API base URL

Do not reuse CI placeholder values in deployed environments.
