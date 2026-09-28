import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createAgentRun,
  getAgentRun,
  getAgentRuns,
  approveAgentRun,
  rejectAgentRun,
  getAgentRunSteps,
} from "../../api/agent.js";
import { Toast } from "../shared/Toast";
import { useToast } from "../../utils/useToast";
import { safeMap } from "../../utils/safe";
import Genesis from "./Genesis";
import WorkPanel from "./WorkPanel";
import MarketPanel from "./MarketPanel";
import StepResult from "./StepResult";
import { buildFindingsDigest, composeFollowUpGoal, splitGoal } from "../../utils/runFindings";

// The user-facing face for the agent: goal -> plan -> approve -> execute -> result.
// Sits on the same agent HTTP surface the admin console uses (client/src/api/agent.js),
// but scoped to a single conversational run for a normal user. See BUILD_PLAN Track 1.

const TERMINAL = new Set([
  "completed", "failed", "verify_failed", "dead_letter", "cancelled", "rejected",
]);
const AWAITING = new Set(["pending_approval", "awaiting_approval"]);

const STATUS_LABEL = {
  pending_approval: "Awaiting approval",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  executing: "Executing",
  completed: "Completed",
  failed: "Failed",
  rejected: "Rejected",
};
const STATUS_COLOR = {
  pending_approval: "text-amber-300 border-amber-500/30 bg-amber-500/10",
  awaiting_approval: "text-amber-300 border-amber-500/30 bg-amber-500/10",
  approved: "text-sky-300 border-sky-500/30 bg-sky-500/10",
  executing: "text-[#00ffaa] border-[#00ffaa]/30 bg-[#00ffaa]/10",
  completed: "text-emerald-300 border-emerald-500/30 bg-emerald-500/10",
  failed: "text-red-300 border-red-500/30 bg-red-500/10",
  rejected: "text-zinc-400 border-zinc-600/40 bg-zinc-700/20",
};
const RISK_COLOR = {
  low: "text-emerald-300 bg-emerald-500/10",
  medium: "text-amber-300 bg-amber-500/10",
  high: "text-red-300 bg-red-500/10",
};

const Badge = ({ status }) =>
  !status ? null : (
    <span className={`px-2 py-0.5 rounded-sm text-[10px] font-bold uppercase tracking-wider border ${STATUS_COLOR[status] || "text-zinc-400 border-zinc-700 bg-zinc-800/40"}`}>
      {STATUS_LABEL[status] || status.replace(/_/g, " ")}
    </span>
  );

const Risk = ({ risk }) =>
  !risk ? null : (
    <span className={`px-2 py-0.5 rounded-sm text-[10px] font-bold uppercase tracking-wider ${RISK_COLOR[risk] || RISK_COLOR.high}`}>
      {risk} risk
    </span>
  );

const EXAMPLES = [
  "Create three tasks for my launch: draft the announcement, schedule the posts, set up the landing page",
  "Research the top approaches to onboarding, then save a note summarizing them",
  "Recall what I already know about my launch plan",
];

export default function Assistant() {
  const [goal, setGoal] = useState("");
  const [run, setRun] = useState(null);
  const [steps, setSteps] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [approving, setApproving] = useState(false);
  const [followUp, setFollowUp] = useState("");
  const [attachFindings, setAttachFindings] = useState(true);
  const [showFindings, setShowFindings] = useState(false);
  const [recentRuns, setRecentRuns] = useState([]);
  const { toast, showToast, clearToast } = useToast();

  // The open run lives in the URL (`?run=<id>`), not only in component state. Held in state
  // alone, it was gone the moment the owner left the page (2026-09-26), including a run still
  // awaiting approval. A reload, back or a bookmark now reopens it; the empty screen lists
  // recent runs for a return through the nav link, which carries no `?run=`.
  const [searchParams, setSearchParams] = useSearchParams();
  const runParam = searchParams.get("run");
  const setRunParam = (id) => {
    const next = new URLSearchParams(searchParams);
    if (id) next.set("run", id);
    else next.delete("run");
    setSearchParams(next, { replace: true });
  };

  // The agent surface returns three different shapes: the create/approve responses wrap the
  // run in an execution envelope (run_id under execution_record, plan under result.plan,
  // UPPERCASE status), while GET /runs/{id} returns a flat detail row (run_id + plan at the
  // top level, lowercase status). Reading only the flat shape left runId undefined after a
  // create, so the poll never started, the plan never showed, and Approve did nothing — the
  // run looked stuck at "planning". Derive robustly from whichever shape we're holding.
  const runId = run?.run_id ?? run?.execution_record?.run_id ?? null;
  const status = (run?.status || "").toLowerCase();
  const awaiting = AWAITING.has(status);
  const terminal = TERMINAL.has(status);
  const planSteps = (run?.plan?.steps ?? run?.result?.plan?.steps) || [];
  const liveSteps = steps.length ? steps : planSteps;

  // Poll the run + its steps every 2s while it is non-terminal. When the status flips
  // to a terminal state, `terminal` changes and the effect tears the interval down.
  useEffect(() => {
    if (!runId || terminal) return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        // Both reads before either write. setRun can flip the run terminal, which tears this
        // effect down and sets `cancelled` — reading steps after it dropped the FINAL steps, the
        // only ones carrying results, and a completed run kept the previous tick's (2026-09-26).
        const r = await getAgentRun(runId);
        // /runs/{id}/steps returns { data: [...] }, not a bare array — unwrap it, else
        // steps never populated and the run showed the static plan the whole time.
        const s = await getAgentRunSteps(runId).catch(() => []);
        if (cancelled) return;
        const stepList = Array.isArray(s) ? s : Array.isArray(s?.data) ? s.data : [];
        if (stepList.length) setSteps(stepList);
        setRun(r);
      } catch (e) {
        if (!cancelled) showToast(e?.message || "Lost the run — check your connection.");
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [runId, terminal, showToast]);

  // Open the run the URL names — on arrival, reload, back/forward, or a link.
  useEffect(() => {
    if (!runParam || runParam === runId) return undefined;
    let cancelled = false;
    getAgentRun(runParam)
      .then((r) => {
        if (cancelled) return;
        setSteps([]);
        setRun(r);
      })
      .catch(() => {
        if (!cancelled) showToast("That run could not be opened.");
      });
    return () => {
      cancelled = true;
    };
  }, [runParam, runId, showToast]);

  // A finished run is never polled, so a reopened one loads its steps (and their results) once.
  useEffect(() => {
    if (!runId || !terminal || steps.length) return undefined;
    let cancelled = false;
    getAgentRunSteps(runId)
      .then((s) => {
        if (!cancelled && Array.isArray(s)) setSteps(s);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [runId, terminal, steps.length]);

  // Recent runs for the empty screen: the way back to a run after leaving the page.
  const idle = !run;
  useEffect(() => {
    if (!idle) return undefined;
    let cancelled = false;
    getAgentRuns(null, 8)
      .then((runs) => {
        if (!cancelled) setRecentRuns(Array.isArray(runs) ? runs : []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [idle]);

  const openRun = (r) => {
    setSteps([]);
    setRun(r);
    setRunParam(r?.run_id);
  };

  const startRun = async (goalText) => {
    if (!goalText.trim() || submitting) return;
    setSubmitting(true);
    setSteps([]);
    setRun(null);
    setFollowUp("");
    setShowFindings(false);
    try {
      const r = await createAgentRun({ goal: goalText.trim() });
      setRun(r); // the poll effect picks up runId and takes over
      setRunParam(r?.run_id ?? r?.execution_record?.run_id);
    } catch (e) {
      showToast(e?.message || "Couldn't start — is the agent reachable?");
    } finally {
      setSubmitting(false);
    }
  };

  const submit = (e) => {
    e?.preventDefault?.();
    return startRun(goal);
  };

  // What this run found, ready to hand to the next one (FR-46: a run cannot pass its own results
  // between steps, so Collaborator carries them between runs, visibly).
  const findings = status === "completed" ? buildFindingsDigest(steps) : "";
  const continueRun = (e) => {
    e?.preventDefault?.();
    if (!followUp.trim()) return;
    return startRun(composeFollowUpGoal(followUp, attachFindings ? findings : ""));
  };

  const approve = async () => {
    if (!runId || approving) return;
    setApproving(true);
    try {
      const r = await approveAgentRun(runId);
      setRun(r); // poll effect keeps running (runId unchanged, not terminal)
    } catch (e) {
      showToast(e?.message || "Approve failed.");
    } finally {
      setApproving(false);
    }
  };

  const reject = async () => {
    if (!runId) return;
    try {
      const r = await rejectAgentRun(runId);
      setRun(r); // terminal -> poll effect stops on its own
    } catch (e) {
      showToast(e?.message || "Reject failed.");
    }
  };

  const reset = () => {
    setRun(null);
    setSteps([]);
    setGoal("");
    setRunParam(null);
  };

  // Awaiting your approval first (a run that cannot move until you act), then newest first.
  const orderedRecent = [...recentRuns].sort((a, b) => {
    const wa = AWAITING.has(String(a?.status || "").toLowerCase()) ? 0 : 1;
    const wb = AWAITING.has(String(b?.status || "").toLowerCase()) ? 0 : 1;
    return wa - wb || String(b?.created_at || "").localeCompare(String(a?.created_at || ""));
  });

  // Mode: one face, two engines — "agent" (do X) or "genesis" (author/revise the plan).
  // Driven by ?mode=genesis so it's linkable (e.g. the MasterPlan "Initialize via Genesis" entry).
  // Four modes, one face: "agent" (do X), "genesis" (author the plan), "work" (what you have made
  // and how it fits: WORK_MODEL_SPEC §4), "market" (who it is for: MARKET_MODEL_SPEC §4).
  const modeParam = searchParams.get("mode");
  const PANEL_MODES = ["genesis", "work", "market"];
  const mode = PANEL_MODES.includes(modeParam) ? modeParam : "agent";
  // Switching modes keeps `?run=`, so going to Plan and back returns to the same run.
  const setMode = (m) => {
    const next = new URLSearchParams(searchParams);
    if (PANEL_MODES.includes(m)) next.set("mode", m);
    else next.delete("mode");
    setSearchParams(next, { replace: true });
  };

  const modeBar = (
    <div className="fixed top-3 left-1/2 -translate-x-1/2 z-30 flex gap-1 rounded-full border border-zinc-800 bg-zinc-950/90 p-1 shadow-lg shadow-black/40 backdrop-blur-sm">
      {safeMap([
        ["agent", "Agent"],
        ["genesis", "Plan"],
        ["work", "Work"],
        ["market", "Market"],
      ], ([m, label]) => (
        <button
          key={m}
          onClick={() => setMode(m)}
          className={`rounded-full px-4 py-1.5 text-[11px] font-bold uppercase tracking-wider transition-colors ${
            mode === m ? "bg-[#00ffaa] text-black" : "text-zinc-400 hover:text-zinc-200"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );

  // ── Market mode: who your work is for, and where they are ──
  if (mode === "market") {
    return (
      <div className="min-h-screen bg-[#09090b] text-zinc-100 flex justify-center">
        {modeBar}
        <div className="w-full max-w-2xl px-6 py-16">
          <MarketPanel />
        </div>
      </div>
    );
  }

  // ── Work mode: what you have made, in your words, and how it fits ──
  if (mode === "work") {
    return (
      <div className="min-h-screen bg-[#09090b] text-zinc-100 flex justify-center">
        {modeBar}
        <div className="w-full max-w-2xl px-6 py-16">
          <WorkPanel />
        </div>
      </div>
    );
  }

  // ── Plan mode: the Genesis plan-authoring engine, folded into the one face ──
  if (mode === "genesis") {
    return (
      <>
        {modeBar}
        <Genesis />
      </>
    );
  }

  // ── Empty state: the prompt ──
  if (!run) {
    return (
      <div className="min-h-screen bg-[#09090b] text-zinc-100 flex justify-center">
        {modeBar}
        <div className="w-full max-w-2xl px-6 py-16 flex flex-col">
          <div className="my-auto">
            <h1 className="text-3xl font-bold tracking-tighter text-white">
              Ask <span className="text-[#00ffaa]">A.I.N.D.Y.</span>
            </h1>
            <p className="text-zinc-500 mt-3 mb-8 max-w-md">
              Tell the agent a goal. It plans the steps, waits for your approval, then executes and reports back.
            </p>
            <form onSubmit={submit} className="space-y-3">
              <textarea
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
                }}
                placeholder="e.g. Create three tasks for my launch…"
                rows={3}
                className="w-full bg-zinc-900/60 border border-zinc-800 rounded-xl px-4 py-3 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-hidden focus:border-[#00ffaa]/50 resize-none custom-scrollbar"
              />
              <button
                type="submit"
                disabled={!goal.trim() || submitting}
                className="w-full px-4 py-3 rounded-xl bg-[#00ffaa] text-black text-sm font-bold uppercase tracking-wider hover:bg-[#00ffaa]/80 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {submitting ? "Starting…" : "Run"}
              </button>
            </form>
            {runParam && (
              <p className="mt-6 text-xs text-zinc-500 font-mono animate-pulse">Opening run…</p>
            )}
            {orderedRecent.length > 0 && (
              <div className="mt-8 space-y-2">
                <p className="text-[10px] uppercase tracking-wider text-zinc-600">Recent runs</p>
                {safeMap(orderedRecent, (r) => (
                  <button
                    key={r.run_id}
                    onClick={() => openRun(r)}
                    className="flex w-full items-center gap-3 text-left border border-zinc-800/60 hover:border-zinc-700 rounded-lg px-3 py-2 transition-colors"
                  >
                    <span className="flex-1 truncate text-xs text-zinc-300">{splitGoal(r.goal).ask}</span>
                    <Badge status={String(r.status || "").toLowerCase()} />
                  </button>
                ))}
              </div>
            )}
            <div className="mt-8 space-y-2">
              <p className="text-[10px] uppercase tracking-wider text-zinc-600">Try</p>
              {safeMap(EXAMPLES, (ex, i) => (
                <button
                  key={i}
                  onClick={() => setGoal(ex)}
                  className="block w-full text-left text-xs text-zinc-400 hover:text-zinc-200 border border-zinc-800/60 hover:border-zinc-700 rounded-lg px-3 py-2 transition-colors"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
          <Toast toast={toast} onDismiss={clearToast} />
        </div>
      </div>
    );
  }

  // ── Active run ──
  return (
    <div className="min-h-screen bg-[#09090b] text-zinc-100 flex justify-center">
      {modeBar}
      <div className="w-full max-w-2xl px-6 py-12 flex flex-col">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex-1">
            <h1 className="text-lg font-bold text-white leading-snug">{splitGoal(run.goal).ask}</h1>
            {splitGoal(run.goal).hasFindings && (
              <p className="text-[10px] uppercase tracking-wider text-zinc-500 mt-1">
                With findings from the previous run
              </p>
            )}
          </div>
          <button
            onClick={reset}
            className="text-[10px] uppercase tracking-wider text-zinc-500 hover:text-zinc-300 border border-zinc-800 rounded-sm px-2 py-1 shrink-0"
          >
            New
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 mb-5">
          <Badge status={status} />
          <Risk risk={run.overall_risk} />
          {run.steps_total > 0 && (
            <span className="text-[10px] text-zinc-500 font-mono">
              {run.steps_completed || 0}/{run.steps_total} steps
            </span>
          )}
        </div>

        {run.executive_summary && (
          <p className="text-sm text-zinc-400 mb-5 leading-relaxed">{run.executive_summary}</p>
        )}

        <div className="space-y-2">
          {safeMap(liveSteps, (step, i) => (
            <div key={step.id || i} className="border border-zinc-800/60 rounded-lg px-4 py-3">
              <div className="flex items-center gap-3">
                <span className="text-[10px] font-mono text-zinc-600 w-4">{i + 1}</span>
                <span className="font-mono text-xs text-[#00ffaa] shrink-0">
                  {step.tool_name || step.tool || "step"}
                </span>
                <Risk risk={step.risk_level} />
                <span className="flex-1 text-xs text-zinc-300 truncate">{step.description || ""}</span>
                {step.status && <Badge status={(step.status || "").toLowerCase()} />}
              </div>
              {step.error_message && (
                <p className="text-xs text-red-400 mt-2 pl-7">{step.error_message}</p>
              )}
              {step.result && String(step.status || "").toLowerCase() === "success" && (
                <div className="mt-2 pl-7">
                  <StepResult tool={step.tool_name} result={step.result} />
                </div>
              )}
            </div>
          ))}
          {liveSteps.length === 0 && (
            <p className="text-xs text-zinc-500 font-mono animate-pulse">Planning…</p>
          )}
        </div>

        {awaiting && (
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              onClick={approve}
              disabled={approving}
              className="px-5 py-2.5 rounded-lg bg-[#00ffaa] text-black text-xs font-bold uppercase tracking-wider hover:bg-[#00ffaa]/80 disabled:opacity-40 transition-colors"
            >
              {approving ? "Approving…" : "Approve & run"}
            </button>
            <button
              onClick={reject}
              className="px-5 py-2.5 rounded-lg border border-zinc-700 text-zinc-400 text-xs font-bold uppercase tracking-wider hover:bg-zinc-800 transition-colors"
            >
              Reject
            </button>
            <span className="text-[10px] text-zinc-600">Review the plan before it runs.</span>
          </div>
        )}

        {status === "executing" && (
          <p className="mt-6 text-xs text-[#00ffaa] font-mono animate-pulse">Executing…</p>
        )}

        {terminal && (
          <div className="mt-6 flex flex-wrap items-center gap-3 pt-4 border-t border-zinc-800/60">
            <Badge status={status} />
            <span className="text-xs text-zinc-400">
              {status === "completed"
                ? "Done."
                : status === "rejected"
                ? "Rejected — not run."
                : "The run ended before completing."}
            </span>
            <button
              onClick={reset}
              className="ml-auto text-[10px] uppercase tracking-wider text-[#00ffaa] hover:underline"
            >
              New request →
            </button>
          </div>
        )}

        {status === "completed" && (
          <form onSubmit={continueRun} className="mt-6 space-y-2">
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">Continue from this</p>
            <textarea
              value={followUp}
              onChange={(e) => setFollowUp(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) continueRun(e);
              }}
              placeholder="What should happen next, using what this run found?"
              rows={2}
              className="w-full bg-zinc-900/60 border border-zinc-800 rounded-xl px-4 py-3 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-hidden focus:border-[#00ffaa]/50 resize-none custom-scrollbar"
            />
            {findings ? (
              <div className="flex flex-wrap items-center gap-3 text-[11px] text-zinc-400">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={attachFindings}
                    onChange={(e) => setAttachFindings(e.target.checked)}
                  />
                  Attach this run&apos;s findings ({findings.length.toLocaleString()} characters)
                </label>
                <button
                  type="button"
                  onClick={() => setShowFindings((v) => !v)}
                  className="text-[10px] uppercase tracking-wider text-[#00ffaa] hover:underline"
                >
                  {showFindings ? "Hide" : "Preview"}
                </button>
              </div>
            ) : (
              <p className="text-[11px] text-zinc-600">This run found nothing to carry forward.</p>
            )}
            {showFindings && findings && (
              <pre className="max-h-64 overflow-auto custom-scrollbar text-[10px] text-zinc-400 whitespace-pre-wrap border border-zinc-800/60 rounded-lg p-3">
                {findings}
              </pre>
            )}
            <button
              type="submit"
              disabled={!followUp.trim() || submitting}
              className="w-full px-4 py-2.5 rounded-xl bg-[#00ffaa] text-black text-xs font-bold uppercase tracking-wider hover:bg-[#00ffaa]/80 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? "Starting…" : "Continue"}
            </button>
          </form>
        )}

        <Toast toast={toast} onDismiss={clearToast} />
      </div>
    </div>
  );
}
