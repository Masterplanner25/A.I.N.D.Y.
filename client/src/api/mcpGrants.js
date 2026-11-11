import { authRequest } from "./_core.js";

// Your connected apps (runtime /auth/mcp-grants, 2.35.0, FR-66): the AIs (claude.ai, ChatGPT) you let read
// A.I.N.D.Y. over MCP. Ending one stops every token it holds within seconds. A signed-in session only.
export async function listMcpGrants() {
  const response = await authRequest("/auth/mcp-grants");
  const body = response?.grants ? response : response?.data ?? response;
  if (Array.isArray(body)) return body;
  return Array.isArray(body?.grants) ? body.grants : [];
}

export async function revokeMcpGrant(id) {
  await authRequest(`/auth/mcp-grants/${encodeURIComponent(id)}`, { method: "DELETE" });
}
