import { authRequest } from "./_core.js";

// Goals: what you are working toward, above any one plan (GOALS_LAYER_SPEC). Proposals from your plan act on nothing
// until you confirm them.
export function getGoalsOverview() {
  return authRequest("/apps/goals/overview");
}

export function confirmGoal(id, edits = {}) {
  return authRequest(`/apps/goals/${encodeURIComponent(id)}/confirm`, { method: "POST", body: JSON.stringify(edits) });
}

export function dropGoal(id) {
  return authRequest(`/apps/goals/${encodeURIComponent(id)}/drop`, { method: "POST" });
}

export function updateGoal(id, edits) {
  return authRequest(`/apps/goals/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(edits) });
}

export function createGoal({ name, description, objectiveIds = [], priority = 0.5 }) {
  return authRequest("/apps/goals", {
    method: "POST",
    body: JSON.stringify({ name, description: description || null, objective_ids: objectiveIds, priority }),
  });
}
