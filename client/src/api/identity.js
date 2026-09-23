import { authRequest } from "./_core.js";
import { ROUTES } from "./_routes.js";

// Every /apps/identity route runs through `execute_with_pipeline` and returns the
// `{status, data, ...}` envelope, stamped `X-AINDY-Envelope`, so ui-kit >= 2.1.0's `request()`
// resolves it to `data` before it reaches us (FR-37). Before that, without unwrapping, IdentityDashboard reads
// `profile?.["communication" | "tools" | "decision_making" | "learning"]` off the
// envelope — all undefined — so the page renders with four blank dimension cards and
// an evolution panel stuck at 0 observations / 0 changes.
//
// Note: the /apps/memory routes are NOT enveloped (they return `{nodes, ...}` and
// `{results, ...}` directly), so they carry no header and arrive as sent.

export function getIdentityProfile() {
  return authRequest(ROUTES.IDENTITY.PROFILE, { method: "GET" });
}

export function updateIdentityProfile(updates) {
  return authRequest(ROUTES.IDENTITY.PROFILE, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
}

export function getIdentityEvolution() {
  return authRequest(ROUTES.IDENTITY.EVOLUTION, { method: "GET" });
}

export function getIdentityContext() {
  return authRequest(ROUTES.IDENTITY.CONTEXT, { method: "GET" });
}
