import { useCallback, useEffect, useState } from "react";
import { confirmPace, dismissPace, getPaceProposal } from "../../api/masterplan.js";
import { safeMap } from "../../utils/safe";

// The plan's pace: ETA drift read against its posture's tolerance, as a proposal. The house
// pattern — system proposes, human confirms, or declines. `retarget` moves the target date to
// the projected completion (a refine); "NOTED" quiets the proposal until the drift moves past
// the tolerance again. Re-posturing is named in the evidence, never offered: revise-class, and
// /revise does not exist yet. Nothing here re-sequences anything.

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function describe(proposal) {
  const ev = proposal?.evidence || {};
  const days = ev.days_ahead_behind;
  if (days == null) return "No projection yet.";
  const abs = Math.abs(days);
  const dir = days < 0 ? "behind" : "ahead of";
  return `Projected ${abs} ${abs === 1 ? "day" : "days"} ${dir} the target (${fmtDate(ev.target_date)} → ${fmtDate(ev.projected_completion_date)}). ` +
    `${ev.posture || "Stable"} posture tolerates ${ev.tolerance_days} days.`;
}

export default function PacePanel({ planId }) {
  const [proposal, setProposal] = useState(null);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => getPaceProposal(planId), [planId]);

  useEffect(() => {
    let alive = true;
    load()
      .then((data) => {
        if (alive) {
          setProposal(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (alive) setError(err?.message || "Could not read the pace.");
      });
    return () => {
      alive = false;
    };
  }, [load]);

  const act = async (label, call) => {
    setBusy(label);
    setError(null);
    try {
      const result = await call();
      setProposal(await load());
      return result;
    } catch (err) {
      setError(err?.message || `Could not ${label}.`);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const handleRetarget = async () => {
    const result = await act("confirm", () => confirmPace(planId, "retarget"));
    if (result) setNotice(`Target moved to ${fmtDate(result.target_date_to)}.`);
  };

  const handleDismiss = async () => {
    const result = await act("dismiss", () => dismissPace(planId));
    if (result) setNotice("Noted. The proposal returns when the pace changes.");
  };

  if (!proposal && !error) return null;

  const ev = proposal?.evidence || {};
  const retarget = (proposal?.options || []).find((o) => o.decision === "retarget");
  const named = (proposal?.options || []).filter((o) => o.decision === null);

  return (
    <div data-testid="pace-panel" style={{ marginTop: "12px", padding: "10px", background: "#111113", borderRadius: "6px", border: "1px solid #27272a" }}>
      <div style={{ fontSize: "11px", color: "#71717a", fontWeight: "700", letterSpacing: "0.05em", marginBottom: "6px" }}>
        PACE
      </div>

      {error && <p style={{ margin: "0 0 6px", fontSize: "12px", color: "#f87171" }}>{error}</p>}
      {notice && <p style={{ margin: "0 0 6px", fontSize: "12px", color: "#a1a1aa" }}>{notice}</p>}

      {proposal && !proposal.proposed && (
        <p style={{ margin: 0, fontSize: "12px", color: "#a1a1aa" }}>
          {proposal.reason === "no_projection" && "Pace unknown — the ETA has no projection yet."}
          {proposal.reason === "low_confidence" && `Pace uncertain (${ev.eta_confidence} confidence) — ${describe(proposal)}`}
          {proposal.reason === "within_tolerance" && `On pace. ${describe(proposal)}`}
          {proposal.dismissed && ` Noted on ${fmtDate(proposal.dismissed.at)}; returns when the drift moves.`}
        </p>
      )}

      {proposal?.proposed && (
        <div data-testid="pace-proposal" style={{ padding: "10px", background: "rgba(250, 204, 21, 0.05)", border: "1px solid #facc1540", borderRadius: "6px" }}>
          <p style={{ margin: "0 0 4px", fontSize: "12px", color: "#facc15", fontWeight: "700" }}>
            {proposal.direction === "behind" ? "The plan is behind its pace." : "The plan is ahead of its pace."}
          </p>
          <p style={{ margin: "0 0 8px", fontSize: "12px", color: "#a1a1aa" }}>{describe(proposal)}</p>
          {named.length > 0 && (
            <ul style={{ margin: "0 0 8px 16px", padding: 0, fontSize: "11px", color: "#71717a" }}>
              {safeMap(named, (o, i) => (
                <li key={i}>{o.label} — a revise; not offered here.</li>
              ))}
            </ul>
          )}
          <div style={{ display: "flex", gap: "8px" }}>
            {retarget && (
              <button
                onClick={handleRetarget}
                disabled={busy !== null}
                title={`Move the target date to ${fmtDate(retarget.consequence?.target_date_to)}. A refine — the plan keeps its identity.`}
                style={{
                  flex: 1, padding: "7px", backgroundColor: "#18181b", color: "#facc15",
                  border: "1px solid #facc1560", borderRadius: "6px", cursor: "pointer",
                  fontWeight: "700", fontSize: "11px",
                }}>
                {busy === "confirm" ? "CONFIRMING..." : `RETARGET TO ${fmtDate(retarget.consequence?.target_date_to).toUpperCase()}`}
              </button>
            )}
            <button
              onClick={handleDismiss}
              disabled={busy !== null}
              title="Keep the target. The proposal comes back when the drift moves past the tolerance."
              style={{
                flex: 1, padding: "7px", backgroundColor: "transparent", color: "#a1a1aa",
                border: "1px solid #3f3f46", borderRadius: "6px", cursor: "pointer",
                fontWeight: "700", fontSize: "11px",
              }}>
              {busy === "dismiss" ? "..." : "NOTED"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
