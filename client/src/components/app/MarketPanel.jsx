import { useCallback, useEffect, useState } from "react";
import {
  confirmMarketProposal,
  createMarketEntity,
  createSegment,
  deleteMarketEntity,
  deleteSegment,
  dismissMarketProposal,
  getMarket,
  listMarketProposals,
  setSegmentWorks,
  updateSegment,
} from "../../api/market.js";
import { safeMap } from "../../utils/safe";

// Collaborator's Market mode (docs/specs/MARKET_MODEL_SPEC.md §4, §6): who your work is for, what
// surrounds that buyer, and what the agent is told. A segment is a bet, so its status is always
// shown. The system and the agent propose; only you confirm.

const FIELD = "w-full bg-zinc-900/60 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-hidden focus:border-[#00ffaa]/50";
const BUTTON = "px-3 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-40";
const PRIMARY = `${BUTTON} bg-[#00ffaa] text-black hover:bg-[#00ffaa]/80`;
const QUIET = `${BUTTON} border border-zinc-700 text-zinc-400 hover:bg-zinc-800`;

const STATUS_TONE = {
  hypothesis: "text-amber-300 border-amber-400/40",
  testing: "text-sky-300 border-sky-400/40",
  validated: "text-[#00ffaa] border-[#00ffaa]/40",
  abandoned: "text-zinc-500 border-zinc-700",
};

const errorText = (e) => e?.body?.message || e?.message || "Something went wrong.";
const terms = (text) => safeMap(String(text || "").split(","), (t) => t.trim()).filter(Boolean);

function SegmentFields({ draft, setDraft }) {
  const set = (field) => (e) => setDraft({ ...draft, [field]: e.target.value });
  return (
    <div className="space-y-2">
      <input aria-label="Segment name" className={FIELD} value={draft.name || ""} placeholder="Name: e.g. Platform teams shipping agents"
        onChange={set("name")} />
      <input aria-label="Buyer" className={FIELD} value={draft.buyer || ""} placeholder="Buyer: who decides, in what kind of organisation"
        onChange={set("buyer")} />
      <textarea aria-label="Problem" className={`${FIELD} resize-none`} rows={2} value={draft.problem || ""}
        placeholder="The problem, in the buyer's words" onChange={set("problem")} />
      <input aria-label="Category terms" className={FIELD} value={draft.terms ?? (draft.category_terms || []).join(", ")}
        placeholder="What they call it, comma-separated: AgentOps, agent orchestration" onChange={set("terms")} />
    </div>
  );
}

function segmentBody(draft) {
  const { name, buyer, problem } = draft;
  const body = { name, buyer, problem };
  if (draft.terms !== undefined) body.category_terms = terms(draft.terms);
  else if (draft.category_terms) body.category_terms = draft.category_terms;
  return body;
}

function Evidence({ items }) {
  if (!items?.length) return null;
  return (
    <ul className="space-y-1">
      {safeMap(items, (e, i) => (
        <li key={e.id || i} className="text-[11px] text-zinc-500">
          <span className={e.stance === "contradicts" ? "text-red-400" : "text-zinc-600"}>
            {e.stance === "contradicts" ? "against · " : "for · "}
          </span>
          {e.claim}
          {e.source_url && (
            <a href={e.source_url} target="_blank" rel="noreferrer" className="ml-1 text-zinc-600 underline">source</a>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function MarketPanel() {
  const [data, setData] = useState(null);
  const [proposals, setProposals] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [adding, setAdding] = useState(null);
  const [addingEntity, setAddingEntity] = useState(null);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [market, open] = await Promise.all([getMarket(), listMarketProposals()]);
      setData(market);
      const list = Array.isArray(open?.proposals) ? open.proposals : [];
      setProposals(list);
      setDrafts((prev) => {
        const next = {};
        for (const p of list) {
          next[p.key] = prev[p.key] || {
            kind: p.kind || "", name: p.name, buyer: p.buyer || "", problem: p.problem || "",
            category_terms: p.category_terms || [], segment_id: "",
          };
        }
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

  const segments = Array.isArray(data?.segments) ? data.segments : [];
  const entities = Array.isArray(data?.entities) ? data.entities : [];
  const works = Array.isArray(data?.works_available) ? data.works_available : [];
  const kinds = data?.vocabulary?.kinds || {};
  const statuses = data?.vocabulary?.statuses || ["hypothesis"];
  const unattached = entities.filter((e) => !e.segment_id);

  if (!data && !error) {
    return <p className="text-xs text-zinc-500 font-mono animate-pulse">Loading your market…</p>;
  }

  const confirmBody = (p, draft) => {
    const body = { key: p.key, kind: draft.kind, name: draft.name };
    if (draft.kind === "segment") Object.assign(body, segmentBody(draft));
    else if (draft.segment_id) body.segment_id = draft.segment_id;
    return body;
  };

  const canConfirm = (draft) => {
    if (!draft.kind || !String(draft.name || "").trim()) return false;
    return draft.kind !== "segment" || String(draft.buyer || "").trim().length > 0;
  };

  const entityRow = (e) => (
    <div key={e.id} className="flex items-start justify-between gap-3 text-xs">
      <div>
        <span className="text-zinc-200">{e.url ? <a href={e.url} target="_blank" rel="noreferrer" className="underline">{e.name}</a> : e.name}</span>
        <span className="ml-2 text-[10px] uppercase tracking-wider text-zinc-500">{e.kind}</span>
        {e.note && <p className="text-[11px] text-zinc-500 mt-0.5">{e.note}</p>}
        <Evidence items={e.evidence} />
      </div>
      <button aria-label={`Remove ${e.name}`} className="text-zinc-500 hover:text-red-400" disabled={busy}
        onClick={() => { if (window.confirm(`Remove ${e.name}?`)) act(() => deleteMarketEntity(e.id)); }}>×</button>
    </div>
  );

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tighter text-white">Your market</h1>
        <p className="text-zinc-500 mt-2 text-sm max-w-lg">
          Who your work is for, what else they would choose, and where they are. Each segment is a bet
          until the evidence says otherwise. The agent plans with what you confirm here.
        </p>
      </div>

      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}

      {proposals.length > 0 && (
        <section className="space-y-3">
          <p className="text-[10px] uppercase tracking-wider text-zinc-600">Proposed ({proposals.length})</p>
          {safeMap(proposals, (p) => {
            const draft = drafts[p.key] || {};
            const setDraft = (d) => setDrafts({ ...drafts, [p.key]: d });
            return (
              <div key={p.key} className="border border-zinc-800/60 rounded-lg p-4 space-y-3">
                <div>
                  <p className="text-sm text-zinc-200">{p.question}</p>
                  {p.note && <p className="text-[11px] text-zinc-500 mt-1">{p.note}</p>}
                  {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="text-[11px] text-zinc-600 underline break-all">{p.url}</a>}
                  <Evidence items={p.evidence} />
                </div>
                <select aria-label={`What ${p.name} is`} className={FIELD} value={draft.kind || ""}
                  onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
                  <option value="">What is it?</option>
                  <option value="segment">segment (a kind of buyer)</option>
                  {safeMap(Object.entries(kinds), ([k, meaning]) => (
                    <option key={k} value={k}>{k} ({meaning})</option>
                  ))}
                </select>
                {draft.kind === "segment" ? (
                  <SegmentFields draft={draft} setDraft={setDraft} />
                ) : (
                  <div className="grid grid-cols-2 gap-2">
                    <input aria-label={`Name for ${p.name}`} className={FIELD} value={draft.name || ""}
                      onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                    <select aria-label={`Segment for ${p.name}`} className={FIELD} value={draft.segment_id || ""}
                      onChange={(e) => setDraft({ ...draft, segment_id: e.target.value })}>
                      <option value="">no segment</option>
                      {safeMap(segments, (s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  </div>
                )}
                <div className="flex gap-2">
                  <button className={PRIMARY} disabled={busy || !canConfirm(draft)}
                    onClick={() => act(() => confirmMarketProposal(confirmBody(p, draft)))}>
                    Confirm
                  </button>
                  <button className={QUIET} disabled={busy} onClick={() => act(() => dismissMarketProposal(p.key))}>
                    {p.source === "lead" ? "It's a lead" : "Not my market"}
                  </button>
                </div>
              </div>
            );
          })}
        </section>
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[10px] uppercase tracking-wider text-zinc-600">Segments ({segments.length})</p>
          {!adding && <button className={QUIET} onClick={() => setAdding({})}>Add a segment</button>}
        </div>

        {adding && (
          <div className="border border-zinc-800/60 rounded-lg p-4 space-y-3">
            <SegmentFields draft={adding} setDraft={setAdding} />
            <div className="flex gap-2">
              <button className={PRIMARY} disabled={busy || !String(adding.name || "").trim() || !String(adding.buyer || "").trim()}
                onClick={async () => { if (await act(() => createSegment(segmentBody(adding)))) setAdding(null); }}>
                Save
              </button>
              <button className={QUIET} onClick={() => setAdding(null)}>Cancel</button>
            </div>
          </div>
        )}

        {segments.length === 0 && !adding && (
          <p className="text-xs text-zinc-500">No segments yet. Confirm a proposal, or add who your work is for.</p>
        )}

        {safeMap(segments, (s) => {
          const serving = new Set(safeMap(s.works || [], (w) => w.id));
          const around = entities.filter((e) => e.segment_id === s.id);
          return (
            <div key={s.id} className="border border-zinc-800/60 rounded-lg p-4 space-y-3">
              {editing?.id === s.id ? (
                <>
                  <SegmentFields draft={editing} setDraft={setEditing} />
                  <div className="flex gap-2">
                    <button className={PRIMARY} disabled={busy}
                      onClick={async () => { if (await act(() => updateSegment(s.id, segmentBody(editing)))) setEditing(null); }}>
                      Save
                    </button>
                    <button className={QUIET} onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                </>
              ) : (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-bold text-white">{s.name}</p>
                      <p className="text-xs text-zinc-400 mt-1">{s.buyer}</p>
                    </div>
                    <div className="flex gap-2 shrink-0 items-center">
                      <select aria-label={`Status of ${s.name}`} disabled={busy} value={s.status}
                        className={`bg-transparent border rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider ${STATUS_TONE[s.status] || ""}`}
                        onChange={(e) => act(() => updateSegment(s.id, { status: e.target.value }))}>
                        {safeMap(statuses, (st) => <option key={st} value={st}>{st}</option>)}
                      </select>
                      <button className={QUIET} onClick={() => setEditing({ ...s })}>Edit</button>
                      <button className={QUIET} disabled={busy}
                        onClick={() => { if (window.confirm(`Delete ${s.name}?`)) act(() => deleteSegment(s.id)); }}>
                        Delete
                      </button>
                    </div>
                  </div>
                  {s.problem && <p className="text-xs text-zinc-300">"{s.problem}"</p>}
                  {s.category_terms?.length > 0 && (
                    <p className="text-[11px] text-zinc-500">Calls it: {s.category_terms.join(", ")}</p>
                  )}
                </>
              )}

              {works.length > 0 && (
                <div className="flex flex-wrap gap-3 text-[11px] text-zinc-400">
                  <span className="text-zinc-600 uppercase tracking-wider">Served by</span>
                  {safeMap(works, (w) => (
                    <label key={w.id} className="flex items-center gap-1">
                      <input type="checkbox" checked={serving.has(w.id)} disabled={busy}
                        onChange={() => {
                          const next = new Set(serving);
                          if (next.has(w.id)) next.delete(w.id);
                          else next.add(w.id);
                          act(() => setSegmentWorks(s.id, [...next]));
                        }} />
                      {w.name}
                    </label>
                  ))}
                </div>
              )}

              {around.length > 0 && <div className="space-y-2">{safeMap(around, entityRow)}</div>}
              <Evidence items={s.evidence} />
            </div>
          );
        })}
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[10px] uppercase tracking-wider text-zinc-600">Not tied to a segment ({unattached.length})</p>
          {!addingEntity && <button className={QUIET} onClick={() => setAddingEntity({ kind: "alternative" })}>Add an entry</button>}
        </div>
        {addingEntity && (
          <div className="border border-zinc-800/60 rounded-lg p-4 space-y-2">
            <select aria-label="Entry kind" className={FIELD} value={addingEntity.kind}
              onChange={(e) => setAddingEntity({ ...addingEntity, kind: e.target.value })}>
              {safeMap(Object.entries(kinds), ([k, meaning]) => <option key={k} value={k}>{k} ({meaning})</option>)}
            </select>
            <input aria-label="Entry name" className={FIELD} placeholder="Name" value={addingEntity.name || ""}
              onChange={(e) => setAddingEntity({ ...addingEntity, name: e.target.value })} />
            <select aria-label="Entry segment" className={FIELD} value={addingEntity.segment_id || ""}
              onChange={(e) => setAddingEntity({ ...addingEntity, segment_id: e.target.value })}>
              <option value="">no segment</option>
              {safeMap(segments, (s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <div className="flex gap-2">
              <button className={PRIMARY} disabled={busy || !String(addingEntity.name || "").trim()}
                onClick={async () => {
                  const body = { ...addingEntity, segment_id: addingEntity.segment_id || null };
                  if (await act(() => createMarketEntity(body))) setAddingEntity(null);
                }}>
                Save
              </button>
              <button className={QUIET} onClick={() => setAddingEntity(null)}>Cancel</button>
            </div>
          </div>
        )}
        {safeMap(unattached, entityRow)}
      </section>

      <details className="border border-zinc-800/60 rounded-lg p-4">
        <summary className="text-[10px] uppercase tracking-wider text-zinc-500 cursor-pointer">
          What the agent is told
        </summary>
        <pre className="mt-3 text-[11px] text-zinc-400 whitespace-pre-wrap">
          {data?.agent_block || "Nothing yet: the agent learns about your market from what you confirm here."}
        </pre>
      </details>
    </div>
  );
}
