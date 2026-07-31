import React, { useEffect, useState, useCallback } from "react";
import { getMyScore, recalculateScore, getScoreHistory, getThreeAxis } from "../../api/product.js";
import { safeMap } from "../../utils/safe";

// Palette matches Dashboard.jsx's InfinityScorePanel — this is the same score data on a
// dedicated surface, so the two should read as one system.
const C = {
  page: "#09090b",
  card: "#0d1117",
  cardInner: "#161b22",
  border: "#21262d",
  border2: "#30363d",
  text0: "#c9d1d9",
  text1: "#8b949e",
  text2: "#6e7681",
  accent: "#6cf",
};

// The five behavioral KPIs, in weight order. 50 = neutral baseline for every axis.
const KPI_META = {
  execution_speed: { label: "Execution Speed", blurb: "Completion velocity vs. your baseline" },
  decision_efficiency: { label: "Decision Efficiency", blurb: "Completion rate + ARM quality" },
  ai_productivity_boost: { label: "AI Productivity Boost", blurb: "ARM usage + code-quality trend" },
  focus_quality: { label: "Focus Quality", blurb: "Watcher sessions: duration, distractions" },
  masterplan_progress: { label: "MasterPlan Progress", blurb: "% tasks done + schedule" },
};

function scoreColor(score) {
  if (score >= 70) return "#4caf50";
  if (score >= 40) return "#ffc107";
  return "#f44336";
}

function fmtNum(v, digits = 1) {
  return Number.isFinite(v) ? v.toFixed(digits) : "—";
}

function fmtMoney(v) {
  if (!Number.isFinite(v)) return "$0";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

// ── Master score ring ─────────────────────────────────────────────────────────
function ScoreRing({ score }) {
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const filled = (score / 100) * circumference;
  const color = scoreColor(score);
  return (
    <svg width={130} height={130} style={{ display: "block", margin: "0 auto" }}>
      <circle cx={65} cy={65} r={radius} fill="none" stroke={C.border} strokeWidth={11} />
      <circle
        cx={65} cy={65} r={radius}
        fill="none" stroke={color} strokeWidth={11}
        strokeDasharray={`${filled} ${circumference}`}
        strokeLinecap="round"
        transform="rotate(-90 65 65)"
        style={{ transition: "stroke-dasharray 0.6s ease" }}
      />
      <text x={65} y={72} textAnchor="middle" fill={color} fontSize={26} fontWeight="bold">
        {Number.isFinite(score) ? score.toFixed(1) : "—"}
      </text>
    </svg>
  );
}

// ── One behavioral-KPI tile ────────────────────────────────────────────────────
function KpiTile({ label, blurb, value, weight }) {
  const val = Number.isFinite(value) ? value : 0;
  const color = scoreColor(val);
  return (
    <div style={{ background: C.cardInner, border: `1px solid ${C.border}`, borderRadius: 8, padding: "12px 14px" }}>
      <div style={{ fontSize: 12, color: C.text0, marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 10, color: C.text2, marginBottom: 8, minHeight: 24 }}>{blurb}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ flex: 1, height: 5, background: C.border, borderRadius: 3, overflow: "hidden", position: "relative" }}>
          <div style={{ width: `${val}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.4s ease" }} />
          {/* neutral-baseline marker at 50 */}
          <div style={{ position: "absolute", left: "50%", top: 0, width: 1, height: "100%", background: C.text2 }} />
        </div>
        <span style={{ fontSize: 13, color, fontWeight: "bold", minWidth: 36, textAlign: "right" }}>{fmtNum(val)}</span>
      </div>
      {weight != null && (
        <div style={{ fontSize: 10, color: C.text2, marginTop: 4 }}>{Math.round(weight * 100)}% of master</div>
      )}
    </div>
  );
}

// ── One axis tile (Volume / Worth / Trajectory) ─────────────────────────────────
function AxisTile({ title, score, children }) {
  const hasScore = Number.isFinite(score);
  const color = hasScore ? scoreColor(score) : C.text2;
  return (
    <div style={{ background: C.cardInner, border: `1px solid ${C.border}`, borderRadius: 8, padding: "14px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
        <span style={{ fontSize: 13, color: C.text0, fontWeight: 600 }}>{title}</span>
        <span style={{ fontSize: 20, color, fontWeight: "bold" }}>{hasScore ? score.toFixed(1) : "—"}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>{children}</div>
    </div>
  );
}

function AxisStat({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
      <span style={{ color: C.text1 }}>{label}</span>
      <span style={{ color: C.text0 }}>{value}</span>
    </div>
  );
}

// ── Score-history sparkline (bars colored by delta) ─────────────────────────────
function ScoreSparkline({ history }) {
  if (!history || history.length < 2) return null;
  return (
    <div>
      <div style={{ fontSize: 11, color: C.text1, marginBottom: 6 }}>Score history</div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 44 }}>
        {safeMap(history.slice().reverse(), (h, i) => {
          // Guard every numeric field — a single malformed row must not take down the panel.
          // score_delta is nullable (no prior on the first sample); `!= null` catches both.
          const score = Number.isFinite(h?.master_score) ? h.master_score : null;
          const delta = Number.isFinite(h?.score_delta) ? h.score_delta : null;
          const barH = Math.max(4, ((score ?? 0) / 100) * 44);
          const barColor = delta == null ? C.accent : delta >= 0 ? "#4caf50" : "#f44336";
          const scoreLabel = score == null ? "—" : score.toFixed(1);
          const deltaLabel = delta == null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`;
          return (
            <div key={i} title={`${scoreLabel} (${deltaLabel})`}
              style={{ flex: 1, height: barH, background: barColor, borderRadius: 2, transition: "height 0.3s ease" }} />
          );
        })}
      </div>
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────────
export default function KPIDashboard() {
  const [score, setScore] = useState(null);
  const [history, setHistory] = useState([]);
  const [axes, setAxes] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [recalculating, setRecalculating] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // /scores/me self-computes on first miss, so a brand-new user still gets a score.
      // The two secondary reads are best-effort: a failure in history or three-axis must
      // not blank the whole dashboard.
      const [s, h, a] = await Promise.all([
        getMyScore(),
        getScoreHistory(30).catch(() => ({ history: [] })),
        getThreeAxis().catch(() => null),
      ]);
      setScore(s);
      setHistory(h?.history || []);
      setAxes(a);
    } catch (e) {
      setError(e?.message || "Failed to load KPI data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const handleRecalculate = async () => {
    setRecalculating(true);
    try {
      const result = await recalculateScore();
      setScore(result);
      getScoreHistory(30).then((d) => setHistory(d?.history || [])).catch(() => {});
      getThreeAxis().then(setAxes).catch(() => {});
    } catch (e) {
      setError(e?.message || "Recalculate failed.");
    } finally {
      setRecalculating(false);
    }
  };

  const containerStyle = {
    minHeight: "100vh",
    background: C.page,
    color: C.text0,
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
    padding: "28px 32px",
    maxWidth: 1000,
    margin: "0 auto",
  };

  if (loading) {
    return (
      <div style={containerStyle}>
        <div style={{ textAlign: "center", padding: 80, color: C.text1 }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📊</div>
          <div>Loading your KPI snapshot…</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={containerStyle}>
        <div style={{ background: "#7f1d1d", borderRadius: 10, padding: "20px 24px", color: "#fca5a5", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 20 }}>⚠️</span>
          <div>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>Failed to load KPI snapshot</div>
            <div style={{ fontSize: 13 }}>{error}</div>
          </div>
          <button onClick={loadAll} style={{ marginLeft: "auto", background: "transparent", border: "1px solid #fca5a5", borderRadius: 6, color: "#fca5a5", fontSize: 12, padding: "6px 14px", cursor: "pointer" }}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const masterScore = score?.master_score ?? 0;
  const kpis = score?.kpis ?? {};
  const weights = score?.weights ?? {};
  const meta = score?.metadata ?? {};
  const hasKpis = Object.keys(kpis).length > 0;
  const volume = axes?.volume;
  const worth = axes?.worth;
  const trajectory = axes?.trajectory;

  return (
    <div style={containerStyle}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.3em", color: "#00ffaa", margin: 0 }}>
          KPI Snapshot
        </p>
        <h1 style={{ margin: "10px 0 0", fontSize: 28, fontWeight: 800 }}>Performance signals, from your own data</h1>
        <p style={{ marginTop: 6, color: C.text1, fontSize: 13, maxWidth: 640 }}>
          Derived live from your tasks, ARM analyses, focus sessions and revenue — not entered by hand.
        </p>
      </div>

      {/* Hero — master score */}
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: "22px 26px", marginBottom: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h2 style={{ margin: 0, color: C.accent, fontSize: 15 }}>Infinity Score</h2>
          <button onClick={handleRecalculate} disabled={recalculating}
            style={{ background: C.border, border: `1px solid ${C.border2}`, color: C.text0, borderRadius: 6, padding: "5px 14px", cursor: recalculating ? "not-allowed" : "pointer", fontSize: 12 }}>
            {recalculating ? "Calculating…" : "Recalculate"}
          </button>
        </div>

        <div style={{ textAlign: "center", marginBottom: 8 }}>
          <ScoreRing score={masterScore} />
          <div style={{ marginTop: 8, fontSize: 12, color: C.text1 }}>
            {meta.confidence && (
              <span style={{
                background: meta.confidence === "high" ? "#1a3a1a" : meta.confidence === "medium" ? "#3a2a00" : "#2a1a1a",
                color: meta.confidence === "high" ? "#4caf50" : meta.confidence === "medium" ? "#ffc107" : "#f44336",
                borderRadius: 4, padding: "2px 8px", marginRight: 8, fontSize: 11,
              }}>
                {meta.confidence} confidence
              </span>
            )}
            {meta.data_points_used != null && `${meta.data_points_used} signals`}
            {meta.calculated_at && ` · updated ${new Date(meta.calculated_at).toLocaleString()}`}
            {meta.trigger_event && ` · via ${meta.trigger_event}`}
          </div>
        </div>

        {/* Genuinely-empty state (self-compute already ran but there's no activity yet) */}
        {!hasKpis && (
          <p style={{ color: C.text1, fontSize: 13, textAlign: "center", marginTop: 12 }}>
            {score?.message || "Not enough activity yet — complete a few tasks to build your score."}
          </p>
        )}

        {history.length > 1 && (
          <div style={{ marginTop: 16 }}>
            <ScoreSparkline history={history} />
          </div>
        )}
      </div>

      {/* Row A — behavioral KPIs */}
      {hasKpis && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, color: C.text1, textTransform: "uppercase", letterSpacing: "0.15em", marginBottom: 10 }}>
            Behavioral KPIs
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
            {safeMap(Object.entries(KPI_META), ([key, { label, blurb }]) => (
              <KpiTile key={key} label={label} blurb={blurb} value={kpis[key]} weight={weights[key]} />
            ))}
          </div>
        </div>
      )}

      {/* Row B — three axes */}
      {axes && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, color: C.text1, textTransform: "uppercase", letterSpacing: "0.15em", marginBottom: 10 }}>
            Volume · Worth · Trajectory
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
            <AxisTile title="Volume" score={volume?.score}>
              <AxisStat label="Effort (hrs)" value={fmtNum(volume?.effort_hours)} />
              <AxisStat label="Completed" value={volume?.completed_count ?? "—"} />
              <AxisStat label="Window" value={volume?.window_days ? `${volume.window_days}d` : "—"} />
            </AxisTile>
            <AxisTile title="Trajectory" score={trajectory?.score}>
              <AxisStat label="Pace ratio" value={fmtNum(trajectory?.mean_pace_ratio, 2)} />
              <AxisStat label="Ahead / on-time / behind" value={`${trajectory?.ahead ?? 0} / ${trajectory?.on_time ?? 0} / ${trajectory?.behind ?? 0}`} />
              <AxisStat label="Tasks measured" value={trajectory?.tasks_measured ?? 0} />
            </AxisTile>
            <AxisTile title="Worth" score={worth?.score}>
              {/* $ and declared units are deliberately kept separate — never fake-combined. */}
              <AxisStat label="Realized revenue" value={fmtMoney(worth?.realized_revenue)} />
              <AxisStat label="Declared (units)" value={fmtNum(worth?.declared_total, 0)} />
              <AxisStat label="Declarations" value={worth?.declaration_count ?? 0} />
            </AxisTile>
          </div>
          <p style={{ fontSize: 10, color: C.text2, marginTop: 8 }}>
            Realized revenue is raw dollars; declared worth is in your own units — the two are shown side by side, never summed.
          </p>
        </div>
      )}
    </div>
  );
}
