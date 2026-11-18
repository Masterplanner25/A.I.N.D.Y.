import { authRequest } from "./_core.js";

// Directing time (DIRECTING_TIME_SPEC §4): the prompts you send agents, as minutes per day beside the watcher's.
// A shadow: nothing in the score reads it.
export function getDirectingSummary(days = 7, timeZone) {
  const params = new URLSearchParams({ days: String(days) });
  if (timeZone) params.set("tz", timeZone);
  return authRequest(`/apps/directing/summary?${params.toString()}`);
}
