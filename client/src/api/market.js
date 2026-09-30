import { authRequest } from "./_core.js";

// The Market model (docs/specs/MARKET_MODEL_SPEC.md): who your work is for, what surrounds that
// buyer, and why each bet is believed. Served at /apps/market. Bare JSON bodies (masterplan's
// raw_json_adapter), so nothing here unwraps.

const json = (method, body) => ({ method, body: JSON.stringify(body) });

export function getMarket() {
  return authRequest("/apps/market", { method: "GET" });
}

export function listMarketProposals() {
  return authRequest("/apps/market/proposals", { method: "GET" });
}

export function confirmMarketProposal(body) {
  return authRequest("/apps/market/proposals/confirm", json("POST", body));
}

export function dismissMarketProposal(key) {
  return authRequest("/apps/market/proposals/dismiss", json("POST", { key }));
}

export function createSegment(body) {
  return authRequest("/apps/market/segments", json("POST", body));
}

export function updateSegment(segmentId, body) {
  return authRequest(`/apps/market/segments/${encodeURIComponent(segmentId)}`, json("PATCH", body));
}

export function deleteSegment(segmentId) {
  return authRequest(`/apps/market/segments/${encodeURIComponent(segmentId)}`, { method: "DELETE" });
}

export function setSegmentWorks(segmentId, workIds) {
  return authRequest(`/apps/market/segments/${encodeURIComponent(segmentId)}/works`, json("PUT", { work_ids: workIds }));
}

export function createMarketEntity(body) {
  return authRequest("/apps/market/entities", json("POST", body));
}

export function deleteMarketEntity(entityId) {
  return authRequest(`/apps/market/entities/${encodeURIComponent(entityId)}`, { method: "DELETE" });
}

// Lead search inside a segment (MARKET_MODEL_SPEC §5). Served by search, at /apps/leadgen.
export function findSegmentBuyers(segment, where = "hiring") {
  return authRequest("/apps/leadgen/segment-search", json("POST", { segment, where }));
}
