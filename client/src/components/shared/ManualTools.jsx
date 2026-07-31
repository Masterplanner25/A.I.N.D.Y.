import React from "react";
import { Link } from "react-router-dom";
import { safeMap } from "../../utils/safe";

// Revenue & growth calculators
import IncomeEfficiencyPanel from "../app/IncomeEfficiencyPanel";
import RevenueScalingPanel from "../app/RevenueScalingPanel";
import BusinessGrowthPanel from "../app/BusinessGrowthPanel";
import MonetizationEfficiencyPanel from "../app/MonetizationEfficiencyPanel";
import LostPotentialPanel from "../app/LostPotentialPanel";
import AttentionValuePanel from "../app/AttentionValuePanel";
// Audience & impact calculators
import EngagementPanel from "../app/EngagementPanel";
import ImpactPanel from "../app/ImpactPanel";
import EngagementRatePanel from "../app/EngagementRatePanel";
import AIEfficiencyPanel from "../app/AIEfficiencyPanel";

// These are what-if calculators: you type numbers and they compute a formula. Nothing is read
// from — or written back to — your account. They were moved off /kpi (now a system-fed dashboard)
// and parked here. The three name-colliding calculators (Execution Speed, Decision Efficiency,
// AI Productivity Boost) were removed because /kpi computes real system-fed versions of them.
const SECTIONS = [
  {
    title: "Revenue & growth",
    panels: [
      ["income-efficiency", IncomeEfficiencyPanel],
      ["revenue-scaling", RevenueScalingPanel],
      ["business-growth", BusinessGrowthPanel],
      ["monetization-efficiency", MonetizationEfficiencyPanel],
      ["lost-potential", LostPotentialPanel],
      ["attention-value", AttentionValuePanel],
    ],
  },
  {
    title: "Audience & impact",
    panels: [
      ["engagement", EngagementPanel],
      ["impact", ImpactPanel],
      ["engagement-rate", EngagementRatePanel],
      ["ai-efficiency", AIEfficiencyPanel],
    ],
  },
];

export default function ManualTools() {
  const containerStyle = {
    minHeight: "100vh",
    background: "#09090b",
    color: "#c9d1d9",
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
    padding: "28px 32px",
    maxWidth: 1000,
    margin: "0 auto",
  };

  return (
    <div style={containerStyle}>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.3em", color: "#00ffaa", margin: 0 }}>
          Manual Tools
        </p>
        <h1 style={{ margin: "10px 0 0", fontSize: 28, fontWeight: 800, color: "#fff" }}>Scratch-pad calculators</h1>
      </div>

      {/* Honesty banner — these are NOT connected to your data */}
      <div style={{
        background: "#161b22",
        border: "1px solid #30363d",
        borderLeft: "3px solid #ffc107",
        borderRadius: 8,
        padding: "12px 16px",
        marginBottom: 24,
        fontSize: 13,
        color: "#8b949e",
      }}>
        These compute a formula from numbers you type — nothing is read from or saved to your
        account. For metrics derived live from your own activity, see{" "}
        <Link to="/kpi" style={{ color: "#6cf", textDecoration: "none", fontWeight: 600 }}>KPI Snapshot</Link>.
      </div>

      {/* Sections */}
      {safeMap(SECTIONS, (section) => (
        <div key={section.title} style={{ marginBottom: 28 }}>
          <div style={{ fontSize: 11, color: "#8b949e", textTransform: "uppercase", letterSpacing: "0.15em", marginBottom: 12 }}>
            {section.title}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
            {safeMap(section.panels, ([key, Panel]) => (
              <Panel key={key} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
