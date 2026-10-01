import { useState } from "react";
import { addPresence, removePresence } from "../../api/works.js";
import { safeMap } from "../../utils/safe";

// Where a work is on the web, and its header or bio there, in your words (RESOLUTION_CHECK_SPEC §2.2).
// Owner, 2026-09-30: "we can use the content/sites as a control … these things are also connections."
// Declared, never crawled.

const FIELD = "w-full bg-zinc-900/60 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-100 placeholder-zinc-600 focus:outline-hidden focus:border-[#00ffaa]/50";
const BUTTON = "px-3 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-40";
const QUIET = `${BUTTON} border border-zinc-700 text-zinc-400 hover:bg-zinc-800`;

export default function PresenceEditor({ work, onChange, onError }) {
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const presence = Array.isArray(work.presence) ? work.presence : [];

  const run = async (fn) => {
    setBusy(true);
    try {
      await fn();
      await onChange();
      return true;
    } catch (e) {
      onError?.(e?.body?.message || e?.message || "Something went wrong.");
      return false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      {presence.length > 0 && (
        <div className="space-y-1">
          <span className="text-[10px] text-zinc-600 uppercase tracking-wider">On the web</span>
          {safeMap(presence, (p) => (
            <div key={p.id} className="flex items-start justify-between gap-3 text-[11px]">
              <div>
                <span className="text-zinc-300">{p.platform}</span>
                {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="ml-2 text-zinc-500 underline break-all">{p.url}</a>}
                {p.self_description && <p className="text-zinc-400 mt-0.5">“{p.self_description}”</p>}
              </div>
              <button aria-label={`Remove ${p.platform}`} className="text-zinc-500 hover:text-red-400" disabled={busy}
                onClick={() => run(() => removePresence(p.id))}>×</button>
            </div>
          ))}
        </div>
      )}
      {draft ? (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <input aria-label={`Platform for ${work.name}`} className={FIELD} placeholder="Platform: LinkedIn, Website…"
              value={draft.platform} onChange={(e) => setDraft({ ...draft, platform: e.target.value })} />
            <input aria-label={`Address for ${work.name}`} className={FIELD} placeholder="https://…"
              value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} />
          </div>
          <textarea aria-label={`Header for ${work.name}`} className={`${FIELD} resize-none`} rows={2}
            placeholder="Its header or bio there, as you wrote it (optional)"
            value={draft.self_description} onChange={(e) => setDraft({ ...draft, self_description: e.target.value })} />
          <div className="flex gap-2">
            <button className={QUIET} disabled={busy || !draft.platform.trim()}
              onClick={async () => { if (await run(() => addPresence(work.id, draft))) setDraft(null); }}>
              Save
            </button>
            <button className={QUIET} onClick={() => setDraft(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button className="text-[11px] text-zinc-500 hover:text-zinc-300"
          onClick={() => setDraft({ platform: "", url: "", self_description: "" })}>
          + where it is on the web
        </button>
      )}
    </div>
  );
}
