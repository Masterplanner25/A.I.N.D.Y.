import { authRequest } from "./_core.js";
import { ROUTES } from "./_routes.js";

export function runResearch(query, summary) {
  return authRequest(ROUTES.SEARCH.RESEARCH_QUERY, {
    method: "POST",
    body: JSON.stringify({ query, summary }),
  });
}

/**
 * Record a feedback signal against one search result.
 *
 * Fire-and-forget by contract: the caller must never await this in a path that affects what
 * the user sees. Feedback is telemetry — a failure to record it is not a failure the user
 * should ever learn about, and must not delay or block navigating to the result.
 *
 * Idempotent server-side per (user, query, result_ref, signal), so repeat clicks are safe.
 */
export function recordSearchFeedback(query, resultRef, signal) {
  return authRequest(ROUTES.SEARCH.FEEDBACK, {
    method: "POST",
    body: JSON.stringify({ query, result_ref: resultRef, signal }),
  });
}

export function getSearchHistory(searchType = null, limit = 25) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (searchType) params.append("search_type", searchType);
  return authRequest(`${ROUTES.SEARCH.HISTORY}?${params.toString()}`, { method: "GET" });
}

export function getSearchHistoryItem(historyId) {
  return authRequest(ROUTES.SEARCH.HISTORY_ITEM(historyId), { method: "GET" });
}

export function deleteSearchHistoryItem(historyId) {
  return authRequest(ROUTES.SEARCH.HISTORY_ITEM(historyId), { method: "DELETE" });
}

export function runLeadGen(query) {
  return authRequest(`${ROUTES.SEARCH.LEAD_GEN}?query=${encodeURIComponent(query)}`, {
    method: "POST",
  });
}

export function analyzeSeo(content, title, targetKeywords) {
  // Both extras are optional and omitted when empty, so the request stays byte-identical to
  // the previous one for callers that do not pass them.
  const body = { content };
  if (title) body.title = title;
  if (targetKeywords?.length) body.target_keywords = targetKeywords;
  return authRequest(ROUTES.SEARCH.ANALYZE_SEO, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function generateMeta(content) {
  return authRequest(ROUTES.SEARCH.GENERATE_META, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function generateTitles(content, currentTitle, targetKeywords) {
  return authRequest(ROUTES.SEARCH.GENERATE_TITLE, {
    method: "POST",
    body: JSON.stringify({
      text: content,
      current_title: currentTitle || null,
      target_keywords: targetKeywords || null,
    }),
  });
}

export function suggestSeoImprovements(content) {
  return authRequest(ROUTES.SEARCH.SUGGEST_IMPROVEMENTS, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

// ── Drafts ────────────────────────────────────────────────────────────────────────────
//
// A draft holds its own content, title and target keywords, so `analyzeDraft` sends no body
// beyond the knob: two analyses of one draft are guaranteed to have been measured against the
// same targets, which is what makes them comparable.

export function listDrafts() {
  return authRequest(ROUTES.SEARCH.DRAFTS, { method: "GET" });
}

export function createDraft(payload) {
  return authRequest(ROUTES.SEARCH.DRAFTS, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDraft(draftId) {
  return authRequest(`${ROUTES.SEARCH.DRAFTS}/${draftId}`, { method: "GET" });
}

export function updateDraft(draftId, payload) {
  return authRequest(`${ROUTES.SEARCH.DRAFTS}/${draftId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteDraft(draftId) {
  return authRequest(`${ROUTES.SEARCH.DRAFTS}/${draftId}`, { method: "DELETE" });
}

export function analyzeDraft(draftId) {
  return authRequest(`${ROUTES.SEARCH.DRAFTS}/${draftId}/analyze`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function pruneDraftAnalyses(draftId, analysisIds) {
  return authRequest(`${ROUTES.SEARCH.DRAFTS}/${draftId}/prune`, {
    method: "POST",
    body: JSON.stringify({ analysis_ids: analysisIds }),
  });
}
