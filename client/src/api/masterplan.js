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

// "Not done." The proposal returns when the phase's attached tasks change.
export function dismissPhaseAdvance(planId, phaseId) {
  return authRequest(`/apps/masterplans/${planId}/phase-advance/dismiss`, {
    method: "POST",
    body: JSON.stringify({ phase_id: phaseId }),
  });
}

// Reverse a confirmation. Only the most recently closed phase can reopen.
export function reopenPhase(planId, phaseId) {
  return authRequest(`/apps/masterplans/${planId}/phases/${phaseId}/reopen`, { method: "POST" });
}

// ── Strategies — how a phase gets done (STRATEGY_LAYER_SPEC §5) ──────────────────
// proposed → active → concluded | abandoned | displaced. Every transition is a human verb.

export function createStrategy(planId, body) {
  return authRequest(`/apps/masterplans/${planId}/strategies`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// A task that is really a strategy becomes one. The task row goes.
export function promoteTaskToStrategy(planId, taskId) {
  return authRequest(`/apps/masterplans/${planId}/strategies/promote`, {
    method: "POST",
    body: JSON.stringify({ task_id: taskId }),
  });
}

export function startStrategy(planId, strategyId) {
  return authRequest(`/apps/masterplans/${planId}/strategies/${strategyId}/start`, { method: "POST" });
}

// verb: "conclude" (needs an outcome) | "abandon" | "displace"
export function finishStrategy(planId, strategyId, verb, { outcome, note } = {}) {
  return authRequest(`/apps/masterplans/${planId}/strategies/${strategyId}/${verb}`, {
    method: "POST",
    body: JSON.stringify({ outcome: outcome ?? null, note: note ?? null }),
  });
}

// Which objective a strategy serves. Ownership, not scheduling; null un-houses.
export function setStrategyObjective(planId, strategyId, objectiveId) {
  return authRequest(`/apps/masterplans/${planId}/strategies/${strategyId}/objective`, {
    method: "POST",
    body: JSON.stringify({ objective_id: objectiveId || null }),
  });
}

