import { useCallback, useEffect, useState } from "react";
import {
  deleteContentSource,
  detectRipples,
  detectRipplesForDropPoint,
  getContentSources,
  getRippleDropPoints,
  ingestContentUrl,
  pollContentSource,
  setContentSourceActive,
} from "../../api/rippletrace.js";
import { safeMap } from "../../utils/safe";

// Routes return the handler dict flat, but the pipeline envelope can also arrive
// wrapped in `data`. Read through both rather than betting on one shape.
function unwrap(response, key) {
  if (!response) return undefined;
  if (response[key] !== undefined) return response[key];
  if (response.data && response.data[key] !== undefined) return response.data[key];
  return undefined;
}

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function formatWhen(value) {
  if (!value) return "never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "unknown" : parsed.toLocaleString();
}

const STATUS_STYLES = {
  ok: "text-emerald-400",
  unchanged: "text-zinc-400",
  error: "text-red-400",
};

export default function RippleTrace() {
  const [url, setUrl] = useState("");
  const [sources, setSources] = useState([]);
  const [dropPoints, setDropPoints] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [suggestedFeeds, setSuggestedFeeds] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [sourceResponse, dropResponse] = await Promise.all([
        getContentSources(),
        getRippleDropPoints(),
      ]);
      setSources(asList(unwrap(sourceResponse, "sources")));
      // The drop points route returns a bare list.
      setDropPoints(
        asList(Array.isArray(dropResponse) ? dropResponse : unwrap(dropResponse, "data"))
      );
    } catch (err) {
      setError(err.message || "Failed to load tracked content");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleIngest(event, overrideUrl) {
    event?.preventDefault();
    const target = (overrideUrl ?? url).trim();
    if (!target) return;
    setBusy(true);
    setError("");
    setNotice("");
    setSuggestedFeeds([]);
    try {
      const response = await ingestContentUrl(target);
      const kind = unwrap(response, "kind");
      const created = unwrap(response, "created") ?? 0;
      const updated = unwrap(response, "updated") ?? 0;
      const feeds = asList(unwrap(response, "suggested_feeds"));
      setNotice(
        kind === "feed"
          ? `Feed registered — ${created} new, ${updated} already tracked. It will keep polling on its own.`
          : `Page tracked — ${created} new, ${updated} updated.`
      );
      setSuggestedFeeds(feeds);
      setUrl("");
      await load();
    } catch (err) {
      // The API returns a specific reason (bad scheme, non-public host, HTTP status);
      // showing it beats a generic failure, since the user can usually fix the URL.
      setError(err?.data?.detail?.message || err.message || "Could not ingest that URL");
    } finally {
      setBusy(false);
    }
  }

  async function handlePoll(sourceId) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await pollContentSource(sourceId);
      const created = unwrap(response, "created") ?? 0;
      const status = unwrap(response, "status");
      setNotice(
        status === "unchanged"
          ? "Nothing new since the last check."
          : `Checked — ${created} new drop point${created === 1 ? "" : "s"}.`
      );
      await load();
    } catch (err) {
      setError(err.message || "Could not check that source");
    } finally {
      setBusy(false);
    }
  }

  async function handleDetect(dropPointId) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = dropPointId
        ? await detectRipplesForDropPoint(dropPointId)
        : await detectRipples(5);
      const created = unwrap(response, "created") ?? 0;
      // A search that returns only your own site is working correctly, not failing —
      // say so, or "0 ripples" reads as a broken feature.
      const rejected = unwrap(response, "rejected");
      const filtered = rejected
        ? Object.values(rejected).reduce((total, count) => total + count, 0)
        : 0;
      setNotice(
        created > 0
          ? `Found ${created} new ripple${created === 1 ? "" : "s"}.`
          : filtered > 0
            ? `No new ripples — ${filtered} result${filtered === 1 ? "" : "s"} were your own pages or predate the post.`
            : "No new ripples found."
      );
      await load();
    } catch (err) {
      const detail = err?.data?.detail;
      setError(
        detail?.error === "mention_search_unavailable"
          ? detail.message
          : err.message || "Could not check for ripples"
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleToggle(source) {
    setBusy(true);
    try {
      await setContentSourceActive(source.id, !source.active);
      await load();
    } catch (err) {
      setError(err.message || "Could not update that source");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(sourceId) {
    setBusy(true);
    try {
      await deleteContentSource(sourceId);
      await load();
    } catch (err) {
      setError(err.message || "Could not remove that source");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-6 space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-zinc-100">RippleTrace</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Track what you publish elsewhere, so the system can measure what happened after.
        </p>
      </header>

      <form
        onSubmit={handleIngest}
        className="border border-zinc-800 rounded-lg bg-zinc-950/70 p-4 space-y-3"
      >
        <label htmlFor="ripple-url" className="block text-sm font-semibold text-zinc-100">
          Add published content
        </label>
        <p className="text-xs text-zinc-500">
          Paste an article URL, or a feed URL (Substack, Medium, Ghost, WordPress, a YouTube
          channel) to keep tracking everything you publish there. LinkedIn and X have no feeds,
          so those go in one link at a time.
        </p>
        <div className="flex gap-2">
          <input
            id="ripple-url"
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://yourblog.com/feed"
            className="flex-1 rounded-md border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600"
          />
          <button
            type="submit"
            disabled={busy || !url.trim()}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {busy ? "Working..." : "Track"}
          </button>
        </div>
        {error && <div className="text-xs text-red-400">{error}</div>}
        {notice && <div className="text-xs text-emerald-400">{notice}</div>}
        {suggestedFeeds.length > 0 && (
          <div className="text-xs text-zinc-400 space-y-1">
            <div>That site publishes a feed. Subscribe to keep it up to date automatically:</div>
            {safeMap(suggestedFeeds, (feed) => (
              <button
                key={feed}
                type="button"
                onClick={(event) => handleIngest(event, feed)}
                className="block text-blue-400 hover:text-blue-300 break-all"
              >
                {feed}
              </button>
            ))}
          </div>
        )}
      </form>

      <section className="border border-zinc-800 rounded-lg bg-zinc-950/70 p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-100">Sources</h2>
            <p className="text-xs text-zinc-500">Feeds polled hourly for new posts</p>
          </div>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="text-xs text-blue-400 hover:text-blue-300"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>

        {!loading && sources.length === 0 && (
          <div className="text-xs text-zinc-500">
            No feeds yet. Add one above and everything you publish there gets tracked on its own.
          </div>
        )}

        <div className="space-y-2">
          {safeMap(sources, (source) => (
            <div
              key={source.id}
              className="border border-zinc-800 rounded-md p-3 bg-zinc-900/70"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm text-zinc-100 truncate">
                    {source.title || source.feed_url}
                  </div>
                  <div className="text-[11px] text-zinc-500 mt-1 break-all">
                    {source.platform || "unknown"} · {source.feed_url}
                  </div>
                  <div className="text-[11px] mt-1">
                    <span className={STATUS_STYLES[source.last_status] || "text-zinc-500"}>
                      {source.last_status || "not checked yet"}
                    </span>
                    <span className="text-zinc-600">
                      {" "}
                      · last checked {formatWhen(source.last_polled_at)} ·{" "}
                      {source.ingested_count || 0} tracked
                      {source.active ? "" : " · paused"}
                    </span>
                  </div>
                  {source.last_error && (
                    <div className="text-[11px] text-red-400 mt-1">{source.last_error}</div>
                  )}
                </div>
                <div className="flex shrink-0 gap-3 text-xs">
                  <button
                    type="button"
                    onClick={() => handlePoll(source.id)}
                    disabled={busy}
                    className="text-blue-400 hover:text-blue-300 disabled:opacity-40"
                  >
                    Check now
                  </button>
                  <button
                    type="button"
                    onClick={() => handleToggle(source)}
                    disabled={busy}
                    className="text-zinc-400 hover:text-zinc-200 disabled:opacity-40"
                  >
                    {source.active ? "Pause" : "Resume"}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(source.id)}
                    disabled={busy}
                    className="text-red-400 hover:text-red-300 disabled:opacity-40"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="border border-zinc-800 rounded-lg bg-zinc-950/70 p-4">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-100">Tracked content</h2>
            <p className="text-xs text-zinc-500">
              Ripples are references to these elsewhere. Your own pages don't count, so scores
              stay at zero until someone else picks it up.
            </p>
          </div>
          <button
            type="button"
            onClick={() => handleDetect(null)}
            disabled={busy || dropPoints.length === 0}
            className="shrink-0 rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:border-zinc-500 disabled:opacity-40"
          >
            Check for ripples
          </button>
        </div>

        {!loading && dropPoints.length === 0 && (
          <div className="text-xs text-zinc-500">Nothing tracked yet.</div>
        )}

        <div className="space-y-2">
          {safeMap(dropPoints, (point) => (
            <div key={point.id} className="border border-zinc-800 rounded-md p-3 bg-zinc-900/70">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm text-zinc-100">{point.title}</div>
                  <div className="text-[11px] text-zinc-500 mt-1 break-all">
                    {point.platform || "unknown"} ·{" "}
                    {point.date_dropped ? formatWhen(point.date_dropped) : "date unknown"}
                    {point.url ? ` · ${point.url}` : ""}
                  </div>
                  <div className="text-[11px] text-zinc-600 mt-1">
                    narrative {Number(point.narrative_score || 0).toFixed(2)} · velocity{" "}
                    {Number(point.velocity_score || 0).toFixed(2)} · spread{" "}
                    {Number(point.spread_score || 0).toFixed(0)}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleDetect(point.id)}
                  disabled={busy}
                  className="shrink-0 text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40"
                >
                  Check
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
