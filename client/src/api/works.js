import { authRequest } from "./_core.js";

// The Work model (docs/specs/WORK_MODEL_SPEC.md): what you have made, how the works relate, and
// which objectives they serve. Served at /apps/works. The bodies are bare JSON (the masterplan
// routes answer through raw_json_adapter), so nothing here unwraps.

const json = (method, body) => ({ method, body: JSON.stringify(body) });

export function listWorks() {
  return authRequest("/apps/works", { method: "GET" });
}

export function createWork(body) {
  return authRequest("/apps/works", json("POST", body));
}

export function updateWork(workId, body) {
  return authRequest(`/apps/works/${encodeURIComponent(workId)}`, json("PATCH", body));
}

export function deleteWork(workId) {
  return authRequest(`/apps/works/${encodeURIComponent(workId)}`, { method: "DELETE" });
}

export function addWorkLink(workId, body) {
  return authRequest(`/apps/works/${encodeURIComponent(workId)}/links`, json("POST", body));
}

export function removeWorkLink(linkId) {
  return authRequest(`/apps/works/links/${encodeURIComponent(linkId)}`, { method: "DELETE" });
}

export function setWorkObjectives(workId, objectiveIds) {
  return authRequest(`/apps/works/${encodeURIComponent(workId)}/objectives`, json("PUT", { objective_ids: objectiveIds }));
}

export function listWorkProposals() {
  return authRequest("/apps/works/proposals", { method: "GET" });
}

export function confirmWorkProposal(body) {
  return authRequest("/apps/works/proposals/confirm", json("POST", body));
}

export function dismissWorkProposal(key) {
  return authRequest("/apps/works/proposals/dismiss", json("POST", { key }));
}

// Your published writing, stored and recallable (WORK_MODEL_SPEC §5). Served by RippleTrace.
export function getPublishedWriting() {
  return authRequest("/apps/rippletrace/content/archive", { method: "GET" });
}

export function storePublishedWriting() {
  return authRequest("/apps/rippletrace/content/archive", { method: "POST" });
}
