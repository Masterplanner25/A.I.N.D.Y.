import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { deleteDraft, getDraft, listDrafts, updateDraft } from "../../api/works.js";
import { safeMap } from "../../utils/safe";

// What the agent wrote for you (content.draft). Owner, 2026-09-30: "where does the output go once it
// does generate/do something?" Until this, into a step result, a memory node and a task. Now here: each
// draft with the run that wrote it and the sources it drew on, to read, edit, copy or download.

const BUTTON = "px-3 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-40";
const PRIMARY = `${BUTTON} bg-[#00ffaa] text-black hover:bg-[#00ffaa]/80`;
const QUIET = `${BUTTON} border border-zinc-700 text-zinc-400 hover:bg-zinc-800`;

const errorText = (e) => e?.body?.message || e?.message || "Something went wrong.";
const slug = (title) => String(title || "draft").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "draft";

export function downloadMarkdown(title, body) {
  const blob = new Blob([body || ""], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${slug(title)}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function DraftsSection() {
  const [drafts, setDrafts] = useState([]);
  const [open, setOpen] = useState(null);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const out = await listDrafts();
      setDrafts(Array.isArray(out?.drafts) ? out.drafts : []);
    } catch (e) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const show = async (id) => {
    if (open?.id === id) {
      setOpen(null);
      return;
    }
    setError("");
    setEditing(null);
    try {
      setOpen(await getDraft(id));
    } catch (e) {
      setError(errorText(e));
    }
  };

  const act = async (fn) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (drafts.length === 0 && !error) return null;

  return (
    <section className="space-y-3">
      <p className="text-[10px] uppercase tracking-wider text-zinc-600">Drafts the agent wrote ({drafts.length})</p>
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
      {safeMap(drafts, (d) => (
        <div key={d.id} className="border border-zinc-800/60 rounded-lg p-4 space-y-3">
          <button className="text-left w-full" onClick={() => show(d.id)}>
            <p className="text-sm font-bold text-white">{d.title}</p>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500 mt-0.5">
              {d.created_at ? new Date(d.created_at).toLocaleString() : ""} · {d.words} words
              {d.sources?.length ? ` · ${d.sources.length} source${d.sources.length === 1 ? "" : "s"}` : " · no sources"}
            </p>
          </button>
          {d.run_id && (
            <Link to={`/collaborator?run=${encodeURIComponent(d.run_id)}`} className="text-[11px] text-zinc-500 underline">
              the run that wrote it
            </Link>
          )}
          {open?.id === d.id && (
            <div className="space-y-3">
              {editing ? (
                <textarea aria-label="Draft text" rows={18} value={editing.body}
                  onChange={(e) => setEditing({ ...editing, body: e.target.value })}
                  className="w-full bg-zinc-900/60 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-100 font-mono" />
              ) : (
                <pre className="whitespace-pre-wrap text-xs text-zinc-300 leading-relaxed max-h-[32rem] overflow-y-auto">{open.body}</pre>
              )}
              <div className="flex flex-wrap gap-2">
                {editing ? (
                  <>
                    <button className={PRIMARY} disabled={busy}
                      onClick={async () => {
                        let saved = null;
                        if (await act(async () => { saved = await updateDraft(d.id, { body: editing.body }); })) {
                          setOpen(saved);
                          setEditing(null);
                          load();
                        }
                      }}>
                      Save
                    </button>
                    <button className={QUIET} onClick={() => setEditing(null)}>Cancel</button>
                  </>
                ) : (
                  <>
                    <button className={QUIET} onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(open.body || "");
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1500);
                      } catch {
                        setError("Copy is not available here; use Download.");
                      }
                    }}>
                      {copied ? "Copied" : "Copy"}
                    </button>
                    <button className={QUIET} onClick={() => downloadMarkdown(open.title, open.body)}>Download .md</button>
                    <button className={QUIET} onClick={() => setEditing({ body: open.body })}>Edit</button>
                    <button className={QUIET} disabled={busy}
                      onClick={async () => {
                        if (!window.confirm(`Delete "${d.title}"?`)) return;
                        if (await act(() => deleteDraft(d.id))) {
                          setOpen(null);
                          load();
                        }
                      }}>
                      Delete
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
