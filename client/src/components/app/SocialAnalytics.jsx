import React, { useCallback, useEffect, useState } from "react";
import { getSocialAnalytics } from "../../api/social.js";
import { safeMap } from "../../utils/safe";
import { EmptyState } from "../shared/EmptyState";

// Replaces the former LinkedIn manual-ingest panel. That surface asked the user to type
// metrics in by hand and could never persist them (form fields never matched
// `LinkedInRawInput`, and the adapter behind it received a dict where it expected an
// object) — `canonical_metrics` held 0 rows. This reads the system-fed social engine
// instead: real posts, real impressions, no data entry.
//
// Palette matches KPIDashboard.jsx so the two analytics surfaces read as one system.
const C = {
  page: "#09090b",
  card: "#0d1117",
  cardInner: "#161b22",
  border: "#21262d",
  text0: "#c9d1d9",
  text1: "#8b949e",
  text2: "#6e7681",
  accent: "#00ffaa",
};

const SIGNAL_META = {
  success: { color: "#4caf50", glyph: "▲", label: "Working" },
  failure: { color: "#f44336", glyph: "▼", label: "Underperforming" },
  pattern: { color: "#6cf", glyph: "◆", label: "Pattern" },
};

const SIGNAL_COPY = {
  top_performing_content: "Best-performing post",
  low_engagement_content: "Seen but not engaged with",
  repeating_high_engagement_pattern: "Repeating high engagement",
};

function fmtNum(v, digits = 1) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
}

function fmtInt(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString() : "0";
}

function StatTile({ label, value, hint }) {
  return (
    <div style={{ background: C.cardInner, border: `1px solid ${C.border}`, borderRadius: 8, padding: "14px 16px" }}>
      <div style={{ fontSize: 22, color: C.text0, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 11, color: C.text1, textTransform: "uppercase", letterSpacing: "0.08em", marginTop: 4 }}>
        {label}
      </div>
      {hint ? <div style={{ fontSize: 10, color: C.text2, marginTop: 4 }}>{hint}</div> : null}
    </div>
  );
}

function Section({ title, subtitle, children }) {
  return (
    <section style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: "18px 20px", marginBottom: 18 }}>
      <div style={{ marginBottom: 14 }}>
        <h2 style={{ fontSize: 14, color: C.text0, margin: 0, fontWeight: 600 }}>{title}</h2>
        {subtitle ? <div style={{ fontSize: 11, color: C.text2, marginTop: 3 }}>{subtitle}</div> : null}
      </div>
      {children}
    </section>
  );
}

function SignalCard({ signal }) {
  const meta = SIGNAL_META[signal.type] || SIGNAL_META.pattern;
  const reason = SIGNAL_COPY[signal.reason] || signal.reason;
  return (
    <div
      style={{
        background: C.cardInner,
        border: `1px solid ${C.border}`,
        borderLeft: `3px solid ${meta.color}`,
        borderRadius: 6,
        padding: "10px 14px",
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
      }}
    >
      <span style={{ color: meta.color, fontSize: 12, lineHeight: "18px" }}>{meta.glyph}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, color: C.text0 }}>{reason}</div>
        {signal.content ? (
          <div style={{ fontSize: 11, color: C.text2, marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            “{signal.content}”
          </div>
        ) : null}
        {Number.isFinite(Number(signal.count)) && signal.count ? (
          <div style={{ fontSize: 11, color: C.text2, marginTop: 3 }}>{signal.count} posts</div>
        ) : null}
      </div>
      <span style={{ fontSize: 12, color: meta.color, fontWeight: 700, whiteSpace: "nowrap" }}>
        Eng {fmtNum(signal.engagement_score)}
      </span>
    </div>
  );
}

function TrendRow({ point, max }) {
  const impressions = Number(point.impressions) || 0;
  const pct = max > 0 ? Math.round((impressions / max) * 100) : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 12 }}>
      <span style={{ color: C.text1, minWidth: 82 }}>{point.date}</span>
      <div style={{ flex: 1, height: 6, background: C.border, borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: C.accent, borderRadius: 3, transition: "width 0.4s ease" }} />
      </div>
      <span style={{ color: C.text2, minWidth: 150, textAlign: "right" }}>
        {fmtInt(point.impressions)} impr · {fmtInt(point.clicks)} clicks · eng {fmtNum(point.avg_engagement_score)}
      </span>
    </div>
  );
}

export default function SocialAnalytics() {
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAnalytics(await getSocialAnalytics());
    } catch (e) {
      setError(e?.message || "Failed to load analytics.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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
          <div style={{ fontSize: 32, marginBottom: 12 }}>📈</div>
          <div>Loading analytics…</div>
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
            <div style={{ fontWeight: 700, marginBottom: 4 }}>Failed to load analytics</div>
            <div style={{ fontSize: 13 }}>{error}</div>
          </div>
          <button
            onClick={load}
            style={{ marginLeft: "auto", background: "transparent", border: "1px solid #fca5a5", borderRadius: 6, color: "#fca5a5", fontSize: 12, padding: "6px 14px", cursor: "pointer" }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const overview = analytics?.overview || {};
  const topPosts = analytics?.top_posts || [];
  const trend = analytics?.trend || [];
  const signals = analytics?.signals || [];
  const postCount = Number(overview.post_count) || 0;
  const maxImpressions = trend.reduce((m, p) => Math.max(m, Number(p.impressions) || 0), 0);

  return (
    <div style={containerStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.3em", color: C.accent, margin: 0 }}>
            Analytics
          </p>
          <h1 style={{ fontSize: 24, margin: "6px 0 0 0", fontWeight: 700 }}>Content Performance</h1>
          <p style={{ fontSize: 12, color: C.text2, margin: "6px 0 0 0" }}>
            Measured from your own posts and the interactions they receive. Nothing here is entered by hand.
          </p>
        </div>
        <button
          onClick={load}
          style={{ background: "transparent", border: `1px solid ${C.border}`, borderRadius: 6, color: C.text1, fontSize: 12, padding: "8px 16px", cursor: "pointer" }}
        >
          Refresh
        </button>
      </div>

      {postCount === 0 ? (
        <EmptyState
          message="No content activity yet."
          hint="Publish a post from the Social Feed — impressions, clicks and engagement start accruing from your first one."
        />
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 18 }}>
            <StatTile label="Posts" value={fmtInt(overview.post_count)} />
            <StatTile label="Impressions" value={fmtInt(overview.total_impressions)} />
            <StatTile label="Clicks" value={fmtInt(overview.total_clicks)} />
            <StatTile label="Avg Engagement" value={fmtNum(overview.avg_engagement_score)} hint="Per post" />
            <StatTile label="Avg Conversion" value={fmtNum(overview.avg_conversion_signal)} hint="Intent signal" />
          </div>

          {signals.length > 0 && (
            <Section title="Signals" subtitle="What the engine noticed about your content">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {safeMap(signals, (signal, i) => (
                  <SignalCard key={`${signal.reason}-${i}`} signal={signal} />
                ))}
              </div>
            </Section>
          )}

          {trend.length > 0 && (
            <Section title="Performance Trend" subtitle="Last 7 active days">
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {safeMap(trend, (point) => (
                  <TrendRow key={point.date} point={point} max={maxImpressions} />
                ))}
              </div>
            </Section>
          )}

          {topPosts.length > 0 && (
            <Section title="Top Content" subtitle="Ranked by engagement score">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {safeMap(topPosts, (post) => (
                  <div
                    key={post.id}
                    style={{ background: C.cardInner, border: `1px solid ${C.border}`, borderRadius: 6, padding: "10px 14px", display: "flex", alignItems: "center", gap: 12 }}
                  >
                    <span style={{ flex: 1, minWidth: 0, fontSize: 12, color: C.text0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {post.content}
                    </span>
                    <span style={{ fontSize: 11, color: C.text2, whiteSpace: "nowrap" }}>
                      {fmtInt(post.impressions)} impr · {fmtInt(post.clicks)} clicks
                    </span>
                    <span style={{ fontSize: 12, color: C.accent, fontWeight: 700, minWidth: 60, textAlign: "right" }}>
                      {fmtNum(post.engagement_score)}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </>
      )}
    </div>
  );
}
