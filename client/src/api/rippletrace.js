import { authRequest } from "./_core.js";
import { ROUTES } from "./_routes.js";

export function getRippleDropPoints() {
  return authRequest(ROUTES.RIPPLETRACE.DROP_POINTS, { method: "GET" });
}

export function getRipplePings() {
  return authRequest(ROUTES.RIPPLETRACE.PINGS, { method: "GET" });
}

export function getRecentRippleEvents(limit = 20) {
  return authRequest(`${ROUTES.RIPPLETRACE.RECENT}?limit=${limit}`, { method: "GET" });
}

export function getRippleTrace(dropPointId) {
  return authRequest(ROUTES.RIPPLETRACE.TRACE(dropPointId), { method: "GET" });
}

export function getRippleTraceGraph(traceId) {
  return authRequest(ROUTES.RIPPLETRACE.TRACE_GRAPH(traceId), { method: "GET" });
}

export function getCausalGraph() {
  return authRequest(ROUTES.RIPPLETRACE.CAUSAL_GRAPH);
}

// Canonical, user-authable influence graph. App-owned route not (yet) in ui-kit ROUTES, so the
// full /apps path is written directly rather than via the _routes.js mount correction. The only
// other influence_graph route is the deprecated legacy one behind an admin API key, which 401s a
// normal user — and a 401 trips the global session-expired logout. GraphView must use this one.
export function getInfluenceGraph() {
  return authRequest("/apps/rippletrace/influence/graph", { method: "GET" });
}

// Content ingestion. Like getInfluenceGraph above, these are app-owned routes that
// predate nothing in the ui-kit ROUTES map, so the full /apps path is written directly.

export function ingestContentUrl(url) {
  return authRequest("/apps/rippletrace/ingest", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export function getContentSources() {
  return authRequest("/apps/rippletrace/sources", { method: "GET" });
}

export function pollContentSource(sourceId) {
  return authRequest(`/apps/rippletrace/sources/${sourceId}/poll`, { method: "POST" });
}

export function setContentSourceActive(sourceId, active) {
  return authRequest(`/apps/rippletrace/sources/${sourceId}`, {
    method: "PATCH",
    body: JSON.stringify({ active }),
  });
}

export function deleteContentSource(sourceId) {
  return authRequest(`/apps/rippletrace/sources/${sourceId}`, { method: "DELETE" });
}

export function detectRipples(limit = 5) {
  return authRequest(`/apps/rippletrace/detect?limit=${limit}`, { method: "POST" });
}

export function detectRipplesForDropPoint(dropPointId) {
  return authRequest(`/apps/rippletrace/drop_points/${dropPointId}/detect`, {
    method: "POST",
  });
}

export function getCausalChain(dropPointId, depth = 3) {
  return authRequest(`${ROUTES.RIPPLETRACE.CAUSAL_CHAIN(dropPointId)}?depth=${depth}`);
}

export function getNarrativeSummary(limit = 3) {
  return authRequest(`${ROUTES.RIPPLETRACE.NARRATIVE_SUMMARY}?limit=${limit}`);
}

export function getDropPointNarrative(dropPointId) {
  return authRequest(ROUTES.RIPPLETRACE.DROP_POINT_NARRATIVE(dropPointId));
}

export function getPredictionsSummary(limit = 50) {
  return authRequest(`${ROUTES.RIPPLETRACE.PREDICTIONS_SUMMARY}?limit=${limit}`);
}

export function getDropPointPrediction(dropPointId, recordLearning = true) {
  return authRequest(
    ROUTES.RIPPLETRACE.DROP_POINT_PREDICTION(dropPointId) +
      `?record_learning=${recordLearning}`
  );
}

export function getSystemRecommendations(limit = 20) {
  return authRequest(`${ROUTES.RIPPLETRACE.SYSTEM_RECOMMENDATIONS}?limit=${limit}`);
}

export function getRecommendationsSummary(limit = 20) {
  return authRequest(`${ROUTES.RIPPLETRACE.RECOMMENDATIONS_SUMMARY}?limit=${limit}`);
}

export function getDropPointRecommendation(dropPointId) {
  return authRequest(ROUTES.RIPPLETRACE.DROP_POINT_RECOMMENDATION(dropPointId));
}

export function getLearningStats() {
  return authRequest(ROUTES.RIPPLETRACE.LEARNING_STATS);
}

export function evaluateLearningOutcome(dropPointId) {
  return authRequest(ROUTES.RIPPLETRACE.EVALUATE_LEARNING_OUTCOME(dropPointId), {
    method: "POST",
  });
}

export function adjustLearningThresholds() {
  return authRequest(ROUTES.RIPPLETRACE.ADJUST_LEARNING_THRESHOLDS, { method: "POST" });
}

export function getPlaybooks() {
  return authRequest(ROUTES.RIPPLETRACE.PLAYBOOKS);
}

export function getPlaybook(playbookId) {
  return authRequest(ROUTES.RIPPLETRACE.PLAYBOOK(playbookId));
}

export function matchPlaybooks(dropPointId) {
  return authRequest(ROUTES.RIPPLETRACE.MATCH_PLAYBOOKS(dropPointId));
}

export function getStrategies() {
  return authRequest(ROUTES.RIPPLETRACE.STRATEGIES);
}

export function buildStrategies() {
  return authRequest(ROUTES.RIPPLETRACE.BUILD_STRATEGIES);
}

export function getStrategy(strategyId) {
  return authRequest(ROUTES.RIPPLETRACE.STRATEGY(strategyId));
}

export function matchStrategies(dropPointId) {
  return authRequest(ROUTES.RIPPLETRACE.MATCH_STRATEGIES(dropPointId));
}

export function getEventDownstream(eventId) {
  return authRequest(ROUTES.RIPPLETRACE.EVENT_DOWNSTREAM(eventId));
}

export function getEventUpstream(eventId) {
  return authRequest(ROUTES.RIPPLETRACE.EVENT_UPSTREAM(eventId));
}
