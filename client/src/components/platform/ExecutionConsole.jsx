import { useState, useEffect, useCallback } from "react";
import { getFlowRuns, getObservabilityRequests, getExecutionGraph } from "../../api/operator.js";
import { useAuth } from "../../context/AuthContext";
import { AdminAccessRequired } from "../shared/AdminApiErrorBoundary";
import { safeMap } from "../../utils/safe";

// ── Design tokens (platform dark theme) ──────────────────────────────────────
const C = {
  page: "#0d1117",
  card: "#161b22",
  cardInner: "#0d1117",
  border: "#21262d",
  border2: "#30363d",
  text0: "#c9d1d9",
  text1: "#8b949e",
  text2: "#6e7681",
  accent: "#00ffaa",
  link: "#6cf",
};

const STATUS_COLORS = {
  completed: "#4caf50",
  success: "#4caf50",
  running: "#6cf",
  in_progress: "#6cf",
  waiting: "#ffc107",
  paused: "#ffc107",
  failed: "#f44336",
  error: "#f44336",
};

const STATUS_FILTERS = [
  { id: "all", label: "All" },
  { id: "running", label: "Running" },
  { id: "waiting", label: "Waiting" },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed" },
];

function statusColor(status) {
  return STATUS_COLORS[String(status || "").toLowerCase()] || C.text1;
}

function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

function fmtDuration(start, end) {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

// ── Header pulse — live request throughput ───────────────────────────────────
function RequestPulse({ summary }) {
  if (!summary) return null;
  const tiles = [
    { label: `Requests (${summary.window_hours ?? 24}h)`, value: summary.window_requests ?? 0, color: C.link },
    { label: `Errors (${summary.window_hours ?? 24}h)`, value: summary.window_errors ?? 0, color: (summary.window_errors ?? 0) > 0 ? "#f44336" : "#4caf50" },
    { label: "Avg latency", value: summary.avg_latency_ms != null ? `${Math.round(summary.avg_latency_ms)}ms` : "—", color: C.text0 },
    { label: "Total requests", value: summary.total_requests ?? 0, color: C.text0 },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 24 }}>
      {safeMap(tiles, (t) => (
        <div key={t.label} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 16px" }}>
          <div style={{ fontSize: 11, color: C.text1, marginBottom: 6 }}>{t.label}</div>
          <div style={{ fontSize: 24, fontWeight: 800, color: t.color }}>{t.value}</div>
        </div>
      ))}
    </div>
  );
}

// ── Execution-graph trace detail for one run ─────────────────────────────────
function TraceDetail({ traceId }) {
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    getExecutionGraph(traceId)
      .then((g) => { if (mounted) setGraph(g); })
      .catch((e) => { if (mounted) setError(e?.message || "Failed to load execution graph."); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [traceId]);

  if (loading) return <div style={{ color: C.text1, fontSize: 12, padding: "10px 0" }}>Loading trace…</div>;
  if (error) return <div style={{ color: "#f44336", fontSize: 12, padding: "10px 0" }}>{error}</div>;

  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const insights = Array.isArray(graph?.insights) ? graph.insights : [];
  if (nodes.length === 0) return <div style={{ color: C.text2, fontSize: 12, padding: "10px 0" }}>No execution nodes recorded for this trace.</div>;

  const ordered = nodes
    .slice()
    .sort((a, b) => new Date(a?.timestamp || 0).getTime() - new Date(b?.timestamp || 0).getTime());

  return (
    <div style={{ padding: "8px 0 4px" }}>
      <div style={{ fontSize: 11, color: C.text1, marginBottom: 8 }}>
        Execution trace · {nodes.length} node{nodes.length !== 1 ? "s" : ""}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {safeMap(ordered, (n, i) => (
          <div key={n?.id || i} style={{ display: "flex", gap: 10, alignItems: "baseline", fontSize: 12 }}>
            <span style={{ color: C.text2, fontFamily: "monospace", minWidth: 92 }}>
              {n?.timestamp ? new Date(n.timestamp).toLocaleTimeString() : "—"}
            </span>
            <span style={{ color: C.accent, minWidth: 8 }}>•</span>
            <span style={{ color: C.text0 }}>{n?.type || n?.node_kind || "event"}</span>
            {n?.source && <span style={{ color: C.text2 }}>({n.source})</span>}
            {n?.payload?.current_node && <span style={{ color: C.text2 }}>→ {n.payload.current_node}</span>}
          </div>
        ))}
      </div>
      {insights.length > 0 && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 11, color: C.text1, marginBottom: 4 }}>Insights</div>
          {safeMap(insights, (ins, i) => (
            <div key={i} style={{ fontSize: 12, color: C.text0 }}>
              {typeof ins === "string" ? ins : JSON.stringify(ins)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── One flow-run row (expandable to its trace) ───────────────────────────────
function RunRow({ run, expanded, onToggle }) {
  const color = statusColor(run?.status);
  const duration = fmtDuration(run?.created_at, run?.completed_at);
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, marginBottom: 8, overflow: "hidden" }}>
      <button
        onClick={onToggle}
        style={{
          width: "100%", background: expanded ? C.cardInner : C.card, border: "none", textAlign: "left",
          padding: "12px 16px", cursor: run?.trace_id ? "pointer" : "default", color: C.text0,
          display: "flex", alignItems: "center", gap: 12,
        }}
      >
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />
        <span style={{ fontWeight: 600, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {run?.flow_name || "unknown flow"}
        </span>
        <span style={{ fontSize: 11, color, textTransform: "uppercase", letterSpacing: "0.06em" }}>{run?.status || "—"}</span>
        <span style={{ flex: 1 }} />
        {run?.waiting_for && <span style={{ fontSize: 11, color: "#ffc107" }}>waiting: {run.waiting_for}</span>}
        {run?.current_node && !run?.completed_at && <span style={{ fontSize: 11, color: C.text2 }}>@ {run.current_node}</span>}
        {duration && <span style={{ fontSize: 11, color: C.text2 }}>{duration}</span>}
        <span style={{ fontSize: 11, color: C.text2 }}>{fmtTime(run?.created_at)}</span>
        {run?.trace_id && <span style={{ fontSize: 11, color: C.text2 }}>{expanded ? "▲" : "▼"}</span>}
      </button>
      {run?.error_message && (
        <div style={{ padding: "0 16px 10px", fontSize: 12, color: "#f44336" }}>{run.error_message}</div>
      )}
      {expanded && run?.trace_id && (
        <div style={{ padding: "0 16px 12px", background: C.cardInner }}>
          <TraceDetail traceId={run.trace_id} />
        </div>
      )}
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────
export default function ExecutionConsole() {
  const { isAdmin } = useAuth();
  if (!isAdmin) return <AdminAccessRequired />;
  return <ExecutionConsoleContent />;
}

function ExecutionConsoleContent() {
  const [summary, setSummary] = useState(null);
  const [runs, setRuns] = useState([]);
  const [filter, setFilter] = useState("all");
  const [expandedId, setExpandedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async (statusFilter) => {
    setLoading(true);
    setError(null);
    try {
      const statusArg = statusFilter === "all" ? null : statusFilter;
      const [reqs, runsResp] = await Promise.all([
        getObservabilityRequests(24, 50).catch(() => null),
        getFlowRuns(statusArg, null, 50),
      ]);
      setSummary(reqs?.summary ?? null);
      setRuns(Array.isArray(runsResp?.runs) ? runsResp.runs : []);
    } catch (e) {
      setError(e?.message || "Failed to load executions.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(filter); }, [load, filter]);

  const containerStyle = {
    maxWidth: 960, margin: "0 auto", padding: "20px 24px",
    background: C.page, color: C.text0, minHeight: "100vh",
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
  };

  return (
    <div style={containerStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <h2 style={{ margin: 0, color: C.accent, fontSize: 18 }}>Execution Console</h2>
        <button onClick={() => load(filter)} disabled={loading}
          style={{ background: C.card, border: `1px solid ${C.border2}`, color: C.text0, borderRadius: 6, padding: "5px 14px", cursor: loading ? "not-allowed" : "pointer", fontSize: 12 }}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      <p style={{ color: C.text1, fontSize: 13, marginTop: 0, marginBottom: 20 }}>
        Live flow runs and request throughput across the platform. Select a run to see its execution trace.
      </p>

      <RequestPulse summary={summary} />

      {/* Status filter */}
      <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
        {safeMap(STATUS_FILTERS, (f) => (
          <button key={f.id} onClick={() => { setFilter(f.id); setExpandedId(null); }}
            style={{
              padding: "6px 14px", borderRadius: 6, fontSize: 12, cursor: "pointer",
              background: filter === f.id ? "#1f6feb" : "transparent",
              color: filter === f.id ? "#fff" : C.text1,
              border: `1px solid ${filter === f.id ? "#1f6feb" : C.border}`,
            }}>
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <div style={{ background: "#3a1a1a", border: "1px solid #f4433644", borderRadius: 8, padding: "12px 16px", color: "#fca5a5", fontSize: 13, marginBottom: 14 }}>
          {error}
        </div>
      )}

      {!loading && runs.length === 0 && !error && (
        <div style={{ color: C.text2, fontSize: 13, textAlign: "center", padding: "40px 0" }}>
          No flow runs {filter !== "all" ? `with status "${filter}"` : "yet"}.
        </div>
      )}

      {safeMap(runs, (run) => (
        <RunRow
          key={run?.id}
          run={run}
          expanded={expandedId === run?.id}
          onToggle={() => run?.trace_id && setExpandedId(expandedId === run?.id ? null : run?.id)}
        />
      ))}
    </div>
  );
}
