import { authRequest, taggedRequest } from "./_core.js";
import { ROUTES } from "./_routes.js";

// The LinkedIn manual-ingest wrappers (`ingestLinkedInManual`, `getMasterplanSummary`)
// were removed with the /analytics rewire. The surface that called them could never
// succeed: the form's fields did not match `LinkedInRawInput` (422 on every submit) and
// the adapter behind the syscall boundary received a dict where it expected an object
// (500 even with a correct payload), so `canonical_metrics` never held a row. The
// backend routes are parked, not deleted — see docs/verification/FRONTEND_WALK_LOG.md item 18.
// /analytics now renders the system-fed social engine via api/social.js.

export const calculateTwr = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_TWR, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateEngagement = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_ENGAGEMENT, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateAiEfficiency = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_AI_EFFICIENCY, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateImpactScore = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_IMPACT_SCORE, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateIncomeEfficiency = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_INCOME_EFFICIENCY, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateRevenueScaling = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_REVENUE_SCALING, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateExecutionSpeed = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_EXECUTION_SPEED, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateAttentionValue = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_ATTENTION_VALUE, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateEngagementRate = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_ENGAGEMENT_RATE, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateBusinessGrowth = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_BUSINESS_GROWTH, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateMonetizationEfficiency = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_MONETIZATION_EFFICIENCY, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateAiProductivityBoost = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_AI_PRODUCTIVITY_BOOST, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateDecisionEfficiency = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_DECISION_EFFICIENCY, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const calculateLostPotential = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.CALCULATE_LOST_POTENTIAL, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const getMyScore = taggedRequest("analytics", () =>
  authRequest(ROUTES.ANALYTICS.SCORES_ME, { method: "GET" })
);

// Three-axis snapshot (Volume / Worth / Trajectory). No ui-kit ROUTES constant yet —
// this is a newer app route not in the shared map, so the /apps-mounted path is a literal.
export const getThreeAxis = taggedRequest("analytics", () =>
  authRequest("/apps/analytics/three-axis", { method: "GET" })
);

export const recalculateScore = taggedRequest("analytics", () =>
  authRequest(ROUTES.ANALYTICS.SCORES_RECALCULATE, { method: "POST" })
);

export const getScoreHistory = taggedRequest("analytics", (limit = 30) =>
  authRequest(`${ROUTES.ANALYTICS.SCORES_HISTORY}?limit=${limit}`, { method: "GET" })
);

export const postScoreFeedback = taggedRequest("analytics", (payload) =>
  authRequest(ROUTES.ANALYTICS.SCORES_FEEDBACK, {
    method: "POST",
    body: JSON.stringify(payload),
  })
);

export const getScoreFeedback = taggedRequest("analytics", (limit = 50) =>
  authRequest(`${ROUTES.ANALYTICS.SCORES_FEEDBACK}?limit=${limit}`, { method: "GET" })
);
