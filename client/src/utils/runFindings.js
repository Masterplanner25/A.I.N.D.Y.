import { safeMap } from "./safe";

// What a completed agent run found, as text the next run's planner can read.
//
// A plan's steps cannot use each other's results (FR-46): every argument is written before any
// step runs. On 2026-09-25/26 that meant "research X, then use it" planned its second half blind,
// and the owner carried the findings into the next goal by hand, copied out of the database.
// Collaborator does the carrying instead: it digests the finished run's step results and attaches
// them to the follow-up goal, visibly, so the owner approves exactly what the planner will see.

// Separates the owner's words from the attached findings inside a goal. Kept distinctive so a
// goal can be split back apart for display; the planner reads it as plain text.
export const FINDINGS_MARKER = "\n\n--- Findings from the previous run (attached by Collaborator) ---\n";

// A research result alone is ~2 KB. The cap keeps a follow-up goal a size the planner prompt can
// carry without crowding out the plan, KPI and tool context around it.
export const MAX_FINDINGS_CHARS = 6000;

// Recall ranks the user's own nodes, most of which are system telemetry ("execution.started from
// masterplan.pace.propose"); they are never a finding.
const isTelemetry = (node) => String(node?.source || "").startsWith("system_event:");

const clean = (s) => String(s ?? "").trim();

// One step's findings as text, or null when the step found nothing worth carrying.
export function stepFindings(step) {
  const r = step?.result;
  if (!r || typeof r !== "object") return null;
  switch (step.tool_name) {
    case "research.query":
      return clean(r.raw_result) || null;
    case "memory.recall": {
      const notes = (Array.isArray(r.nodes) ? r.nodes : []).filter((n) => !isTelemetry(n));
      return notes.length ? safeMap(notes, (n) => `- ${clean(n.content)}`).join("\n") : null;
    }
    case "search.query": {
      const hits = (Array.isArray(r.results) ? r.results : []).filter((h) => h?.title || h?.snippet);
      return hits.length
        ? safeMap(hits, (h) => `- ${clean(h.title)}${h.snippet ? `: ${clean(h.snippet)}` : ""}${h.url ? ` (${h.url})` : ""}`).join("\n")
        : null;
    }
    case "arm.analyze":
      return clean(r.summary) || null;
    case "reasoning.evaluate":
      return r.decision_type
        ? `Recommendation: ${r.decision_type}${r.reason ? ` (because ${r.reason})` : ""}` +
            (r.next_action_title ? `\n${clean(r.next_action_title)}` : "")
        : null;
    case "task.create":
      return r.name ? `Created task: ${clean(r.name)}` : null;
    default:
      return null;
  }
}

// Every successful step's findings, labelled by tool, capped at MAX_FINDINGS_CHARS.
export function buildFindingsDigest(steps) {
  const succeeded = (Array.isArray(steps) ? steps : []).filter(
    (s) => String(s?.status || "").toLowerCase() === "success"
  );
  const sections = safeMap(succeeded, (s) => {
    const text = stepFindings(s);
    return text ? `[${s.tool_name}]\n${text}` : null;
  }).filter(Boolean);
  const digest = sections.join("\n\n");
  return digest.length > MAX_FINDINGS_CHARS
    ? `${digest.slice(0, MAX_FINDINGS_CHARS)}\n[truncated]`
    : digest;
}

export function composeFollowUpGoal(nextGoal, digest) {
  const ask = clean(nextGoal);
  return digest ? `${ask}${FINDINGS_MARKER}${digest}` : ask;
}

// The owner's words, and whether findings were attached — for showing a goal without the digest.
export function splitGoal(goal) {
  const text = String(goal ?? "");
  const at = text.indexOf(FINDINGS_MARKER);
  return at === -1
    ? { ask: text, hasFindings: false }
    : { ask: text.slice(0, at), hasFindings: true };
}
