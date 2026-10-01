import { useCallback, useEffect, useState } from "react";
import { getResolution, startResolution } from "../../api/works.js";
import { safeMap } from "../../utils/safe";

// The resolution check (RESOLUTION_CHECK_SPEC): your definition of success, measured. Does AI search
// bring back the right entity, how much of what it says is correct, does it connect your entities.
// A check is answered a few questions a minute by a scheduled job, so this polls while one runs.

const BUTTON = "px-3 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-40";
const PRIMARY = `${BUTTON} bg-[#00ffaa] text-black hover:bg-[#00ffaa]/80`;
const QUIET = `${BUTTON} border border-zinc-700 text-zinc-400 hover:bg-zinc-800`;
const POLL_MS = 15000;

const TONE = {
  resolved: "text-[#00ffaa] border-[#00ffaa]/40",
  mixed: "text-amber-300 border-amber-400/40",
  wrong: "text-red-400 border-red-400/40",
  unknown: "text-zinc-500 border-zinc-700",
};
const ENGINE_LABEL = { perplexity: "Perplexity", openai: "ChatGPT", claude: "Claude" };

const errorText = (e) => e?.body?.message || e?.message || "Something went wrong.";

function AnswerRow({ answer }) {
  const [open, setOpen] = useState(false);
  const s = answer.scores;
  return (
    <div className="text-[11px] space-y-1">
      <button className="flex flex-wrap items-center gap-2 text-left w-full" onClick={() => setOpen(!open)}>
        <span className="w-16 text-zinc-400">{ENGINE_LABEL[answer.engine] || answer.engine}</span>
        {answer.error ? (
          <span className="text-red-400">failed: {answer.error.slice(0, 80)}</span>
        ) : s ? (
          <>
            <span className={`border rounded-full px-2 py-0.5 uppercase tracking-wider text-[10px] ${TONE[s.resolution] || TONE.unknown}`}>
              {s.resolution}
            </span>
            <span className="text-zinc-400">
              {s.claims_correct} correct · {s.claims_incorrect} wrong · {s.claims_unverifiable} unverified
            </span>
            <span className="text-zinc-500">facts {s.facts_covered}/{s.facts_total}</span>
            {s.links_total > 0 && <span className="text-zinc-500">connections {s.links_stated}/{s.links_total}</span>}
            {s.own_sources_cited?.length > 0 && <span className="text-zinc-500">cites you: {s.own_sources_cited.join(", ")}</span>}
            {s.other_entities?.length > 0 && <span className="text-amber-300">also: {s.other_entities.join(", ")}</span>}
          </>
        ) : (
          <span className="text-zinc-500">answered, not judged</span>
        )}
      </button>
      {open && (
        <div className="pl-16 space-y-2">
          <pre className="whitespace-pre-wrap text-zinc-300 leading-relaxed">{answer.answer}</pre>
          {answer.claims?.length > 0 && (
            <ul className="space-y-0.5">
              {safeMap(answer.claims, (c, i) => (
                <li key={i} className={c.status === "incorrect" ? "text-red-400" : c.status === "unverifiable" ? "text-amber-300" : "text-zinc-400"}>
                  {c.status}: {c.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function ResolutionSection() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await getResolution());
    } catch (e) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const latest = data?.latest;
  const running = latest && (latest.status === "pending" || latest.status === "running");

  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [running, load]);

  const start = async (scope) => {
    setBusy(true);
    setError("");
    try {
      await startResolution(scope);
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  if (!data && !error) return null;
  const answers = Array.isArray(latest?.answers) ? latest.answers : [];
  const questions = Array.isArray(latest?.questions) ? latest.questions : [];

  return (
    <section className="border border-zinc-800/60 rounded-lg p-4 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-zinc-600">How well AI search resolves you</p>
          <p className="text-xs text-zinc-400 mt-1">
            The right entity, what it says that is correct, and the connections it makes, checked against what you confirmed.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <button className={PRIMARY} disabled={busy || running} onClick={() => start("core")}>Run a check</button>
          <button className={QUIET} disabled={busy || running} onClick={() => start("full")}>Full</button>
        </div>
      </div>
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}

      {data?.self_descriptions?.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] uppercase tracking-wider text-zinc-600">How you describe yourself, side by side</p>
          {safeMap(data.self_descriptions, (d, i) => (
            <p key={i} className="text-[11px] text-zinc-400">
              <span className="text-zinc-300">{d.work} · {d.platform}:</span> “{d.self_description}”
            </p>
          ))}
        </div>
      )}

      {latest && (
        <div className="space-y-3">
          <p className="text-[11px] text-zinc-500">
            {running ? `Checking… ${latest.answered} of ${latest.expected} answers` : `Last check (${latest.scope}), ${latest.finished_at ? new Date(latest.finished_at).toLocaleString() : ""}`}
          </p>
          {safeMap(questions, (q) => {
            const rows = answers.filter((a) => a.question_key === q.key);
            if (rows.length === 0) return null;
            return (
              <div key={q.key} className="space-y-1">
                <p className="text-xs text-zinc-200">{q.text}</p>
                {safeMap(rows, (a) => <AnswerRow key={`${a.question_key}-${a.engine}`} answer={a} />)}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
