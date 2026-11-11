import { useCallback, useEffect, useState } from "react";
import { listMcpGrants, revokeMcpGrant } from "../../api/mcpGrants.js";
import { safeMap } from "../../utils/safe";

// Connected apps (owner, 2026-11-11): the AIs you let read A.I.N.D.Y. over MCP, such as claude.ai and ChatGPT
// (scripts/CLAUDE.md, "claude.ai and ChatGPT"). They read only; disconnecting ends their access.
// The site a connection returns to is shown first: an app's name is whatever it registered itself as.

const BUTTON = "px-3 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-40";

const SCOPE_LABELS = {
  "memory.read": "memory",
  "work.context": "your Works",
  "work.facts": "facts about a Work",
};

function scopeText(scopes) {
  const labels = safeMap(scopes, (s) => SCOPE_LABELS[s] || s);
  return labels.length ? `reads ${labels.join(", ")}` : "";
}

function day(value) {
  return value ? new Date(value).toLocaleDateString() : "";
}

function errorText(err, fallback) {
  let body = err?.data ?? err?.body;
  if (typeof body === "string") {
    try {
      body = JSON.parse(body);
    } catch {
      body = null;
    }
  }
  const detail = body?.detail ?? body;
  if (typeof detail === "string") return detail;
  return detail?.message || body?.message || fallback;
}

export default function ConnectedAppsCard() {
  const [grants, setGrants] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () =>
      listMcpGrants().then(setGrants, (e) => {
        setGrants([]);
        setError(errorText(e, "Could not load your connected apps."));
      }),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  const disconnect = async (id) => {
    setBusy(true);
    setError("");
    try {
      await revokeMcpGrant(id);
      await load();
    } catch (err) {
      setError(errorText(err, "Could not disconnect that app."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="border border-zinc-800/60 rounded-lg p-4 space-y-3" data-testid="connected-apps">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-zinc-600">Connected apps</p>
        <p className="text-xs text-zinc-400 mt-1">
          AIs you let read A.I.N.D.Y., such as Claude and ChatGPT. They can read your Works and memory, never change
          them. Disconnecting ends an app's access within seconds; to use it again, it asks you to sign in.
        </p>
      </div>
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
      {grants === null ? <p className="text-[11px] text-zinc-500">Loading…</p> :
        <ul className="space-y-2">
          {grants.length === 0 && <li className="text-[11px] text-zinc-500">No apps connected.</li>}
          {safeMap(grants, (g) =>
            <li key={g.id} className="flex items-center justify-between gap-2 text-xs text-zinc-300">
              <span className="min-w-0">
                <span className="text-zinc-100">{g.redirect_host || "unknown site"}</span>
                {g.client_name && <span className="text-zinc-500"> · calls itself {g.client_name}</span>}
                <span className="block text-[11px] text-zinc-500">
                  {[scopeText(g.scopes),
                    g.created_at && `connected ${day(g.created_at)}`,
                    g.last_used_at && `last used ${day(g.last_used_at)}`].filter(Boolean).join(" · ")}
                </span>
              </span>
              <button type="button" className={`${BUTTON} border border-zinc-700 text-zinc-400`} disabled={busy}
                      onClick={() => disconnect(g.id)}>
                Disconnect
              </button>
            </li>
          )}
        </ul>
      }
    </section>
  );
}
