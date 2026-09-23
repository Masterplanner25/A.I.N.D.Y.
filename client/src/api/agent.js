import { authRequest } from "./_core.js";
import { ROUTES } from "./_routes.js";

// Several /apps/agent read routes wrap their payload as `{data: [...]}` — runs, run steps,
// tools and suggestions (verified live); trust returns a bare object and /apps/memory/agents
// returns `{agents, total}`. That wrapper is not the execution envelope: the agent router
// builds it by hand (`_execute_agent` returns `{"data": data}` for a list), so it carries no
// `X-AINDY-Envelope` and ui-kit >= 2.1.0 hands it back untouched. `listOf` reads it explicitly.
// It used to go through `unwrapEnvelope`, which worked by shape only — and under 2.1.0 stops
// unwrapping once the client has seen any stamped response (FR-37). Without the unwrap
// AgentConsole did `setRuns({data: []})` and then `runs.filter(...)`, which threw and
// blanked the whole console.
const listOf = (body) => (Array.isArray(body) ? body : Array.isArray(body?.data) ? body.data : []);

export function getAgents() {
  return authRequest(ROUTES.MEMORY.AGENTS, { method: "GET" });
}

export function recallFromAgent(namespace, query = "", limit = 5) {
  return authRequest(
    `${ROUTES.MEMORY.AGENT_RECALL(namespace)}?query=${encodeURIComponent(query)}&limit=${limit}`,
    { method: "GET" }
  );
}

export function getFederatedMemory(query, namespaces = null, limit = 5) {
  return authRequest(ROUTES.MEMORY.FEDERATED_RECALL, {
    method: "POST",
    body: JSON.stringify({ query, agent_namespaces: namespaces, limit }),
  });
}

export function createAgentRun(payload) {
  return authRequest(ROUTES.AGENT.CREATE_RUN, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAgentRuns(status = null, limit = 20) {
  const params = new URLSearchParams({ limit });
  if (status) params.append("status", status);
  return authRequest(`${ROUTES.AGENT.RUNS}?${params.toString()}`, { method: "GET" }).then(listOf);
}

export function getAgentRun(runId) {
  return authRequest(ROUTES.AGENT.RUN(runId), { method: "GET" });
}

export function approveAgentRun(runId) {
  return authRequest(ROUTES.AGENT.APPROVE(runId), { method: "POST" });
}

export function rejectAgentRun(runId) {
  return authRequest(ROUTES.AGENT.REJECT(runId), { method: "POST" });
}

export function getAgentRunSteps(runId) {
  return authRequest(ROUTES.AGENT.STEPS(runId), { method: "GET" }).then(listOf);
}

export function getAgentTools() {
  return authRequest(ROUTES.AGENT.TOOLS, { method: "GET" }).then(listOf);
}

export function getAgentTrust() {
  return authRequest(ROUTES.AGENT.TRUST, { method: "GET" });
}

export function updateAgentTrust(payload) {
  return authRequest(ROUTES.AGENT.TRUST, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getAgentSuggestions() {
  return authRequest(ROUTES.AGENT.SUGGESTIONS, { method: "GET" }).then(listOf);
}

export async function fetchRunEvents(runId) {
  return authRequest(ROUTES.AGENT.EVENTS(runId));
}
