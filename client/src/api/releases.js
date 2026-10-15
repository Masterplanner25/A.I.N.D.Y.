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
