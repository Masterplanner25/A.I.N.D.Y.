import { adminRequest as authRequest, unwrapEnvelope } from "./_core.js";
import { ROUTES } from "./_routes.js";

export function getFlowRuns(status = null, workflowType = null, limit = 20) {
  const params = new URLSearchParams();
  if (status) params.append("status", status);
  if (workflowType) params.append("workflow_type", workflowType);
  params.append("limit", limit);
  return authRequest(`${ROUTES.OPERATOR.FLOW_RUNS}?${params.toString()}`, { method: "GET" });
}

export function getFlowRun(runId) {
  return authRequest(ROUTES.OPERATOR.FLOW_RUN(runId), { method: "GET" });
}

export function getFlowRunHistory(runId) {
  return authRequest(ROUTES.OPERATOR.FLOW_RUN_HISTORY(runId), { method: "GET" });
}

export function resumeFlowRun(runId, eventType, payload = {}) {
  return authRequest(ROUTES.OPERATOR.FLOW_RUN_RESUME(runId), {
    method: "POST",
    body: JSON.stringify({ event_type: eventType, payload }),
  });
}

export function getFlowRegistry() {
  return authRequest(ROUTES.OPERATOR.FLOW_REGISTRY, { method: "GET" });
}

// Run a registered flow on demand. Body is FlowRunRequest ({state?}). /platform is
// runtime-owned; no ui-kit constant for the by-name run route, so the path is a literal.
export function runFlow(name, state = {}) {
  return authRequest(`/platform/flows/${encodeURIComponent(name)}/run`, {
    method: "POST",
    body: JSON.stringify({ state }),
  }).then(unwrapEnvelope);
}

export function getFlowStrategies() {
  return authRequest(ROUTES.OPERATOR.FLOW_STRATEGIES, { method: "GET" });
}

export function getAutomationLogs(status = null, source = null, limit = 50) {
  const params = new URLSearchParams();
  if (status) params.append("status", status);
  if (source) params.append("source", source);
  params.append("limit", limit);
  return authRequest(`${ROUTES.OPERATOR.AUTOMATION_LOGS}?${params.toString()}`, { method: "GET" });
}

export function getAutomationLog(logId) {
  return authRequest(ROUTES.OPERATOR.AUTOMATION_LOG(logId), { method: "GET" });
}

export function replayAutomationLog(logId) {
  return authRequest(ROUTES.OPERATOR.AUTOMATION_REPLAY(logId), { method: "POST" });
}

export function getSchedulerStatus() {
  return authRequest(ROUTES.OPERATOR.SCHEDULER_STATUS, { method: "GET" });
}

export function getObservabilityRequests(windowHours = 24, limit = 50, errorLimit = 25) {
  const params = new URLSearchParams({
    window_hours: String(windowHours),
    limit: String(limit),
    error_limit: String(errorLimit),
  });
  return authRequest(`${ROUTES.OPERATOR.OBSERVABILITY_REQUESTS}?${params.toString()}`, { method: "GET" });
}

// Execution graph for a single trace. No ui-kit ROUTES constant yet — /platform is
// runtime-owned (never /apps-mounted), so the path is a literal like the other operator routes.
export function getExecutionGraph(traceId) {
  return authRequest(`/platform/observability/execution_graph/${encodeURIComponent(traceId)}`, {
    method: "GET",
  });
}

// ── Webhooks (control-plane: subscription CRUD) ──────────────────────────────
// GET returns a flat {webhooks:[…]}; DELETE returns 204 (empty body → resolves "").
export function getWebhooks() {
  return authRequest("/platform/webhooks", { method: "GET" }).then(unwrapEnvelope);
}

export function createWebhook({ event_type, callback_url, secret }) {
  // Operator-created subscriptions are first-party (the operator owns this deployment).
  // external-third-party ownership additionally requires declared provenance — not something
  // an operator supplies from this console.
  const body = { event_type, callback_url, owner_class: "first-party-app" };
  if (secret) body.secret = secret;
  return authRequest("/platform/webhooks", {
    method: "POST",
    body: JSON.stringify(body),
  }).then(unwrapEnvelope);
}

export function deleteWebhook(subscriptionId) {
  return authRequest(`/platform/webhooks/${encodeURIComponent(subscriptionId)}`, {
    method: "DELETE",
  });
}

// ── Admin users (control-plane: promotion) ───────────────────────────────────
// GET returns a flat {users:[…]}; promote wraps in the {status,data} envelope.
export function getAdminUsers() {
  return authRequest("/platform/admin/users", { method: "GET" });
}

export function promoteUser(userId) {
  return authRequest(`/platform/admin/users/${encodeURIComponent(userId)}/promote`, {
    method: "POST",
  }).then(unwrapEnvelope);
}

// ── Dead-Letter Queue (control-plane actions) ────────────────────────────────
// /platform is runtime-owned (never /apps-mounted) and these queue routes wrap their
// payload in the standard {status, data} envelope, so unwrap to a flat object.
export function getQueueHealth() {
  return authRequest("/platform/queue/health", { method: "GET" }).then(unwrapEnvelope);
}

export function getDeadLetters(limit = 100) {
  return authRequest(`/platform/queue/dead-letters?limit=${limit}`, { method: "GET" }).then(unwrapEnvelope);
}

export function replayDeadLetter(jobId) {
  return authRequest(`/platform/queue/dead-letters/${encodeURIComponent(jobId)}/replay`, {
    method: "POST",
  }).then(unwrapEnvelope);
}

export function deleteDeadLetter(jobId) {
  return authRequest(`/platform/queue/dead-letters/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  }).then(unwrapEnvelope);
}

export function drainDeadLetters() {
  return authRequest("/platform/queue/dead-letters/drain", { method: "POST" }).then(unwrapEnvelope);
}

export function getObservabilityDashboard(windowHours = 24) {
  const params = new URLSearchParams({
    window_hours: String(windowHours),
  });
  return authRequest(`${ROUTES.OPERATOR.OBSERVABILITY_DASHBOARD}?${params.toString()}`, { method: "GET" });
}

export async function reportClientError(payload) {
  await authRequest(ROUTES.OPERATOR.CLIENT_ERROR, {
    method: "POST",
    body: JSON.stringify(payload),
  }).catch(() => {});
}

export async function reportClientVitals(payload) {
  await authRequest(ROUTES.OPERATOR.CLIENT_VITALS, {
    method: "POST",
    body: JSON.stringify(payload),
  }).catch(() => {});
}
