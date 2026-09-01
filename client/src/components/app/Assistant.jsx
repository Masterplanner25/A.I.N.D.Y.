import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createAgentRun,
  getAgentRun,
  approveAgentRun,
  rejectAgentRun,
  getAgentRunSteps,
} from "../../api/agent.js";
import { Toast } from "../shared/Toast";
import { useToast } from "../../utils/useToast";
import { safeMap } from "../../utils/safe";
import Genesis from "./Genesis";

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
  const { toast, showToast, clearToast } = useToast();

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
        const r = await getAgentRun(runId);
        if (cancelled) return;
        setRun(r);
        // /runs/{id}/steps returns { data: [...] }, not a bare array — unwrap it, else
        // steps never populated and the run showed the static plan the whole time.
        const s = await getAgentRunSteps(runId).catch(() => []);
        const stepList = Array.isArray(s) ? s : Array.isArray(s?.data) ? s.data : [];
        if (!cancelled && stepList.length) setSteps(stepList);
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

  const submit = async (e) => {
    e?.preventDefault?.();
    if (!goal.trim() || submitting) return;
    setSubmitting(true);
    setSteps([]);
    setRun(null);
    try {
      const r = await createAgentRun({ goal: goal.trim() });
      setRun(r); // the poll effect picks up runId and takes over
    } catch (e) {
      showToast(e?.message || "Couldn't start — is the agent reachable?");
    } finally {
      setSubmitting(false);
    }
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
  };

  // Mode: one face, two engines — "agent" (do X) or "genesis" (author/revise the plan).
  // Driven by ?mode=genesis so it's linkable (e.g. the MasterPlan "Initialize via Genesis" entry).
  const [searchParams, setSearchParams] = useSearchParams();
  const mode = searchParams.get("mode") === "genesis" ? "genesis" : "agent";
  const setMode = (m) =>
    setSearchParams(m === "genesis" ? { mode: "genesis" } : {}, { replace: true });

  const modeBar = (
    <div className="fixed top-3 left-1/2 -translate-x-1/2 z-30 flex gap-1 rounded-full border border-zinc-800 bg-zinc-950/90 p-1 shadow-lg shadow-black/40 backdrop-blur-sm">
      {safeMap([
        ["agent", "Agent"],
        ["genesis", "Plan"],
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
          <h1 className="text-lg font-bold text-white leading-snug flex-1">{run.goal}</h1>
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

        <Toast toast={toast} onDismiss={clearToast} />
      </div>
    </div>
  );
}
