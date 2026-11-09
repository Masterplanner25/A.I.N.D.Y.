import { authRequest } from "./_core.js";

// Your watcher keys (runtime /watcher/keys, DEC-117). A key can only send watcher signals, which count for you.
// It is shown once, when it is made. A signed-in session only.
export async function listWatcherKeys() {
  const response = await authRequest("/watcher/keys");
  const body = response?.keys ? response : response?.data ?? response;
  return Array.isArray(body?.keys) ? body.keys : [];
}

export function createWatcherKey(name) {
  return authRequest("/watcher/keys", { method: "POST", body: JSON.stringify({ name }) });
}

export async function revokeWatcherKey(id) {
  await authRequest(`/watcher/keys/${encodeURIComponent(id)}`, { method: "DELETE" });
}
