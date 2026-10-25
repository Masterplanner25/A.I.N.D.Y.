import { authRequest } from "./_core.js";

// The release handoff (docs/specs/RELEASE_HANDOFF_SPEC.md): hand a tagged release off and A.I.N.D.Y.
// follows its publish run to the end. Served at /apps/releases. The bodies are bare JSON (the
// automation routes answer through raw_json_adapter), so nothing here unwraps.

export function listReleases({ active = false, limit = 10 } = {}) {
  return authRequest(`/apps/releases?active=${active ? "true" : "false"}&limit=${limit}`, { method: "GET" });
}

export function handOffRelease(tag, repo) {
  return authRequest("/apps/releases", {
    method: "POST",
    body: JSON.stringify(repo ? { tag, repo } : { tag }),
  });
}

// Phase 3 (§7.3): answer the gate on GitHub as the owner. Shown only when the handoff says can_decide.
export function decideRelease(id, decision, comment) {
  return authRequest(`/apps/releases/${encodeURIComponent(id)}/${decision === "approve" ? "approve" : "reject"}`, {
    method: "POST",
    body: JSON.stringify(comment ? { comment } : {}),
  });
}
