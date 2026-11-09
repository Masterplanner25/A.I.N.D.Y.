import { useCallback, useEffect, useState } from "react";
import { createWatcherKey, listWatcherKeys, revokeWatcherKey } from "../../api/watcher.js";
import { safeMap } from "../../utils/safe";

// The watcher (audit D1, owner 2026-11-08): it watches which app is in front and reports focus sessions, so
// focus_quality (15% of your score) stops being a fixed 50. Run it on this laptop with scripts/watcher.py and a key
// from here. A key can only send watcher signals; it is shown once.

const BUTTON = "px-3 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-40";

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

export default function WatcherKeysCard() {
  const [keys, setKeys] = useState(null);
  const [name, setName] = useState("laptop");
  const [fresh, setFresh] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () =>
      listWatcherKeys().then(setKeys, (e) => {
        setKeys([]);
        setError(errorText(e, "Could not load your watcher keys."));
      }),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  const create = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const made = await createWatcherKey(name.trim() || "laptop");
      setFresh(made?.key ? made : made?.data ?? made);
      await load();
    } catch (err) {
      setError(errorText(err, "Could not make a key."));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (id) => {
    setBusy(true);
    setError("");
    try {
      await revokeWatcherKey(id);
      await load();
    } catch (err) {
      setError(errorText(err, "Could not revoke that key."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="border border-zinc-800/60 rounded-lg p-4 space-y-3" data-testid="watcher-keys">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-zinc-600">Watcher key</p>
        <p className="text-xs text-zinc-400 mt-1">
          The watcher reports your focus sessions from this laptop, so focus quality (15% of your score) reflects real
          work. A key can only send watcher signals, and they count for you.
        </p>
      </div>
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
      {fresh?.key &&
        <div className="rounded border border-[#00ffaa]/40 p-3 space-y-1" data-testid="watcher-key-fresh">
          <p className="text-xs text-[#00ffaa]">Copy this key now. It won't be shown again.</p>
          <code className="block break-all text-xs text-zinc-100 select-all">{fresh.key}</code>
          <p className="text-[11px] text-zinc-500">
            Save it in <code>~/.aindy/watcher_key</code> (or set <code>AINDY_WATCHER_KEY</code>), then run{" "}
            <code>venv\Scripts\python scripts\watcher.py</code> from the repo.
          </p>
          <button type="button" className={`${BUTTON} border border-zinc-700 text-zinc-400`} onClick={() => setFresh(null)}>
            I've saved it
          </button>
        </div>
      }
      {keys === null ? <p className="text-[11px] text-zinc-500">Loading…</p> :
        <ul className="space-y-1">
          {keys.length === 0 && <li className="text-[11px] text-zinc-500">No watcher key yet.</li>}
          {safeMap(keys, (k) =>
            <li key={k.id} className="flex items-center justify-between gap-2 text-xs text-zinc-300">
              <span>{k.name} <span className="text-zinc-500">{k.key_prefix ? `${k.key_prefix}… ` : ""}{k.created_at ? `· ${new Date(k.created_at).toLocaleDateString()}` : ""}</span></span>
              <button type="button" className={`${BUTTON} border border-zinc-700 text-zinc-400`} disabled={busy} onClick={() => revoke(k.id)}>
                Revoke
              </button>
            </li>
          )}
        </ul>
      }
      <form className="flex flex-wrap gap-2" onSubmit={create}>
        <input
          aria-label="Watcher key name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200"
        />
        <button type="submit" className={`${BUTTON} bg-[#00ffaa] text-black`} disabled={busy}>Make a key</button>
      </form>
    </section>
  );
}
