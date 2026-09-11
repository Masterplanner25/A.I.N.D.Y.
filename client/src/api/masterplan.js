import { authRequest } from "./_core.js";
import { ROUTES } from "./_routes.js";

export function startGenesisSession() {
  return authRequest(ROUTES.MASTERPLAN.GENESIS_SESSION, { method: "POST" });
}

// Seeds a Genesis session from a plan the user already wrote, so it can be discussed
// before being locked. Route is newer than the ui-kit ROUTES map, so the full /apps
// path is written directly.
export function importExistingPlan(content) {
  return authRequest("/apps/genesis/import", {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function sendGenesisMessage(sessionId, message) {
  return authRequest(ROUTES.MASTERPLAN.GENESIS_MESSAGE, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, message }),
  });
}

export function getGenesisSession(sessionId) {
  return authRequest(ROUTES.MASTERPLAN.GENESIS_SESSION_BY_ID(sessionId), { method: "GET" });
}

export function synthesizeGenesisDraft(sessionId) {
  return authRequest(ROUTES.MASTERPLAN.GENESIS_SYNTHESIZE, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export function getGenesisDraft(sessionId) {
  return authRequest(ROUTES.MASTERPLAN.GENESIS_DRAFT(sessionId), { method: "GET" });
}

export function lockMasterPlan(sessionId, draft) {
  return authRequest(ROUTES.MASTERPLAN.GENESIS_LOCK, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, draft }),
  });
}

export function auditGenesisDraft(sessionId) {
  return authRequest(ROUTES.MASTERPLAN.GENESIS_AUDIT, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export function listMasterPlans() {
  return authRequest(ROUTES.MASTERPLAN.PLANS, { method: "GET" });
}

export function getMasterPlan(planId) {
  return authRequest(ROUTES.MASTERPLAN.PLAN(planId), { method: "GET" });
}

export function activateMasterPlan(planId) {
  return authRequest(ROUTES.MASTERPLAN.PLAN_ACTIVATE(planId), { method: "POST" });
}

export function setMasterplanAnchor(planId, anchorData) {
  return authRequest(ROUTES.MASTERPLAN.PLAN_ANCHOR(planId), {
    method: "PUT",
    body: JSON.stringify(anchorData),
  });
}

export function getMasterplanProjection(planId) {
  return authRequest(ROUTES.MASTERPLAN.PLAN_PROJECTION(planId), { method: "GET" });
}

// ── Strategy layer (STRATEGY_LAYER_SPEC §8 step 3b) ─────────────────────────────
// Routes newer than the ui-kit ROUTES map, so the full /apps paths are written directly.

export function getStrategyLayer(planId) {
  return authRequest(`/apps/masterplans/${planId}/strategy-layer`, { method: "GET" });
}

// What the system proposes about the plan's current phase. Reads only — the proposal is
// the system's half; confirming it is the human's.
export function getPhaseAdvanceProposal(planId) {
  return authRequest(`/apps/masterplans/${planId}/phase-advance`, { method: "GET" });
}

export function confirmPhaseAdvance(planId, phaseId) {
  return authRequest(`/apps/masterplans/${planId}/phase-advance/confirm`, {
    method: "POST",
    body: JSON.stringify({ phase_id: phaseId }),
  });
}
