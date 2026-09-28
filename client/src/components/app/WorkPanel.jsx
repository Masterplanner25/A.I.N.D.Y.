import { useCallback, useEffect, useState } from "react";
import {
  addWorkLink,
  confirmWorkProposal,
  createWork,
  deleteWork,
  dismissWorkProposal,
  listWorkProposals,
  listWorks,
  removeWorkLink,
  setWorkObjectives,
  updateWork,
} from "../../api/works.js";
import { safeMap } from "../../utils/safe";

// Collaborator's Work mode (docs/specs/WORK_MODEL_SPEC.md §4, §6): what you have made, in your
// words, how it fits together, and what the agent is told. Nothing is inferred into it: the system
// proposes what it can already see, and you confirm, edit or dismiss.

const FIELD = "w-full bg-zinc-900/60 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-hidden focus:border-[#00ffaa]/50";
const BUTTON = "px-3 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-40";
const PRIMARY = `${BUTTON} bg-[#00ffaa] text-black hover:bg-[#00ffaa]/80`;
const QUIET = `${BUTTON} border border-zinc-700 text-zinc-400 hover:bg-zinc-800`;

const errorText = (e) => e?.body?.message || e?.message || "Something went wrong.";

function Select({ value, options, onChange, label }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={FIELD}>
      {safeMap(options, (o) => (
        <option key={o} value={o}>{o}</option>
      ))}
    </select>
  );
}

function WorkFields({ draft, setDraft, vocabulary }) {
  const set = (field) => (value) => setDraft({ ...draft, [field]: value });
  return (
    <div className="space-y-2">
      <input aria-label="Name" className={FIELD} value={draft.name || ""} placeholder="Name"
        onChange={(e) => set("name")(e.target.value)} />
      <textarea aria-label="Summary" className={`${FIELD} resize-none`} rows={3} value={draft.summary || ""}
        placeholder="What it is, in your words" onChange={(e) => set("summary")(e.target.value)} />
      <div className="grid grid-cols-3 gap-2">
        <Select label="Kind" value={draft.kind || "project"} options={vocabulary.kinds} onChange={set("kind")} />
        <Select label="Role" value={draft.role || "creator"} options={vocabulary.roles} onChange={set("role")} />
        <Select label="Status" value={draft.status || "active"} options={vocabulary.statuses} onChange={set("status")} />
      </div>
    </div>
  );
}

const EMPTY_VOCAB = { kinds: ["project"], roles: ["creator"], statuses: ["active"], relations: {} };

export default function WorkPanel() {
  const [data, setData] = useState(null);
  const [proposals, setProposals] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [adding, setAdding] = useState(null);
  const [editing, setEditing] = useState(null);
  const [linkDrafts, setLinkDrafts] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [works, open] = await Promise.all([listWorks(), listWorkProposals()]);
      setData(works);
      const list = Array.isArray(open?.proposals) ? open.proposals : [];
      setProposals(list);
      setDrafts((prev) => {
        const next = {};
        for (const p of list) next[p.key] = prev[p.key] || { name: p.name, summary: p.summary, kind: p.kind, role: p.role, status: p.status };
        return next;
      });
    } catch (e) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (fn) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const vocabulary = data?.vocabulary || EMPTY_VOCAB;
  const works = Array.isArray(data?.works) ? data.works : [];
  const links = Array.isArray(data?.links) ? data.links : [];
  const objectives = Array.isArray(data?.objectives_available) ? data.objectives_available : [];
  const nameOf = Object.fromEntries(safeMap(works, (w) => [w.id, w.name]));

  if (!data && !error) {
    return <p className="text-xs text-zinc-500 font-mono animate-pulse">Loading your work…</p>;
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tighter text-white">Your work</h1>
        <p className="text-zinc-500 mt-2 text-sm max-w-lg">
          What you have made, in your words, and how it fits together. The agent plans with what you
          confirm here, and nothing else.
        </p>
      </div>

      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}

      {proposals.length > 0 && (
        <section className="space-y-3">
          <p className="text-[10px] uppercase tracking-wider text-zinc-600">The system noticed</p>
          {safeMap(proposals, (p) => {
            const draft = drafts[p.key] || {};
            return (
              <div key={p.key} className="border border-zinc-800/60 rounded-lg p-4 space-y-3">
                <div>
                  <p className="text-sm text-zinc-200">{p.question}</p>
                  <p className="text-[11px] text-zinc-500 mt-1">{p.evidence}</p>
                </div>
                <WorkFields draft={draft} vocabulary={vocabulary}
                  setDraft={(d) => setDrafts({ ...drafts, [p.key]: d })} />
                <div className="flex gap-2">
                  <button className={PRIMARY} disabled={busy || !String(draft.summary || "").trim()}
                    onClick={() => act(() => confirmWorkProposal({ key: p.key, ...draft }))}>
                    Confirm
                  </button>
                  <button className={QUIET} disabled={busy} onClick={() => act(() => dismissWorkProposal(p.key))}>
                    Not mine
                  </button>
                </div>
              </div>
            );
          })}
        </section>
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[10px] uppercase tracking-wider text-zinc-600">Confirmed ({works.length})</p>
          {!adding && (
            <button className={QUIET} onClick={() => setAdding({ kind: "project", role: "creator", status: "active" })}>
              Add a work
            </button>
          )}
        </div>

        {adding && (
          <div className="border border-zinc-800/60 rounded-lg p-4 space-y-3">
            <WorkFields draft={adding} setDraft={setAdding} vocabulary={vocabulary} />
            <div className="flex gap-2">
              <button className={PRIMARY} disabled={busy || !String(adding.name || "").trim() || !String(adding.summary || "").trim()}
                onClick={async () => { if (await act(() => createWork(adding))) setAdding(null); }}>
                Save
              </button>
              <button className={QUIET} onClick={() => setAdding(null)}>Cancel</button>
            </div>
          </div>
        )}

        {works.length === 0 && !adding && (
          <p className="text-xs text-zinc-500">Nothing yet. Confirm what the system noticed, or add a work.</p>
        )}

        {safeMap(works, (w) => {
          const outgoing = links.filter((l) => l.from_work_id === w.id);
          const serving = new Set(safeMap(w.objectives || [], (o) => o.id));
          const linkDraft = linkDrafts[w.id] || { relation: Object.keys(vocabulary.relations)[0] || "built_on", to_work_id: "" };
          const others = works.filter((o) => o.id !== w.id);
          return (
            <div key={w.id} className="border border-zinc-800/60 rounded-lg p-4 space-y-3">
              {editing?.id === w.id ? (
                <>
                  <WorkFields draft={editing} setDraft={setEditing} vocabulary={vocabulary} />
                  <div className="flex gap-2">
                    <button className={PRIMARY} disabled={busy}
                      onClick={async () => {
                        const { id, name, summary, kind, role, status } = editing;
                        if (await act(() => updateWork(id, { name, summary, kind, role, status }))) setEditing(null);
                      }}>
                      Save
                    </button>
                    <button className={QUIET} onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                </>
              ) : (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-bold text-white">{w.name}</p>
                      <p className="text-[10px] uppercase tracking-wider text-zinc-500 mt-0.5">
                        {w.kind} · {w.role} · {w.status}
                      </p>
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <button className={QUIET} onClick={() => setEditing({ ...w })}>Edit</button>
                      <button className={QUIET} disabled={busy}
                        onClick={() => { if (window.confirm(`Delete ${w.name}?`)) act(() => deleteWork(w.id)); }}>
                        Delete
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-zinc-300 leading-relaxed whitespace-pre-wrap">{w.summary}</p>
                </>
              )}

              {outgoing.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {safeMap(outgoing, (l) => (
                    <span key={l.id} className="text-[11px] text-zinc-300 border border-zinc-800 rounded-full px-2 py-0.5">
                      {l.relation.replace(/_/g, " ")} {nameOf[l.to_work_id]}
                      <button aria-label={`Remove ${l.relation} ${nameOf[l.to_work_id]}`} className="ml-2 text-zinc-500 hover:text-red-400"
                        onClick={() => act(() => removeWorkLink(l.id))}>×</button>
                    </span>
                  ))}
                </div>
              )}

              {others.length > 0 && (
                <div className="flex gap-2 items-center">
                  <select aria-label={`Relation for ${w.name}`} className={FIELD} value={linkDraft.relation}
                    onChange={(e) => setLinkDrafts({ ...linkDrafts, [w.id]: { ...linkDraft, relation: e.target.value } })}>
                    {safeMap(Object.entries(vocabulary.relations), ([rel, meaning]) => (
                      <option key={rel} value={rel}>{rel.replace(/_/g, " ")} ({meaning})</option>
                    ))}
                  </select>
                  <select aria-label={`Related work for ${w.name}`} className={FIELD} value={linkDraft.to_work_id}
                    onChange={(e) => setLinkDrafts({ ...linkDrafts, [w.id]: { ...linkDraft, to_work_id: e.target.value } })}>
                    <option value="">choose a work…</option>
                    {safeMap(others, (o) => (
                      <option key={o.id} value={o.id}>{o.name}</option>
                    ))}
                  </select>
                  <button className={QUIET} disabled={busy || !linkDraft.to_work_id}
                    onClick={async () => {
                      if (await act(() => addWorkLink(w.id, linkDraft))) setLinkDrafts({ ...linkDrafts, [w.id]: undefined });
                    }}>
                    Relate
                  </button>
                </div>
              )}

              {objectives.length > 0 && (
                <div className="flex flex-wrap gap-3 text-[11px] text-zinc-400">
                  <span className="text-zinc-600 uppercase tracking-wider">Serves</span>
                  {safeMap(objectives, (o) => (
                    <label key={o.id} className="flex items-center gap-1">
                      <input type="checkbox" checked={serving.has(o.id)} disabled={busy}
                        onChange={() => {
                          const next = new Set(serving);
                          if (next.has(o.id)) next.delete(o.id);
                          else next.add(o.id);
                          act(() => setWorkObjectives(w.id, [...next]));
                        }} />
                      {o.name}
                    </label>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </section>

      <details className="border border-zinc-800/60 rounded-lg p-4">
        <summary className="text-[10px] uppercase tracking-wider text-zinc-500 cursor-pointer">
          What the agent is told
        </summary>
        <pre className="mt-3 text-[11px] text-zinc-400 whitespace-pre-wrap">
          {data?.agent_block || "Nothing yet: the agent learns about your work from what you confirm here."}
        </pre>
      </details>
    </div>
  );
}
