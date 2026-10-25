import { useCallback, useEffect, useState } from "react";
import { decideRelease, handOffRelease, listReleases } from "../../api/releases.js";
import { safeMap } from "../../utils/safe";

// The release handoff on Collaborator's empty screen (RELEASE_HANDOFF_SPEC §6). Hand a tag off and
// A.I.N.D.Y. follows its publish run; while it waits at the approval gate the card says so and links
// straight to GitHub. With the approve token set (phase 3, §7.3) the card also offers Approve and
// Reject, each behind a confirm step that says what it does; GitHub records the decision and the stage
// moves on the watcher's next tick. The card clears itself once the stage moves, and a finished handoff
// stays for a day.

const ACTIVE = new Set(["requested", "running", "at_gate", "approved", "published"]);
const POLL_MS = 30_000;
const KEEP_FINISHED_MS = 24 * 60 * 60 * 1000;

const STAGE_LABEL = {
  requested: "Looking for the publish run",
  running: "Building and testing",
  at_gate: "Waiting for your approval",
  approved: "Approved, publishing",
  published: "Published, verifying the wheel",
  done: "Released",
  failed: "Stopped",
};

const REASON = {
  no_run: "no publish run was found for the tag",
  stalled: "the run stopped moving",
  rejected: "the approval was rejected",
  cancelled: "the run was cancelled",
};

function clock(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function duration(seconds) {
  if (seconds == null) return "";
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  return m ? `${m} min ${s % 60} s` : `${s} s`;
}

function project(h) {
  return `${String(h.repo || "").split("/").pop()} ${h.version}`;
}

function failureText(failure) {
  if (!failure) return "";
  if (REASON[failure.reason]) return REASON[failure.reason];
  return `${failure.job || "the run"} ended ${failure.conclusion || "unsuccessfully"}`;
}

function visibleHandoffs(handoffs, now = Date.now()) {
  return (handoffs || []).filter(
    (h) => ACTIVE.has(h.stage) || now - new Date(h.finished_at || h.stage_at || 0).getTime() < KEEP_FINISHED_MS,
  );
}

function Decide({ h, onDecided }) {
  const [asking, setAsking] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const send = async () => {
    setBusy(true);
    setError("");
    try {
      await decideRelease(h.id, asking);
      setAsking(null);
      await onDecided();
    } catch (err) {
      setError(err?.message || "GitHub did not take the decision.");
    } finally {
      setBusy(false);
    }
  };

  if (asking) {
    return (
      <div className="mt-2 space-y-1">
        <p className="text-zinc-200">
          {asking === "approve"
            ? `Publish ${project(h)} to PyPI, approving as you on GitHub?`
            : `Reject ${project(h)}? Nothing is published and the handoff stops.`}
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={send}
            disabled={busy}
            className={`rounded-sm px-2 py-1 font-bold uppercase tracking-wider disabled:opacity-40 ${
              asking === "approve" ? "bg-amber-400 text-black hover:bg-amber-300" : "border border-red-500/60 text-red-300"
            }`}
          >
            {busy ? "…" : asking === "approve" ? "Yes, publish" : "Yes, reject"}
          </button>
          <button
            type="button"
            onClick={() => setAsking(null)}
            disabled={busy}
            className="rounded-sm border border-zinc-700 px-2 py-1 uppercase tracking-wider text-zinc-400"
          >
            Cancel
          </button>
        </div>
        {error && <p className="text-[11px] text-red-300">{error}</p>}
      </div>
    );
  }
  return (
    <div className="mt-2 flex gap-2">
      <button
        type="button"
        onClick={() => setAsking("approve")}
        className="rounded-sm bg-amber-400 px-2 py-1 font-bold uppercase tracking-wider text-black hover:bg-amber-300"
      >
        Approve
      </button>
      <button
        type="button"
        onClick={() => setAsking("reject")}
        className="rounded-sm border border-zinc-700 px-2 py-1 font-bold uppercase tracking-wider text-zinc-300"
      >
        Reject
      </button>
    </div>
  );
}

function ReleaseCard({ h, onChanged }) {
  const gate = h.stage === "at_gate";
  const tone = gate
    ? "border-amber-500/40 bg-amber-500/10"
    : h.stage === "failed"
      ? "border-red-500/30 bg-red-500/5"
      : "border-zinc-800/60";
  const gateAt = (h.history || []).find((e) => e.stage === "at_gate")?.at;
  const decided = gate && h.decision;
  return (
    <div className={`rounded-lg border px-3 py-2 text-xs ${tone}`} data-testid={`release-${h.tag}`}>
      {gate ? (
        <p className="text-amber-200">
          {project(h)} is waiting for your approval{gateAt ? ` (gate reached ${clock(gateAt)})` : ""}
        </p>
      ) : (
        <p className="text-zinc-300">
          {project(h)} · <span className="text-zinc-400">{STAGE_LABEL[h.stage] || h.stage}</span>
        </p>
      )}
      {decided && (
        <p className="mt-1 text-zinc-400">
          {h.decision.state === "approved" ? "Approved" : "Rejected"} from A.I.N.D.Y. at {clock(h.decision.at)}; waiting
          for GitHub to move
        </p>
      )}
      {gate && h.can_decide && <Decide h={h} onDecided={onChanged} />}
      {h.stage === "done" && h.approved_by && (
        <p className="mt-1 text-zinc-500">
          Approved by {h.approved_by}
          {h.gate_wait_seconds != null ? ` after ${duration(h.gate_wait_seconds)} at the gate` : ""}
        </p>
      )}
      {h.stage === "failed" && <p className="mt-1 text-red-300">Stopped: {failureText(h.failure)}</p>}
      {((gate && !decided) || h.stage === "failed") && (h.failure?.url || h.run_url) && (
        <a
          href={(h.stage === "failed" && h.failure?.url) || h.run_url}
          target="_blank"
          rel="noreferrer"
          className={`mt-2 inline-block rounded-sm px-2 py-1 font-bold uppercase tracking-wider ${
            gate && !h.can_decide ? "bg-amber-400 text-black hover:bg-amber-300" : "border border-zinc-700 text-zinc-300"
          }`}
        >
          {gate ? (h.can_decide ? "Open on GitHub" : "Approve on GitHub") : "Open on GitHub"}
        </a>
      )}
      <p className="mt-1 text-[10px] text-zinc-600">
        {safeMap(h.history, (e) => `${e.stage === "decision" ? `${e.state} (A.I.N.D.Y.)` : e.stage} ${clock(e.at)}`).join(" → ")}
      </p>
    </div>
  );
}

export default function ReleasePanel() {
  const [handoffs, setHandoffs] = useState([]);
  const [open, setOpen] = useState(false);
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const body = await listReleases({ limit: 5 });
      setHandoffs(Array.isArray(body?.handoffs) ? body.handoffs : []);
    } catch {
      // The panel is an addition to the empty screen; an unreachable endpoint shows nothing rather than an error.
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const visible = visibleHandoffs(handoffs);
  const following = visible.some((h) => ACTIVE.has(h.stage));
  useEffect(() => {
    if (!following) return undefined;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [following, load]);

  const submit = async (e) => {
    e.preventDefault();
    if (!tag.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await handOffRelease(tag.trim());
      setTag("");
      await load();
    } catch (err) {
      setError(err?.message || "The handoff was refused.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-8 space-y-2" data-testid="release-panel">
      {visible.length > 0 && <p className="text-[10px] uppercase tracking-wider text-zinc-600">Releases</p>}
      {safeMap(visible, (h) => (
        <ReleaseCard key={h.id} h={h} onChanged={load} />
      ))}
      {open ? (
        <form onSubmit={submit} className="flex gap-2">
          <input
            autoFocus
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            placeholder="Hand off a tag, e.g. v2.28.0"
            aria-label="Release tag"
            className="flex-1 bg-zinc-900/60 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-100 placeholder-zinc-600 focus:outline-hidden focus:border-[#00ffaa]/50"
          />
          <button
            type="submit"
            disabled={!tag.trim() || busy}
            className="px-3 py-2 rounded-lg border border-zinc-700 text-[10px] font-bold uppercase tracking-wider text-zinc-300 hover:border-zinc-500 disabled:opacity-40"
          >
            {busy ? "…" : "Follow"}
          </button>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-[10px] uppercase tracking-wider text-zinc-500 hover:text-zinc-300"
        >
          Hand off a release
        </button>
      )}
      {error && <p className="text-[11px] text-red-300">{error}</p>}
    </div>
  );
}
