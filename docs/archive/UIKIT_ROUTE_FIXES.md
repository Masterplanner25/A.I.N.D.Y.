---
title: "UI-Kit Route Fixes — handoff to @aindy/ui-kit"
last_verified: "2026-07-18"
api_version: "1.0"
status: current
owner: "app-team"
---

# UI-Kit Route Fixes — handoff to `@aindy/ui-kit`

## ✅ Resolved (2026-07-18)

`@aindy/ui-kit@1.0.6` shipped the runtime/platform fix and the app bumped to it
(`client/package.json` → `^1.0.6`). 1.0.6 corrected the platform surface broadly —
`OPERATOR.FLOW_STRATEGIES` **and** the rest of `OPERATOR.*` now resolve under `/platform/*`,
and `AGENT.*` now uses the canonical `/apps/agent/*`. The 17 app-domain routes (`/compute/*`,
`/seo/*`) were **not** changed upstream (correctly — they're app-owned) and remain corrected by
this repo's `client/src/api/_routes.js`. **Effective client→backend drift is now 0** (139
routes cross-checked vs the live `/openapi.json`). The detail below is retained for history.

## What this is

A live-frontend verification of `client/` (2026-07-18) cross-checked all 135 client route
definitions (from `@aindy/ui-kit`'s `ROUTES`, resolved through `buildApiUrl`) against the
566 live backend routes. **18 resolved to paths the backend doesn't serve** — each omitting
its backend router-prefix segment.

A runtime-side ownership review then split those 18 by layer — and only **one** is actually
a `@aindy/ui-kit` fix:

| Layer | Routes | Owner / home |
|---|---|---|
| **Runtime / platform** | `/platform/flows/strategies` (1) | **Fix in `@aindy/ui-kit`** — every consumer of the platform surface benefits (`AINDY/routes/platform/flows_router.py`). |
| **App-domain** | `/compute/*` (14 analytics KPI) + `/seo/*` (3) | **App-owned** — these are this monolith's endpoints, not runtime routes; corrected in the app's own route map. |

## The one item for `@aindy/ui-kit`

`ROUTES.OPERATOR.FLOW_STRATEGIES`:

```
/flows/strategies   →   /platform/flows/strategies
```

This is a genuine runtime/platform route (the strategies are app-registered via
`register_flow_strategy`, but the *route that lists them* is runtime-owned). Every ui-kit
consumer of the platform surface inherits the bug and benefits from the fix. If
`docs/runtime/UI_CONTRACT.md` (the runtime→UI contract) doesn't already pin the canonical
platform paths, adding `/platform/flows/strategies` there gives ui-kit an authoritative
source so this can't drift again.

## The 17 app-domain routes — resolved app-side (not a ui-kit ask)

The 14 `ANALYTICS.CALCULATE_*` (`/compute/*`) and 3 SEO (`/seo/*`) routes are this monolith's
own endpoints. Per the runtime/app split applied at the frontend layer — the shared kit owns
runtime/platform routes, each app owns its own app routes — these do **not** belong in
`@aindy/ui-kit`. A different app built on the runtime would define its own, not inherit these.

They are corrected in this repo's app-owned route map, `client/src/api/_routes.js`, which
re-exports ui-kit's `ROUTES` and overrides the app-domain paths (self-healing: it only prepends
the missing prefix when ui-kit's value is present and unprefixed, so a future ui-kit that
removes these — the correct upstream end-state — makes the override a no-op). Guarded by
`client/src/api/__tests__/routes-app-owned.test.js`. See TECH_DEBT **UIKIT-ROUTE-DRIFT-1**.

**Suggested upstream end-state (optional, ui-kit hygiene):** remove the app-domain
`ANALYTICS.CALCULATE_*` and SEO path entries from the shared `ROUTES` so the kit stops baking
in monolith-specific app routes — the coupling this finding made visible. Not required for
correctness here (the app override owns them either way).

## For reference — the full 18 with verified targets

`/compute` group (app-owned, fixed in `_routes.js`):

```
CALCULATE_TWR                     /calculate_twr             → /compute/calculate_twr
CALCULATE_ENGAGEMENT             /calculate_engagement       → /compute/calculate_engagement
CALCULATE_AI_EFFICIENCY          /calculate_ai_efficiency    → /compute/calculate_ai_efficiency
CALCULATE_IMPACT_SCORE           /calculate_impact_score     → /compute/calculate_impact_score
CALCULATE_AI_PRODUCTIVITY_BOOST  /ai_productivity_boost      → /compute/ai_productivity_boost
CALCULATE_ATTENTION_VALUE        /attention_value            → /compute/attention_value
CALCULATE_BUSINESS_GROWTH        /business_growth            → /compute/business_growth
CALCULATE_DECISION_EFFICIENCY    /decision_efficiency        → /compute/decision_efficiency
CALCULATE_ENGAGEMENT_RATE        /engagement_rate            → /compute/engagement_rate
CALCULATE_EXECUTION_SPEED        /execution_speed            → /compute/execution_speed
CALCULATE_INCOME_EFFICIENCY      /income_efficiency          → /compute/income_efficiency
CALCULATE_LOST_POTENTIAL         /lost_potential             → /compute/lost_potential
CALCULATE_MONETIZATION_EFFICIENCY/monetization_efficiency    → /compute/monetization_efficiency
CALCULATE_REVENUE_SCALING        /revenue_scaling            → /compute/revenue_scaling
```

`/seo` group (app-owned, fixed in `_routes.js` — targets the backend compat aliases; canonical
`/seo/analyze`, `/seo/meta`, `/seo/suggest` also exist):

```
ANALYZE_SEO          /analyze_seo/          → /seo/analyze_seo/
GENERATE_META        /generate_meta/        → /seo/generate_meta/
SUGGEST_IMPROVEMENTS /suggest_improvements/ → /seo/suggest_improvements/
```

`/platform` group (runtime-owned, **fix in ui-kit**):

```
FLOW_STRATEGIES      /flows/strategies      → /platform/flows/strategies
```

## Verification

Resolving every `ROUTES.*` value through `buildApiUrl` should hit a live backend route. The
app-side cross-check that found this (135 client routes vs the live `/openapi.json`, structural
match with `{param}` as wildcards and an optional leading `/apps` stripped) drops from 18
mismatches to **1** once the app override lands, and to **0** once the ui-kit `/platform/flows`
fix ships and this repo bumps the dependency.
