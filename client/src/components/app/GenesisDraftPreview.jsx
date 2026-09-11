/**
 * GenesisDraftPreview — Phase 3 editable preview of a synthesized MasterPlan draft.
 * Block 4: Strategic Integrity Audit panel added.
 * Receives a draft object, sessionId, onLock callback from Genesis.jsx.
 */
import { useState } from "react";
import { auditGenesisDraft } from "../../api/masterplan.js";
import { safeMap } from "../../utils/safe";
import PlanStructure from "./PlanStructure.jsx";

const SEVERITY_COLORS = {
  critical: "#f87171",
  warning: "#fbbf24",
  advisory: "#60a5fa"
};

export default function GenesisDraftPreview({ draft, sessionId, onLock, locking }) {
  const [auditing, setAuditing] = useState(false);
  const [auditResult, setAuditResult] = useState(null);
  const [auditError, setAuditError] = useState(null);

  if (!draft) return null;

  async function handleAudit() {
    setAuditing(true);
    setAuditResult(null);
    setAuditError(null);
    try {
      const result = await auditGenesisDraft(sessionId);
      setAuditResult(result);
    } catch (err) {
      setAuditError(err.message || "Audit failed.");
    } finally {
      setAuditing(false);
    }
  }

  return (
    <div style={{
      padding: "24px",
      border: "1px solid #27272a",
      borderRadius: "12px",
      background: "#0c0c0e",
      color: "#f4f4f5",
      fontSize: "13px"
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "700" }}>
          DRAFT <span style={{ color: "#00ffaa" }}>MASTERPLAN</span>
        </h3>
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            onClick={handleAudit}
            disabled={auditing || locking}
            style={{
              padding: "10px 18px",
              backgroundColor: "transparent",
              color: auditing ? "#71717a" : "#fbbf24",
              border: "1px solid #3f3f46",
              borderRadius: "8px",
              cursor: auditing || locking ? "not-allowed" : "pointer",
              fontWeight: "700",
              fontSize: "12px"
            }}>

            {auditing ? "AUDITING..." : "AUDIT DRAFT"}
          </button>
          <button
            onClick={onLock}
            disabled={locking}
            style={{
              padding: "10px 20px",
              backgroundColor: locking ? "#27272a" : "#fff",
              color: "#000",
              border: "none",
              borderRadius: "8px",
              cursor: locking ? "not-allowed" : "pointer",
              fontWeight: "800",
              fontSize: "12px"
            }}>

            {locking ? "LOCKING..." : "LOCK PLAN"}
          </button>
        </div>
      </div>

      {/* The plan itself — the same component the dashboard renders once it is locked */}
      <PlanStructure structure={draft} />

      {/* Audit error */}
      {auditError &&
      <div style={{
        marginTop: "16px",
        padding: "12px",
        background: "#1a0a0a",
        border: "1px solid #7f1d1d",
        borderRadius: "8px",
        color: "#f87171",
        fontSize: "12px"
      }}>
          Audit error: {auditError}
        </div>
      }

      {/* Audit results panel */}
      {auditResult &&
      <div style={{
        marginTop: "20px",
        padding: "16px",
        background: "#0f0f13",
        border: `1px solid ${auditResult.audit_passed ? "#14532d" : "#7f1d1d"}`,
        borderRadius: "10px"
      }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <span style={{ fontWeight: "700", fontSize: "13px" }}>
              AUDIT{" "}
              <span style={{ color: auditResult.audit_passed ? "#4ade80" : "#f87171" }}>
                {auditResult.audit_passed ? "PASSED" : "FAILED"}
              </span>
            </span>
            <span style={{ color: "#71717a", fontSize: "12px" }}>
              Confidence: {auditResult.overall_confidence != null ?
            `${Math.round(auditResult.overall_confidence * 100)}%` :
            "—"}
            </span>
          </div>

          {auditResult.audit_summary &&
        <p style={{ margin: "0 0 12px 0", color: "#a1a1aa", fontSize: "12px", fontStyle: "italic" }}>
              {auditResult.audit_summary}
            </p>
        }

          {auditResult.findings && auditResult.findings.length > 0 ?
        <div>
              {safeMap(auditResult.findings, (f, i) =>
          <div key={i} style={{
            marginBottom: "10px",
            padding: "10px",
            background: "#18181b",
            borderRadius: "6px",
            borderLeft: `3px solid ${SEVERITY_COLORS[f.severity] || "#71717a"}`
          }}>
                  <div style={{ display: "flex", gap: "8px", marginBottom: "4px", alignItems: "center" }}>
                    <span style={{
                padding: "2px 8px",
                borderRadius: "4px",
                fontSize: "10px",
                fontWeight: "700",
                textTransform: "uppercase",
                background: SEVERITY_COLORS[f.severity] ? `${SEVERITY_COLORS[f.severity]}22` : "#27272a",
                color: SEVERITY_COLORS[f.severity] || "#71717a"
              }}>
                      {f.severity}
                    </span>
                    <span style={{ color: "#71717a", fontSize: "11px", textTransform: "uppercase" }}>
                      {f.type}
                    </span>
                  </div>
                  <p style={{ margin: "0 0 4px 0", color: "#f4f4f5", fontSize: "12px" }}>{f.description}</p>
                  {f.recommendation &&
            <p style={{ margin: 0, color: "#71717a", fontSize: "11px" }}>
                      Rec: {f.recommendation}
                    </p>
            }
                </div>)
          }
            </div> :

        <p style={{ margin: 0, color: "#4ade80", fontSize: "12px" }}>No findings — draft is structurally clean.</p>
        }
        </div>
      }
    </div>);

}
