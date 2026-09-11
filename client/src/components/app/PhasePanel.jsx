import { useEffect, useState } from "react";
import {
  getStrategyLayer,
  getPhaseAdvanceProposal,
  confirmPhaseAdvance,
  dismissPhaseAdvance,
  reopenPhase,
  createStrategy,
  startStrategy,
  finishStrategy,
  setStrategyObjective,
} from "../../api/masterplan.js";
import { safeMap } from "../../utils/safe";
import { describeHours } from "../../utils/effort.js";

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

// A strategy is how a phase gets done: weeks or months, and it finishes with a verdict.
// `abandoned` (tried, did not work — a result) and `displaced` (never tried, did something
// else — a choice) are different colours on purpose; collapsing them is the thing the layer
// exists to prevent.
const STRATEGY_COLOR = {
  proposed: "#71717a",
  active: "#facc15",
  concluded: "#00ffaa",
  abandoned: "#f87171",
  displaced: "#a78bfa",
};
const FINISHED = new Set(["concluded", "abandoned", "displaced"]);

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

function miniBtn(color) {
  return {
    background: "transparent", color, border: `1px solid ${color}60`, borderRadius: "4px",
    fontSize: "9px", padding: "1px 6px", cursor: "pointer", fontWeight: "700",
  };
}

function describeEvidence(proposal) {
  const ev = proposal.evidence || {};
  const parts = [];
  if (ev.strategies_total > 0) parts.push(`${ev.strategies_finished} of ${ev.strategies_total} ${ev.strategies_total === 1 ? "strategy" : "strategies"} finished`);
  if (ev.tasks_total > 0) parts.push(`${ev.tasks_completed} of ${ev.tasks_total} ${ev.tasks_total === 1 ? "task" : "tasks"} complete`);
  const summary = parts.join(", ");
  if (proposal.reason === "work_complete") {
    const early = ev.early_by_days;
    const when = typeof early === "number" && early > 0 ? `, ${early} days inside its window` : "";
    return `All of its work is done — ${summary}${when}.`;
  }
  if (proposal.reason === "window_elapsed") {
    const open = (ev.open_task_ids || []).length + (ev.open_strategy_ids || []).length;
    return `Its window has ended with ${open} ${open === 1 ? "thing" : "things"} still open (${summary}).`;
  }
  return "";
}

export default function PhasePanel({ planId }) {
  const [layer, setLayer] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(null);   // "confirm" | "dismiss" | "reopen" | "strategy" | null
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [newStrategy, setNewStrategy] = useState("");
  const [newStrategyObjective, setNewStrategyObjective] = useState("");
  const [verdictFor, setVerdictFor] = useState(null);   // strategy id with the verdict menu open

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

  const handleAddStrategy = async (phase) => {
    const name = newStrategy.trim();
    if (!name) return;
    const body = { name, phase_id: phase.id };
    if (newStrategyObjective) body.objective_id = newStrategyObjective;
    const result = await act("strategy", () => createStrategy(planId, body));
    if (result) setNewStrategy("");
  };

  // Which objective a strategy serves. The act that lets hours roll up to purpose — without
  // it the strategy's work lands in "unhoused" and no objective can report it.
  const handleServes = (st, objectiveId) =>
    act("strategy", () => setStrategyObjective(planId, st.id, objectiveId || null));

  const objectives = layer?.objectives || [];
  const rollup = layer?.objective_rollup || {};

  const handleStart = (st) => act("strategy", () => startStrategy(planId, st.id));

  const handleVerdict = async (st, verb, outcome) => {
    setVerdictFor(null);
    const result = await act("strategy", () => finishStrategy(planId, st.id, verb, { outcome }));
    if (result && typeof result.tasks_released === "number" && result.tasks_released > 0) {
      setNotice(`${st.name} ${verb === "abandon" ? "abandoned" : "displaced"}. ${result.tasks_released} open ${result.tasks_released === 1 ? "task" : "tasks"} returned to the plan; completed work stays attached.`);
    }
  };

  const strategiesOf = (phase) => (layer?.strategies || []).filter((st) => st.phase_id === phase.id);
  const stCounts = (st) => layer?.strategy_task_counts?.[st.id];

  // The one phase that can be reopened: the most recently closed one. The API refuses any
  // other, so the button is only drawn where it would work.
  const lastClosed = [...phases].reverse().find((p) => p.status === "complete");
  const nothingClosedAfter = lastClosed && !phases.some((p) => p.ordinal > lastClosed.ordinal && p.status === "complete");
  const reopenable = nothingClosedAfter ? lastClosed : null;

  return (
    <div style={{ marginTop: "12px", padding: "10px", background: "#111113", borderRadius: "6px", border: "1px solid #27272a" }}>
      {objectives.length > 0 &&
        <div data-testid="plan-objectives" style={{ marginBottom: "10px" }}>
          <div style={{ fontSize: "11px", color: "#71717a", fontWeight: "700", letterSpacing: "0.05em", marginBottom: "6px" }}>
            OBJECTIVES
          </div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "12px" }}>
            {safeMap(objectives, (o) => {
              const r = rollup[o.id];
              return (
                <li key={o.id} title={o.intent || undefined} style={{ display: "flex", alignItems: "baseline", gap: "8px", padding: "2px 0" }}>
                  <span style={{ color: "#e4e4e7" }}>{o.name}</span>
                  {r ?
                    <span style={{ fontSize: "10px", color: "#71717a" }}>
                      {r.strategies} {r.strategies === 1 ? "strategy" : "strategies"}
                      {r.hours_total > 0 ? ` · ${describeHours(r.hours_completed) || "0h"} of ${describeHours(r.hours_total)}` : ""}
                    </span> :
                    <span style={{ fontSize: "10px", color: "#52525b" }}>nothing serves this yet</span>
                  }
                </li>
              );
            })}
          </ul>
          {rollup.unhoused &&
            <p style={{ margin: "4px 0 0", fontSize: "11px", color: "#71717a" }}>
              {rollup.unhoused.strategies} {rollup.unhoused.strategies === 1 ? "strategy serves" : "strategies serve"} no objective{rollup.unhoused.hours_total > 0 ? ` — ${describeHours(rollup.unhoused.hours_completed) || "0h"} of ${describeHours(rollup.unhoused.hours_total)} that no objective can claim` : ""}.
            </p>
          }
        </div>
      }

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

      {/* Strategies of the current phase — how it gets done */}
      {proposal?.phase &&
        <div data-testid="phase-strategies" style={{ marginTop: "10px", paddingLeft: "16px", borderLeft: "1px solid #27272a" }}>
          <div style={{ fontSize: "10px", color: "#71717a", fontWeight: "700", letterSpacing: "0.05em", marginBottom: "4px" }}>
            STRATEGIES — {proposal.phase.name}
          </div>
          {strategiesOf(proposal.phase).length === 0 &&
            <p style={{ margin: "0 0 6px", fontSize: "11px", color: "#52525b" }}>
              None yet. A strategy is how this phase gets done — weeks or months, and it finishes with a verdict.
            </p>
          }
          <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "12px" }}>
            {safeMap(strategiesOf(proposal.phase), (st) => {
              const color = STRATEGY_COLOR[st.status] || STRATEGY_COLOR.proposed;
              const c = stCounts(st);
              return (
                <li key={st.id} style={{ display: "flex", alignItems: "center", gap: "8px", padding: "3px 0", flexWrap: "wrap" }}>
                  <span style={{ color: FINISHED.has(st.status) ? "#71717a" : "#e4e4e7" }}>{st.name}</span>
                  <span style={{ fontSize: "9px", color, border: `1px solid ${color}`, borderRadius: "4px", padding: "0 4px" }}>
                    {st.status}{st.outcome ? ` · ${st.outcome.replace(/_/g, " ")}` : ""}
                  </span>
                  {c &&
                    <span title="tasks complete / attached · hours done / estimated" style={{ fontSize: "10px", color: "#71717a" }}>
                      {c.completed}/{c.total} tasks{c.hours_total > 0 ? ` · ${describeHours(c.hours_completed) || "0h"} of ${describeHours(c.hours_total)}` : ""}
                    </span>
                  }
                  {objectives.length > 0 &&
                    <select
                      aria-label={`${st.name} serves`}
                      value={st.objective_id || ""}
                      onChange={(e) => handleServes(st, e.target.value)}
                      disabled={busy !== null}
                      title="Which objective this strategy serves. Its hours roll up there."
                      style={{ background: "#18181b", color: st.objective_id ? "#a1a1aa" : "#facc15", border: "1px solid #27272a", borderRadius: "4px", fontSize: "9px", padding: "1px 4px" }}>
                      <option value="">serves: —</option>
                      {safeMap(objectives, (o) => <option key={o.id} value={o.id}>serves: {o.name}</option>)}
                    </select>
                  }
                  {st.status === "proposed" &&
                    <button onClick={() => handleStart(st)} disabled={busy !== null} style={miniBtn("#facc15")}>START</button>
                  }
                  {!FINISHED.has(st.status) && verdictFor !== st.id &&
                    <button onClick={() => setVerdictFor(st.id)} disabled={busy !== null} style={miniBtn("#a1a1aa")}>FINISH…</button>
                  }
                  {verdictFor === st.id &&
                    <span data-testid="strategy-verdict" style={{ display: "inline-flex", gap: "4px", flexWrap: "wrap" }}>
                      <button onClick={() => handleVerdict(st, "conclude", "worked")} style={miniBtn("#00ffaa")} title="Tried it; it worked">WORKED</button>
                      <button onClick={() => handleVerdict(st, "conclude", "inconclusive")} style={miniBtn("#a1a1aa")} title="Tried it; cannot say">INCONCLUSIVE</button>
                      <button onClick={() => handleVerdict(st, "abandon")} style={miniBtn("#f87171")} title="Tried it; it did not work. A result.">DID NOT WORK</button>
                      <button onClick={() => handleVerdict(st, "displace")} style={miniBtn("#a78bfa")} title="Never tried; did something else instead. A choice, not a result.">DISPLACED</button>
                      <button onClick={() => setVerdictFor(null)} style={miniBtn("#52525b")}>×</button>
                    </span>
                  }
                </li>
              );
            })}
          </ul>
          <form
            onSubmit={(e) => { e.preventDefault(); handleAddStrategy(proposal.phase); }}
            style={{ display: "flex", gap: "6px", marginTop: "6px" }}>
            <input
              aria-label="New strategy"
              placeholder="Add a strategy…"
              value={newStrategy}
              onChange={(e) => setNewStrategy(e.target.value)}
              style={{ flex: 1, padding: "5px 8px", background: "#18181b", border: "1px solid #27272a", borderRadius: "4px", color: "#fff", fontSize: "11px" }} />
            {objectives.length > 0 &&
              <select
                aria-label="New strategy serves"
                value={newStrategyObjective}
                onChange={(e) => setNewStrategyObjective(e.target.value)}
                style={{ background: "#18181b", color: "#a1a1aa", border: "1px solid #27272a", borderRadius: "4px", fontSize: "10px", padding: "1px 4px" }}>
                <option value="">serves: —</option>
                {safeMap(objectives, (o) => <option key={o.id} value={o.id}>serves: {o.name}</option>)}
              </select>
            }
            <button type="submit" disabled={busy !== null || !newStrategy.trim()} style={miniBtn("#00ffaa")}>ADD</button>
          </form>
        </div>
      }
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
