import { authRequest } from "./_core.js";
import { ROUTES } from "./_routes.js";

export * from "./operator.js";

export function getDashboardOverview() {
  return authRequest(ROUTES.PLATFORM.DASHBOARD_OVERVIEW, { method: "GET" });
}

export function getHealthDetails() {
  return authRequest(ROUTES.PLATFORM.HEALTH_DETAILS, { method: "GET" });
}

// getInfluenceGraph / getCausalGraph / getNarrative were removed 2026-11-08: they called
// RippleTrace's legacy shared-key routes, retired server-side in #548. The graph view uses the
// user-scoped versions in ./rippletrace.js.
