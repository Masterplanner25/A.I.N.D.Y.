---
title: "Governance Index (apps-monolith)"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# Governance Index

Authoritative registry of documentation scope and authority for
A.I.N.D.Y.. Defines the doc hierarchy, change protocol, and agent
obligations for this repo. Authored fresh during DOCS-MIGRATION-2 (the pre-split
monolith index was monolith-centric and referenced runtime-owned docs this repo
does not own).

This repo owns app domain code (`apps/<domain>/...`), the React client
(`client/`), the app plugin manifest, app-owned migrations, and the app docs
below. It does **not** own `AINDY/` — runtime contracts are *referenced* upstream
authority, not redefined here. See
[docs/runtime/RUNTIME_DEPENDENCY.md](./runtime/RUNTIME_DEPENDENCY.md) and the runtime repo's
`docs/runtime/RUNTIME_DOCSET_BOUNDARY.md`.

## 0. Directory Map

Restructured **2026-08-22**. Directories are named for **what a document is**, not for which
pre-split team owned it. `docs/apps/`, `docs/deployment/` and `docs/platform/` were retired:
the first was a catch-all, and the other two were named after things they did not contain —
`docs/platform/` held no platform-layer docs at all, only three app-owned files inherited from
the old monolith's directory skeleton.

| Directory | Holds | Note |
|---|---|---|
| `docs/architecture/` | how the system is built | plugin registry, boot profiles, coupling, public surfaces, roadmap |
| `docs/infinity/` | the algorithm | 8 docs that were split across two directories, for the thing the README calls the point of the product |
| `docs/domains/` | one guide per domain app | |
| `docs/api/` | the HTTP surface | `API_REFERENCE` (app `/apps/*`, CI-guarded) + `API_CONTRACTS` (route→owner inventory) |
| `docs/runtime/` | **the seam with `aindy-runtime`** | dependency contract, the feature-request register, upgrade notes. This repo does not own the runtime; it owns how it consumes it |
| `docs/operations/` | running and shipping it | deploy, migrations, CI, testing, invariants, settings |
| `docs/specs/` | forward specs, not yet built | |
| `docs/verification/` | what we checked and what broke | walk log, soak audit, defect write-ups |
| `docs/archive/` | dated, retired, kept for provenance | `status: outdated`; never retro-edited |
| *(root)* `SESSION_HANDOFF.md` | the single rolling handoff | the owner's local working notes, gitignored — **not** repo documentation. Consolidated 2026-08-22 from four files; `docs/handoffs/` no longer exists. Anything durable belongs in a tracked document instead |

**Every directory above is frontmatter-linted** by `scripts/lint_docs.py` (the root
`SESSION_HANDOFF.md` is not — it is gitignored working notes, not documentation). Before this restructure the linter named five directories that have
never existed in this repo and skipped the two largest real ones, so 44 of 65 documents were
never checked — including the runtime feature-request register and every spec.

---

## 1. Documentation Hierarchy

### Level 0 — Upstream runtime authority (referenced, owned by `aindy-runtime`)
App code and docs must conform to these and must not contradict or redefine them:
- Runtime Public API Contract — the only `AINDY.*` surface apps may import.
- Runtime DB Ownership Contract — runtime-owned vs app-owned tables/migrations.
- `RUNTIME_DOCSET_BOUNDARY.md` — the doc ownership map between the two repos.
- Runtime governance docs relocated upstream (DOCS-MIGRATION-2 Bucket A, shipped with
  aindy-runtime 1.8.0 / FR-4): `ERROR_HANDLING_POLICY`, `AGENT_WORKING_RULES`,
  `DATA_MODEL_MAP`, `MODEL_OWNERSHIP_POLICY`, the four runtime `tutorials/*`, and the
  runtime half of `INVARIANTS.md`. App docs reference these; they are not vendored here.

### Level 1 — Repo operating instructions
- `CLAUDE.md` (repo root) — conventions, commands, and boundary rules that
  **override default agent behavior**. First read before any change.

### Level 2 — Architecture & integration contract (app-owned)
- `docs/operations/INVARIANTS.md` — app-domain invariants (non-negotiable
  constraints enforced by `apps/`); runtime invariants are owned by `aindy-runtime`.
- `docs/architecture/ARCHITECTURE_MAP.md` — app architecture overview.
- `docs/architecture/PLUGIN_REGISTRY_PATTERN.md` — runtime↔app registration contract.
- `docs/architecture/BOOT_PROFILES.md` — boot profiles and manifest selection.
- `docs/architecture/CROSS_DOMAIN_COUPLING.md` — cross-domain dependency rules.
- `docs/archive/APPS_MONOLITH_REPO_SHAPE.md` — target repo shape.
- `docs/runtime/RUNTIME_DEPENDENCY.md` — runtime dependency contract.
- `docs/operations/CLIENT_OWNERSHIP.md` — frontend ownership.

### Level 3 — Public surface & interface authority (app-owned)
- `docs/architecture/PUBLIC_SURFACE_CONTRACTS.md` — cross-domain public surfaces.
- `docs/architecture/PUBLIC_SURFACE_AUDIT.md`, `PUBLIC_SURFACE_MIGRATION_GUIDE.md`.
- `docs/api/API_CONTRACTS.md` — HTTP route inventory
  (validated by `scripts/check_api_contracts.py`).
- `docs/api/API_REFERENCE.md` (app-owned `/apps/*` coverage guarded by
  `scripts/check_api_reference.py`), `CHANGELOG.md` (repo root) — app REST surface + history.
- `docs/architecture/ANALYTICS_BOUNDARY.md` — analytics ownership boundary.
- `docs/architecture/USER_ID_AUDIT.md` — per-user scoping audit.

### Level 4 — Engineering & collaboration
- `docs/operations/TESTING_STRATEGY.md`
- `docs/operations/MIGRATION_POLICY.md`, `docs/operations/DEPLOYMENT.md` — schema/migration discipline + server deploy walkthrough.
- `docs/operations/CI_OWNERSHIP.md`, `docs/operations/GITHUB_SETTINGS_CHECKLIST.md`
- `docs/verification/IMPLEMENTATION_DOCS_AUDIT.md`

### Level 5 — Evolution, risk & domain guides
- `TECH_DEBT.md` (repo root) — debt register.
- `docs/architecture/EVOLUTION_PLAN.md` — phased app evolution roadmap.
- `LIVE_VERIFICATION_SCOPE.md` — live-stack verification scope.
- Domain guides under `docs/domains/`: `AUTONOMOUS_REASONING_MODULE`, `FREELANCING_SYSTEM`,
  `MASTERPLAN_SAAS`, `RIPPLETRACE`, `SEARCH_SYSTEM`, `SOCIAL_LAYER`.
- The algorithm under `docs/infinity/` — see §0.
- Forward specs under `docs/specs/`; verification records under `docs/verification/`.

## 2. Authority Rules
- Upstream runtime contracts (Level 0) are authoritative; app docs may depend on
  them but must not redefine runtime ownership or imply app bootstrap is part of
  the runtime baseline.
- `CLAUDE.md` overrides default agent behavior within this repo.
- Import-boundary rules are **hard constraints**, enforced by CI:
  `AINDY/` must never import `apps.*`; apps reach `AINDY.*` only through declared
  public contracts; cross-app imports must be declared in `APP_DEPENDS_ON`. See
  `scripts/check_app_imports.py` and `tests/unit/test_import_boundaries.py`.
- No lower-level document may contradict a higher-level one. Conflict order:
  Level 0 → CLAUDE.md → architecture → interface → domain.

## 3. Change Protocol
A structural change must update the docs it affects, in the same change:
- App architecture change → `docs/architecture/ARCHITECTURE_MAP.md`.
- Registration/bootstrap change → `docs/architecture/PLUGIN_REGISTRY_PATTERN.md`.
- New/changed cross-domain coupling → `docs/architecture/CROSS_DOMAIN_COUPLING.md`
  and `PUBLIC_SURFACE_CONTRACTS.md`.
- Route behavior change → `docs/api/API_CONTRACTS.md`,
  `docs/api/API_REFERENCE.md`, and `CHANGELOG.md` (breaking/additive).
- Schema/migration discipline change → `docs/operations/MIGRATION_POLICY.md`.
- Deploy artifact / serve-time env change → `docs/operations/DEPLOYMENT.md`.
- Test/validation discipline change → `docs/operations/TESTING_STRATEGY.md`.
- New deferred risk → `TECH_DEBT.md`.

## 4. Agent Interaction Protocol
AI agents working in this repo must:
- Read `CLAUDE.md` first; treat its instructions as overriding defaults.
- Treat the import-boundary rules (§2) as hard constraints and run
  `python scripts/check_app_imports.py` before proposing a PR.
- Consult the relevant domain guide before changing a domain's behavior.
- Treat `AINDY.*` as runtime-owned: import only documented public contracts;
  never add `apps.*` imports to runtime code.
- Verify claims on Linux CI — green local Windows runs do not prove integration.

## 5. Governance Stability Principle
- Documentation must reflect implementation reality.
- Docs are updated before or alongside the code change, not after.
- Documentation drift is technical debt and belongs in `TECH_DEBT.md`.

## 6. Entry Point
This file is the first document to read before architectural or cross-domain
modifications. For runtime behavior, defer to the runtime repo's authority docs.

## 7. Docs Changes Checklist
- Update `last_verified` in any doc you materially change.
- Ensure the change does not contradict a higher-level authority.
- Apply the §3 Change Protocol to related docs.
- For a new doc, add it to the appropriate Level above.

## 8. Doc Ownership
- Governance documents require explicit human sign-off by the project owner or
  designated maintainer.
- Designated maintainer: Shawn Knight.

## 9. Out of Scope (owned elsewhere)
- Runtime behavior, execution/retry semantics, memory bridge, syscalls,
  invariants, deployment model → `aindy-runtime` (`docs/runtime/`).
- The app evolution roadmap lives at `docs/architecture/EVOLUTION_PLAN.md`
  (Level 5). Its Phase 1–4 runtime/platform hardening is owned upstream by
  `aindy-runtime` and retained there only as historical context.
