import { useEffect, useState } from "react";
import {
  getStrategyLayer,
  getPhaseAdvanceProposal,
  confirmPhaseAdvance,
  dismissPhaseAdvance,
  reopenPhase,
} from "../../api/masterplan.js";
import { safeMap } from "../../utils/safe";

// The plan's phases, and what the system has to say about the current one.
//
// STRATEGY_LAYER_SPEC §8 step 3b. The layer was real data nobody could see; this is the first
// thing that renders it. The proposal card is the house pattern — system proposes, human
// confirms — or declines. The first live proposal drew "what if the phase isn't complete?", so
// the card has two buttons, and "not done" is the one that records something the plan did
// not know: that its phase is under-described. There is deliberately no "close phase" button
// without a proposal behind it — the API refuses that too — and the only undo is reopening
// the most recently closed phase.

const PHASE_COLOR = {
  complete: "#00ffaa",
  active: "#facc15",
  pending: "#3f3f46",
};

// The API's 409 arrives as ApiError with the raw body; the useful sentence is in
// detail.message. Fall back to whatever message there is.
function refusalMessage(err) {
  try {
    const parsed = JSON.parse(err?.body || "");
    return parsed?.detail?.message || parsed?.detail || err?.message;
  } catch {
    return err?.message || "Could not confirm.";
  }
}

function describeEvidence(proposal) {
  const ev = proposal.evidence || {};
  if (proposal.reason === "work_complete") {
    const early = ev.early_by_days;
    const when = typeof early === "number" && early > 0 ? `, ${early} days inside its window` : "";
    return `All ${ev.tasks_total} of its tasks are complete${when}.`;
  }
  if (proposal.reason === "window_elapsed") {
    const open = (ev.open_task_ids || []).length;
    const work = open === 1 ? "1 task still open" : `${open} tasks still open`;
    return `Its window has ended with ${work} (${ev.tasks_completed} of ${ev.tasks_total} complete).`;
  }
  return "";
}

export default function PhasePanel({ planId }) {
  const [layer, setLayer] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(null);   // "confirm" | "dismiss" | "reopen" | null
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = async () => {
    try {
      const [layerData, proposalData] = await Promise.all([
        getStrategyLayer(planId),
        getPhaseAdvanceProposal(planId),
      ]);
      setLayer(layerData);
      setProposal(proposalData);
    } catch {
      // A plan that predates the layer has nothing here, and that is not an error worth
      // a red box on a card that is mostly about other things.
      setLayer(null);
      setProposal(null);
    }
  };

  useEffect(() => { load(); }, [planId]);

  const phases = layer?.phases || [];
  if (phases.length === 0) return null;

  const act = async (kind, call) => {
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      const result = await call();
      await load();
      return result;
    } catch (err) {
      setError(refusalMessage(err));
      return null;
    } finally {
      setBusy(null);
    }
  };

  const handleConfirm = async () => {
    if (!proposal?.phase?.id) return;
    const result = await act("confirm", () => confirmPhaseAdvance(planId, proposal.phase.id));
    if (result) setReview(result);
  };

  const handleDismiss = async () => {
    if (!proposal?.phase?.id) return;
    const result = await act("dismiss", () => dismissPhaseAdvance(planId, proposal.phase.id));
    if (result) {
      setNotice(`Noted. ${proposal.phase.name} stays open — the proposal comes back when its tasks change, so attach the work that is missing.`);
    }
  };

  const handleReopen = async (phase) => {
    const result = await act("reopen", () => reopenPhase(planId, phase.id));
    if (result) {
      setReview(null);
      setNotice(`${phase.name} reopened.${result.stepped_back ? ` ${result.stepped_back.name} is pending again.` : ""}`);
    }
  };

  // The one phase that can be reopened: the most recently closed one. The API refuses any
  // other, so the button is only drawn where it would work.
  const lastClosed = [...phases].reverse().find((p) => p.status === "complete");
  const nothingClosedAfter = lastClosed && !phases.some((p) => p.ordinal > lastClosed.ordinal && p.status === "complete");
  const reopenable = nothingClosedAfter ? lastClosed : null;

  return (
    <div style={{ marginTop: "12px", padding: "10px", background: "#111113", borderRadius: "6px", border: "1px solid #27272a" }}>
      <div style={{ fontSize: "11px", color: "#71717a", fontWeight: "700", letterSpacing: "0.05em", marginBottom: "8px" }}>
        PHASES
      </div>

      <ol style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "12px" }}>
        {safeMap(phases, (phase) => {
          const color = PHASE_COLOR[phase.status] || PHASE_COLOR.pending;
          const isCurrent = proposal?.phase?.id === phase.id;
          return (
            <li key={phase.id} style={{ display: "flex", alignItems: "center", gap: "8px", padding: "3px 0" }}>
              <span aria-hidden="true" style={{
                width: "8px", height: "8px", borderRadius: "50%", flexShrink: 0,
                background: phase.status === "pending" ? "transparent" : color,
                border: `1px solid ${color}`,
              }} />
              <span style={{ color: phase.status === "pending" ? "#71717a" : "#e4e4e7", fontWeight: isCurrent ? "700" : "400" }}>
                {phase.ordinal}. {phase.name}
              </span>
              {layer?.task_counts?.[phase.id] &&
                <span title="tasks complete / attached" style={{ fontSize: "10px", color: "#71717a" }}>
                  {layer.task_counts[phase.id].completed}/{layer.task_counts[phase.id].total}
                </span>
              }
              {phase.status !== "pending" &&
                <span style={{ fontSize: "9px", color, border: `1px solid ${color}`, borderRadius: "4px", padding: "0 4px" }}>
                  {phase.status}
                </span>
              }
              {isCurrent && phase.status === "pending" &&
                <span style={{ fontSize: "9px", color: "#a1a1aa" }}>current</span>
              }
              {reopenable?.id === phase.id &&
                <button
                  onClick={() => handleReopen(phase)}
                  disabled={busy !== null}
                  title="Reverse the confirmation. Tasks stay where they are."
                  style={{ marginLeft: "auto", background: "transparent", color: "#71717a", border: "1px solid #3f3f46", borderRadius: "4px", fontSize: "9px", padding: "1px 6px", cursor: "pointer" }}>
                  {busy === "reopen" ? "..." : "REOPEN"}
                </button>
              }
            </li>
          );
        })}
      </ol>
      {layer?.task_counts?.unphased &&
        <p style={{ margin: "6px 0 0", fontSize: "11px", color: "#71717a" }}>
          {layer.task_counts.unphased.total} {layer.task_counts.unphased.total === 1 ? "task" : "tasks"} on this plan {layer.task_counts.unphased.total === 1 ? "has" : "have"} no phase and {layer.task_counts.unphased.total === 1 ? "does" : "do"} not count toward one.
        </p>
      }

      {proposal?.proposed &&
        <div data-testid="phase-advance-proposal" style={{ marginTop: "10px", padding: "10px", background: "rgba(250, 204, 21, 0.05)", border: "1px solid #facc1540", borderRadius: "6px" }}>
          <p style={{ margin: "0 0 4px", fontSize: "12px", color: "#facc15", fontWeight: "700" }}>
            {proposal.phase.name} looks done.
          </p>
          <p style={{ margin: "0 0 8px", fontSize: "12px", color: "#a1a1aa" }}>
            {describeEvidence(proposal)}
            {proposal.next_phase && ` Confirming opens ${proposal.next_phase.name}.`}
          </p>
          <div style={{ display: "flex", gap: "8px" }}>
            <button
              onClick={handleConfirm}
              disabled={busy !== null}
              style={{
                flex: 1, padding: "7px", backgroundColor: "#18181b", color: "#facc15",
                border: "1px solid #facc1560", borderRadius: "6px", cursor: "pointer",
                fontWeight: "700", fontSize: "11px",
              }}>
              {busy === "confirm" ? "CONFIRMING..." : "CONFIRM — CLOSE PHASE"}
            </button>
            <button
              onClick={handleDismiss}
              disabled={busy !== null}
              title="The phase is not done. The proposal comes back when its tasks change."
              style={{
                flex: 1, padding: "7px", backgroundColor: "transparent", color: "#a1a1aa",
                border: "1px solid #3f3f46", borderRadius: "6px", cursor: "pointer",
                fontWeight: "700", fontSize: "11px",
              }}>
              {busy === "dismiss" ? "..." : "NOT DONE"}
            </button>
          </div>
        </div>
      }

      {proposal?.dismissed && !proposal.proposed &&
        <p data-testid="phase-advance-dismissed" style={{ margin: "8px 0 0", fontSize: "11px", color: "#71717a" }}>
          You said {proposal.phase.name} is not done, with {proposal.dismissed.task_count} {proposal.dismissed.task_count === 1 ? "task" : "tasks"} attached. The question returns when that changes.
        </p>
      }

      {notice &&
        <p data-testid="phase-advance-notice" style={{ margin: "8px 0 0", fontSize: "11px", color: "#a1a1aa" }}>{notice}</p>
      }
      {error &&
        <p style={{ margin: "8px 0 0", fontSize: "11px", color: "#f87171" }}>{error}</p>
      }

      {review &&
        <div data-testid="phase-advance-review" style={{ marginTop: "10px", padding: "10px", background: "rgba(0, 255, 170, 0.04)", border: "1px solid #14532d", borderRadius: "6px", fontSize: "12px", color: "#a1a1aa" }}>
          <p style={{ margin: "0 0 4px", color: "#00ffaa", fontWeight: "700" }}>
            {review.completed?.name} closed.
          </p>
          {review.activated &&
            <p style={{ margin: "2px 0" }}>{review.activated.name} is now active.</p>
          }
          {typeof review.review?.early_by_days === "number" && review.review.early_by_days > 0 &&
            <p style={{ margin: "2px 0" }}>
              Finished {review.review.early_by_days} days early — worth a look at whether what comes next can start sooner.
            </p>
          }
          {(review.review?.moved_task_ids || []).length > 0 &&
            <p style={{ margin: "2px 0" }}>
              {review.review.moved_task_ids.length} open {review.review.moved_task_ids.length === 1 ? "task" : "tasks"} moved into {review.activated?.name || "the next phase"} — the work that did not happen when the plan said it would.
            </p>
          }
        </div>
      }
    </div>
  );
}
