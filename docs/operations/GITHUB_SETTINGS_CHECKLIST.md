---
title: "Apps GitHub Settings Checklist"
last_verified: "2026-05-17"
api_version: "1.0"
status: current
owner: "platform-team"
---
# Apps GitHub Settings Checklist

This document lists the manual GitHub UI settings that should be configured for
A.I.N.D.Y..

These settings are not stored in git and must be recreated in GitHub after the
repo split.

## Branch Baseline

Recommended baseline:

- default branch: `main`
- protect branch: `main`

The current apps workflow is designed around `push` and `pull_request` events
on `main`.

## Recommended Branch Protection

In GitHub:

- Settings -> Branches -> Add branch protection rule
- branch name pattern: `main`

Recommended protections:

- require a pull request before merging: enabled
- required approvals: `1`
- dismiss stale pull request approvals when new commits are pushed: enabled
- require conversation resolution before merging: enabled
- require status checks to pass before merging: enabled
- restrict direct pushes to `main`: enabled

Recommended required status checks:

- `App Docs And Contract Checks`
- `App Contracts`
- `Frontend Unit Tests`
- `Frontend Build And Container Smoke`

Do **not** require any check that does not currently exist in
`.github/workflows/app-ci.yml`.

In particular, do **not** assume there is a default blocking Playwright job yet.

## Merge Policy

Recommended:

- allow squash merge: enabled
- allow merge commit: disabled
- allow rebase merge: optional, team preference

Reasoning:

- squash merge keeps app/bootstrap/frontend history easier to review
- merge commits are not required by the current apps repo workflow design

## Optional Stronger Settings

These are reasonable if the team wants stricter governance:

- require linear history: enabled
- require signed commits: enabled if the team already uses signed commits
- allow auto-merge: enabled
- automatically delete head branches: enabled
- require approval of the most recent reviewable push: enabled

Only enable these if they match how the team actually works.

## Actions / Workflow Settings

Recommended GitHub repo settings:

- GitHub Actions: enabled
- workflow permissions: read repository contents unless a future workflow needs
  write access
- fork pull request approval policy: set according to org policy

## Runtime Install Note

App CI installs `aindy-runtime` from PyPI as a normal pinned dependency, so no
runtime-checkout repository variable or secret is required. The former
`AINDY_RUNTIME_REPO` / `AINDY_RUNTIME_CHECKOUT_TOKEN` config (for the
pre-publication source checkout) is no longer used and can be removed if set.

## First-Run Note

GitHub only lets branch protection require status checks that have already run
at least once on the repository.

Recommended sequence:

1. push `.github/workflows/app-ci.yml` to `main`
2. let the workflow run successfully at least once
3. configure the required status checks listed above
