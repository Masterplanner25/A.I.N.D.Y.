import { safeMap } from "../../utils/safe";

// The plan itself — what Genesis synthesized and the owner locked. Read-only.
//
// This is `structure_json`, and until now the only place it was ever rendered was the Genesis
// draft preview, *before* locking. Once a plan was locked the dashboard showed its metadata,
// its ETA and (since #329) its phases, and never the vision, the mechanism, the domains or
// the success criteria — the owner's own words for what the plan is. Extracted from
// `GenesisDraftPreview` so the draft and the locked plan render the same fields the same way,
// and so the preview cannot drift into showing something the dashboard does not.

export function Field({ label, value }) {
  return (
    <div>
      <p style={{ margin: "0 0 2px 0", color: "#71717a", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </p>
      <p style={{ margin: 0, color: "#f4f4f5" }}>{value || "—"}</p>
    </div>);
}

export function Section({ label, children }) {
  return (
    <div style={{ marginBottom: "16px" }}>
      <p style={{ margin: "0 0 8px 0", color: "#71717a", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </p>
      {children}
    </div>);
}

function pct(value) {
  return value != null ? `${Math.round(value * 100)}%` : "—";
}

export default function PlanStructure({ structure, compact = false }) {
  if (!structure) return null;

  const phases = structure.phases || [];
  const domains = structure.core_domains || [];
  const criteria = structure.success_criteria || [];
  const risks = structure.risk_factors || [];
  const assets = structure.key_assets || [];

  return (
    <div style={{ fontSize: compact ? "12px" : "13px" }}>
      {/* Core fields */}
      <div style={{ display: "grid", gridTemplateColumns: compact ? "1fr" : "1fr 1fr", gap: "12px", marginBottom: "20px" }}>
        <Field label="Vision" value={structure.vision_statement} />
        <Field label="Mechanism" value={structure.primary_mechanism} />
        <Field label="Horizon" value={structure.time_horizon_years ? `${structure.time_horizon_years} years` : "—"} />
        <Field label="Ambition" value={pct(structure.ambition_score)} />
        <Field label="Confidence" value={pct(structure.confidence_at_synthesis)} />
      </div>

      {domains.length > 0 &&
        <Section label="Core Domains">
          {safeMap(domains, (d, i) =>
            <div key={i} style={{ marginBottom: "6px" }}>
              <span style={{ color: "#00ffaa", fontWeight: "600" }}>{d.name}</span>
              {d.intent && <p style={{ color: "#a1a1aa", margin: "2px 0 0 0" }}>{d.intent}</p>}
            </div>)
          }
        </Section>
      }

      {phases.length > 0 &&
        <Section label="Phases">
          {safeMap(phases, (p, i) =>
            <div key={i} style={{ marginBottom: "8px" }}>
              <span style={{ color: "#00ffaa", fontWeight: "600" }}>{p.name}</span>
              {p.duration_months && <span style={{ color: "#71717a", marginLeft: "8px" }}>{p.duration_months}mo</span>}
              {p.description && <p style={{ color: "#a1a1aa", margin: "2px 0 0 0" }}>{p.description}</p>}
            </div>)
          }
        </Section>
      }

      {criteria.length > 0 &&
        <Section label="Success Criteria">
          <ul style={{ margin: 0, paddingLeft: "16px", color: "#a1a1aa" }}>
            {safeMap(criteria, (c, i) => <li key={i}>{typeof c === "string" ? c : c?.description || c?.name || JSON.stringify(c)}</li>)}
          </ul>
        </Section>
      }

      {assets.length > 0 &&
        <Section label="Key Assets">
          <ul style={{ margin: 0, paddingLeft: "16px", color: "#a1a1aa" }}>
            {safeMap(assets, (a, i) => <li key={i}>{typeof a === "string" ? a : a?.name || JSON.stringify(a)}</li>)}
          </ul>
        </Section>
      }

      {risks.length > 0 &&
        <Section label="Risk Factors">
          <ul style={{ margin: 0, paddingLeft: "16px", color: "#f87171" }}>
            {safeMap(risks, (r, i) => <li key={i}>{typeof r === "string" ? r : r?.description || JSON.stringify(r)}</li>)}
          </ul>
        </Section>
      }

      {structure.synthesis_notes &&
        <Section label="Synthesis Notes">
          <p style={{ margin: 0, color: "#a1a1aa", fontStyle: "italic" }}>{structure.synthesis_notes}</p>
        </Section>
      }
    </div>);
}
