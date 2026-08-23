---
title: "Invariants (app-owned)"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# Invariants

The **app-owned half** of the system invariants, extracted from the pre-split
monolith `INVARIANTS.md` during DOCS-MIGRATION-2 (that doc was mixed). These are
invariants enforced by **app-domain code** (`apps/<domain>/...`). Section numbers
in parentheses trace back to the original combined document.

**Runtime/platform invariants are owned and documented by `aindy-runtime`**, not
here — including: PostgreSQL `DATABASE_URL` requirement, UTC timezone on DB
connections, background-lease aware-UTC timestamps, required `SystemEvent`
fail-closed emission, per-request session isolation (`get_db`), the memory-graph
constraints (link uniqueness/self-reference/FKs, node UUID defaults, updated-at
trigger, full-text indexing, `node_type` enforcement), asynchronous embedding
write safety, and the startup schema-drift guard. App code depends on those but
must not redefine them.

The runtime half is now **authored upstream** in the `aindy-runtime` docset (shipped
with aindy-runtime 1.8.0, closing the DOCS-MIGRATION-2 / FR-4 handoff); see the doc
ownership map `RUNTIME_DOCSET_BOUNDARY.md` in that repo for its location. This file
remains the app-owned half; section numbers stay in lockstep with the runtime half for
traceability.

---

## Masterplan & Genesis

### (8) Single Active MasterPlan on Activation
- Activating a masterplan deactivates all other plans.
- Enforcement: `apps/masterplan/flows/masterplan_flows.py: masterplan_activate_node` (the
  `masterplan_activate` flow) and `apps/masterplan/services/genesis_service.py: activate_masterplan_genesis`
  — both run `db.query(MasterPlan).filter(MasterPlan.user_id == user_id).update({"is_active": False})`
  before setting the selected plan active. The `activate_masterplan` route handlers delegate to these.
- Violation: multiple masterplans active simultaneously.
- Type: Application-enforced.

### (9) Genesis Session Locking
- A genesis session with status `locked` cannot be re-locked or used to create another masterplan.
- Enforcement: `apps/masterplan/services/masterplan_factory.py: create_masterplan_from_genesis`
  raises `Exception("Session already locked")` if `session.status == "locked"`.
- Violation: multiple masterplans derived from the same locked session.
- Type: Application-enforced. **Note:** this is enforced only in application logic; the
  schema-level lock invariant is a tracked gap — see `TECH_DEBT.md` **APP-DEBT-MIGRATED-1a**.

### (24) Genesis Session `synthesis_ready` Gate Before Lock
- `create_masterplan_from_genesis()` refuses to lock a session unless `session.synthesis_ready` is `True`.
- Enforcement: `apps/masterplan/services/masterplan_factory.py` raises
  `ValueError("Session is not synthesis-ready …")`; callers (`POST /genesis/lock`,
  `POST /masterplans/lock`) catch it and return HTTP 422.
- Violation: MasterPlans created from un-synthesized sessions (no proper draft).
- Type: Application-enforced.

### (25) Audit Endpoint Requires Persisted Draft
- `POST /genesis/audit` runs only when the session has a non-null `draft_json`.
- Enforcement: `apps/masterplan/routes/genesis_router.py: audit_genesis_draft` checks
  `if not session.draft_json` and raises HTTP 422 before `validate_draft_integrity()`.
- Violation: audit called with an empty draft.
- Type: Application-enforced.

### (26) Atomic MasterPlan Creation — Rollback on Failure
- All DB writes inside `create_masterplan_from_genesis()` are wrapped in try/except;
  any exception triggers `db.rollback()` before re-raise.
- Enforcement: `apps/masterplan/services/masterplan_factory.py: create_masterplan_from_genesis`.
- Violation: partial DB state (plan inserted but session status not updated, or vice versa).
- Type: Application-enforced.

### (11a) MasterPlan Required Non-Null Columns
- `apps/masterplan/masterplan.py`: `start_date`, `duration_years`, `target_date` are `nullable=False`.
- Type: DB-enforced.

## Analytics

### (10) Canonical Metrics Uniqueness per Period Scope
- `canonical_metrics` is unique across masterplan and period-scope dimensions.
- Enforcement: `apps/analytics/metrics_models.py: CanonicalMetricDB.__table_args__`
  (`UniqueConstraint(..., name="uq_canonical_period_scope")`) + app-owned migration.
- Violation: duplicate metric rows for the same scope/period.
- Type: DB-enforced.

## RippleTrace

### (19) DropPoint Presence Before Ping Creation
- Ripple-event logging creates a DropPoint if the referenced `drop_point_id` does not exist.
- Enforcement: `apps/rippletrace/services/rippletrace_services.py: log_ripple_event` inserts the
  DropPoint before Ping creation.
- Violation: Ping insertion fails on FK constraint.
- Type: Application-enforced.

## Freelance

### (11b) Freelance Required Non-Null Columns
- `apps/freelance/models/freelance.py`: `client_name`, `client_email`, `service_type`, `price`
  are `nullable=False`.
- Type: DB-enforced.

## Cross-domain Security (app route surfaces)

The **protected surfaces** below are app-owned routers; the **enforcement
mechanism** (`get_current_user`, `verify_api_key`, the SlowAPI `Limiter`) is
runtime-owned in `aindy-runtime` (`AINDY/auth/...`). App routers opt in via
router-level dependencies/decorators.

### (21) JWT Authentication on Protected Route Groups
- All user-facing app route groups require a valid JWT Bearer token via router-level
  `dependencies=[Depends(get_current_user)]`; requests without/with invalid tokens get HTTP 401
  before the route body runs.
- App route groups: `apps/tasks/routes/task_router.py`, `apps/search/routes/leadgen_router.py`,
  `apps/masterplan/routes/genesis_router.py`, `apps/analytics/routes/analytics_router.py`,
  `apps/search/routes/seo_routes.py`, `apps/authorship/routes/authorship_router.py`,
  `apps/arm/routes/arm_router.py`, `apps/rippletrace/routes/rippletrace_router.py`,
  `apps/freelance/routes/freelance_router.py`, `apps/search/routes/research_results_router.py`,
  `apps/dashboard/routes/dashboard_router.py`, `apps/social/routes/social_router.py`.
- Public exceptions: auth routes, health routes, bridge routes.
- Type: Application-enforced (runtime auth layer).

### (22) API Key Authentication on Service-to-Service Routes
- Internal service-to-service app routes require a valid `X-API-Key` matching `AINDY_API_KEY`.
- App surface: `apps/network_bridge/routes/network_bridge_router.py` (`/network_bridge/*`).
  (The runtime also protects its own `/db/verify` surface this way.)
- Type: Application-enforced (runtime auth layer).

### (23) Rate Limiting on AI/Expensive App Endpoints
- App endpoints that invoke external AI providers are per-IP rate-limited (SlowAPI):
  `POST /leadgen/` (10/min), `POST /genesis/message` (20/min), `POST /genesis/synthesize` (5/min),
  `POST /genesis/audit` (5/min), `POST /arm/analyze` (10/min), `POST /arm/generate` (10/min).
- Enforcement: `@limiter.limit(...)` on the app route functions; shared `Limiter` is runtime-owned.
- Violation: unconstrained callers can exhaust provider quotas and incur unbounded cost.
- Type: Application-enforced (runtime rate limiter).

## Cross-boundary Note

### (15) Author System Identity Seeding
- A record with id `author-system` is created if missing (else `last_seen` updated) at startup.
- This is a **runtime startup hook** (`aindy-runtime` startup) writing to the app-owned
  `authors` table (`apps/authorship`). Listed here for visibility; the enforcement point is
  runtime-owned.
- Type: Application-enforced (runtime startup).
