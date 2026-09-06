import { safeMap } from "../../utils/safe";
import { recordSearchFeedback } from "../../api/search.js";

function toPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Math.round(Number(value) * 100);
}

function ScoreBadge({ value, label = "score", tone = "emerald" }) {
  const pct = toPercent(value);
  if (pct === null) return null;
  const tones = {
    emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
    blue: "bg-blue-500/10 text-blue-300 border-blue-500/30",
    zinc: "bg-zinc-700/40 text-zinc-300 border-zinc-600/40",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${tones[tone] || tones.zinc}`}
      title={`${label}: ${pct}%`}
    >
      {label} {pct}
    </span>
  );
}

/**
 * Renders a unified, ranked SearchResponse.results list (Evolution Plan — v5).
 * Each item follows the shared SearchResultItem shape: { title, url, snippet,
 * score, metadata: { relevance, quality_score, ... } }.
 *
 * ★ Opening a result emits a `click` feedback signal (Search v4 §8). This is
 * INSTRUMENTATION, not a UI feature — nothing is added to the page and the user is never
 * asked to rate anything. Four of the six feedback signals the backend understands are
 * implicit (click 0.3, dwell 0.5, convert 1.0, dismiss -0.3); only thumbs up/down are
 * explicit, and those are the signals a user supplies least often. The ranking service,
 * the aggregation and the route have existed since Search v4 §8 with nothing calling them,
 * so `search_result_feedback` had 0 rows and AINDY_SEARCH_OUTCOME_WEIGHTING had no input.
 *
 * `query` is optional: without it a signal cannot be attributed to a query (the weights are
 * aggregated per query), so the component silently records nothing rather than sending a
 * useless row. Existing callers that do not pass it keep working unchanged.
 */
export default function SearchResults({
  results = [],
  searchScore = null,
  title = "Ranked Results",
  query = null,
}) {
  if (!Array.isArray(results) || results.length === 0) return null;

  const handleResultOpen = (item) => {
    // Fire-and-forget, and deliberately NOT awaited: this runs in an anchor's onClick, and
    // the browser navigates immediately. Awaiting would either delay the navigation or be
    // abandoned mid-flight. `.catch` is mandatory — an unhandled rejection here would
    // surface as a console error on a link click, and feedback failing is not something the
    // user should ever be told about.
    if (!query || !item?.url) return;
    try {
      recordSearchFeedback(query, item.url, "click")?.catch?.(() => {});
    } catch {
      // A synchronous throw (bad route config, missing token) must not stop the link.
    }
  };

  return (
    <div className="border border-zinc-800 rounded-lg bg-zinc-950/70 p-4 mt-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-100">{title}</h3>
        <ScoreBadge value={searchScore} label="overall" tone="blue" />
      </div>

      <ol className="space-y-2">
        {safeMap(results, (item, index) => (
          <li
            key={item.url || `${item.title}-${index}`}
            className="border border-zinc-800 rounded-md p-3 bg-zinc-900/70"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-zinc-600 font-mono">#{index + 1}</span>
                  {item.url ? (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={() => handleResultOpen(item)}
                      className="text-sm text-blue-400 hover:text-blue-300 truncate"
                    >
                      {item.title}
                    </a>
                  ) : (
                    <span className="text-sm text-zinc-100 truncate">{item.title}</span>
                  )}
                </div>
                {item.snippet ? (
                  <p className="text-xs text-zinc-400 mt-1 leading-relaxed">{item.snippet}</p>
                ) : null}
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                <ScoreBadge value={item.score} label="rank" tone="emerald" />
                <ScoreBadge value={item.metadata?.relevance} label="rel" tone="zinc" />
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
