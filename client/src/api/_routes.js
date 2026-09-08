// App-owned route map.
//
// The shared @aindy/ui-kit exports `ROUTES`, but builds this monolith's *app-domain* paths
// without the `/apps` router prefix the backend actually mounts them under. In the ui-kit
// bundle the app prefix is the empty string, so e.g. MASTERPLAN.GENESIS_SESSION resolves to
// `/genesis/session` while the backend serves `/apps/genesis/session` — a 404. An audit of the
// live openapi found 90 of 101 ui-kit app routes unreachable this way, which took out most of
// the app surface (Genesis init, freelance, tasks, scores, identity, social, arm, rippletrace…).
//
// Per the runtime/app split applied at the frontend layer, the shared kit owns runtime/platform
// routes and each app owns its own app routes. This module is that ownership boundary: it
// re-exports ui-kit's `ROUTES` and corrects the app-domain paths that belong to this monolith.
//
// Two corrections compose here, in order:
//   1. sub-router prefixes ui-kit omits entirely (`/compute`, `/seo`)
//   2. the `/apps` mount prefix, applied to every path that isn't runtime-owned
// So `/calculate_twr` -> `/compute/calculate_twr` -> `/apps/compute/calculate_twr`.
//
// Runtime-owned namespaces (`/auth`, `/platform`, `/api`, `/health`, `/openapi`) are left
// alone — PLATFORM in particular is mixed, holding both `/dashboard/overview` (app-domain)
// and `/health/details` (runtime), so the rule is path-based rather than per-domain.
//
// Self-healing: each correction is a no-op when the value is already prefixed, so if a future
// ui-kit emits correct `/apps/...` paths (the correct upstream end-state) nothing double-
// prefixes and this quietly becomes dead weight rather than breaking.
//
// See docs/archive/UIKIT_ROUTE_FIXES.md and TECH_DEBT UIKIT-ROUTE-DRIFT-1.

import { ROUTES as UIKIT_ROUTES } from "@aindy/ui-kit";

// Analytics KPI compute endpoints live under the backend `/compute` router.
const COMPUTE_KEYS = [
  "CALCULATE_TWR",
  "CALCULATE_ENGAGEMENT",
  "CALCULATE_AI_EFFICIENCY",
  "CALCULATE_IMPACT_SCORE",
  "CALCULATE_AI_PRODUCTIVITY_BOOST",
  "CALCULATE_ATTENTION_VALUE",
  "CALCULATE_BUSINESS_GROWTH",
  "CALCULATE_DECISION_EFFICIENCY",
  "CALCULATE_ENGAGEMENT_RATE",
  "CALCULATE_EXECUTION_SPEED",
  "CALCULATE_INCOME_EFFICIENCY",
  "CALCULATE_LOST_POTENTIAL",
  "CALCULATE_MONETIZATION_EFFICIENCY",
  "CALCULATE_REVENUE_SCALING",
];

// SEO endpoints live under the backend `/seo` router.
const SEO_KEYS = ["ANALYZE_SEO", "GENERATE_META", "SUGGEST_IMPROVEMENTS"];

function withPrefix(group, keys, prefix) {
  const corrected = { ...group };
  for (const key of keys) {
    const value = group?.[key];
    if (typeof value === "string" && !value.startsWith(prefix)) {
      corrected[key] = `${prefix}${value}`;
    }
  }
  // Preserve ui-kit's frozen-domain-map contract (see api-routes.test.js).
  return Object.freeze(corrected);
}

// Namespaces the runtime owns and mounts at the root — never prefixed with /apps.
// `/client` is the runtime's client-telemetry sink (/client/error, /client/vitals).
const RUNTIME_OWNED_PREFIXES = [
  "/apps",
  "/auth",
  "/platform",
  "/api",
  "/health",
  "/openapi",
  "/client",
];

function isRuntimeOwned(value) {
  return RUNTIME_OWNED_PREFIXES.some(
    (prefix) => value === prefix || value.startsWith(`${prefix}/`),
  );
}

// Route entries are strings or path-building functions; both must be corrected.
function toAppPath(value) {
  if (typeof value === "function") {
    return (...args) => toAppPath(value(...args));
  }
  if (typeof value !== "string" || !value.startsWith("/") || isRuntimeOwned(value)) {
    return value;
  }
  return `/apps${value}`;
}

function withAppsMount(group) {
  if (!group || typeof group !== "object") return group;
  const corrected = {};
  for (const [key, value] of Object.entries(group)) {
    corrected[key] = toAppPath(value);
  }
  // Preserve ui-kit's frozen-domain-map contract (see api-routes.test.js).
  return Object.freeze(corrected);
}

// Routes this repo owns that the ui-kit does not declare AT ALL — a third correction
// alongside the two above, which both fix paths the kit already has. `/tasks/delete` is
// app-owned (the backend mounts it on the tasks router), so it flows through
// `withAppsMount` below and picks up the `/apps` prefix like every other app route.
//
// Kept here rather than hardcoded at the call site so the route-map guard test sees it and
// so a future ui-kit that adds TASKS.DELETE overrides cleanly instead of colliding.
const APP_ONLY_ROUTES = {
  TASKS: { DELETE: "/tasks/delete" },
  // `/search/feedback` records implicit (click/dwell/convert/dismiss) and explicit
  // (thumbs_up/thumbs_down) signals on a search result. The backend route, service and
  // ranking nudge have all existed since Search v4 §8; nothing in the client called it, so
  // `search_result_feedback` had 0 rows and AINDY_SEARCH_OUTCOME_WEIGHTING had no input.
  // `/seo/title` proposes title options for an article. App-owned and not in the ui-kit, so
  // it carries its own `/seo` prefix here rather than going through `withPrefix`.
  // Containers — the project or series a piece belongs to. App-owned and not in the ui-kit.
  RIPPLETRACE: {
    CONTAINER_CANDIDATES: "/rippletrace/containers/candidates",
    CONTAINER_PERFORMANCE: "/rippletrace/containers/performance",
    CONTAINER_CONFIRM: "/rippletrace/containers/confirm",
    CONTAINER_DISMISS: "/rippletrace/containers/dismiss",
  },
  SEARCH: {
    FEEDBACK: "/search/feedback",
    GENERATE_TITLE: "/seo/title",
    // The draft loop. App-owned and not in the ui-kit, so these carry their own `/seo`
    // prefix rather than going through `withPrefix`.
    DRAFTS: "/seo/drafts",
  },
};

const SUB_ROUTER_CORRECTED = {
  ...UIKIT_ROUTES,
  RIPPLETRACE: { ...UIKIT_ROUTES.RIPPLETRACE, ...APP_ONLY_ROUTES.RIPPLETRACE },
  ANALYTICS: withPrefix(UIKIT_ROUTES.ANALYTICS, COMPUTE_KEYS, "/compute"),
  TASKS: { ...UIKIT_ROUTES.TASKS, ...APP_ONLY_ROUTES.TASKS },
  // `withPrefix` first (the kit's SEO paths), then the app-only additions. Order matters:
  // the SEO correction must only ever touch keys the kit actually declares.
  SEARCH: {
    ...withPrefix(UIKIT_ROUTES.SEARCH, SEO_KEYS, "/seo"),
    ...APP_ONLY_ROUTES.SEARCH,
  },
};

const MOUNTED = {};
for (const [domain, group] of Object.entries(SUB_ROUTER_CORRECTED)) {
  MOUNTED[domain] = withAppsMount(group);
}

export const ROUTES = Object.freeze(MOUNTED);

// Exposed for the route-map guard test.
export const APP_OWNED_ROUTE_CORRECTIONS = {
  COMPUTE_KEYS,
  SEO_KEYS,
  RUNTIME_OWNED_PREFIXES,
  APP_ONLY_ROUTES,
};
