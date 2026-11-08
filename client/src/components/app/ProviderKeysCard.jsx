import { useCallback, useEffect, useState } from "react";
import { deleteProviderKey, listProviderKeys, setProviderKey } from "../../api/auth.js";
import { safeMap } from "../../utils/safe";

// Your own API keys (FR-59). When the server turns per-user keys on, your model and search calls
// are paid with these; without one a feature says "Add it in Settings". Write-only: a stored key
// is never shown again, only its last four characters.

const PROVIDERS = [
  { id: "openai", label: "OpenAI", uses: "Collaborator, Genesis, drafts, SEO, article answers, research summaries, the Resolution Check's judge" },
  { id: "perplexity", label: "Perplexity", uses: "web research, lead search, mention search, the Resolution Check" },
  { id: "anthropic", label: "Anthropic", uses: "the Resolution Check's Claude answers, the Claude planner" },
  { id: "deepseek", label: "DeepSeek", uses: "ARM code analysis and generation" },
];

const BUTTON = "px-3 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-40";
const PRIMARY = `${BUTTON} bg-[#00ffaa] text-black hover:bg-[#00ffaa]/80`;
const QUIET = `${BUTTON} border border-zinc-700 text-zinc-400 hover:bg-zinc-800`;

function errorText(err, fallback) {
  const raw = err?.data ?? err?.body;
  let body = raw;
  if (typeof raw === "string") {
    try {
      body = JSON.parse(raw);
    } catch {
      body = null;
    }
  }
  const detail = body?.detail ?? body;
  if (err?.status === 503) return "Provider keys aren't switched on for this server yet.";
  if (typeof detail === "string") return detail;
  return detail?.message || body?.message || fallback;
}

function KeyRow({ provider, stored, busy, onSave, onRemove }) {
  const [value, setValue] = useState("");
  const set = Boolean(stored);
  return (
    <div className="space-y-2 border-t border-zinc-800/60 pt-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm text-zinc-200">{provider.label}</p>
          <p className="text-[11px] text-zinc-500">{provider.uses}</p>
        </div>
        <p className="text-[11px] text-zinc-400">
          {set
            ? `Set · ending ${stored.key_hint}${stored.updated_at ? ` · ${new Date(stored.updated_at).toLocaleDateString()}` : ""}`
            : "Not set"}
        </p>
      </div>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim()) onSave(provider.id, value.trim()).then((ok) => ok && setValue(""));
        }}
      >
        <input
          type="password"
          autoComplete="off"
          aria-label={`${provider.label} API key`}
          placeholder={set ? "Paste a new key to replace it" : "Paste your API key"}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600"
        />
        <button type="submit" className={PRIMARY} disabled={busy || !value.trim()}>
          {set ? "Replace" : "Save"}
        </button>
        {set && (
          <button type="button" className={QUIET} disabled={busy} onClick={() => onRemove(provider.id)}>
            Remove
          </button>
        )}
      </form>
    </div>
  );
}

export default function ProviderKeysCard() {
  const [keys, setKeys] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () =>
      listProviderKeys().then(setKeys, (e) => {
        setKeys([]);
        setError(errorText(e, "Could not load your keys."));
      }),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  const run = async (action, done) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(done);
      await load();
      return true;
    } catch (e) {
      setError(errorText(e, "That didn't work."));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const byProvider = Object.fromEntries(safeMap(keys || [], (k) => [k.provider, k]));
  const label = (id) => PROVIDERS.find((p) => p.id === id)?.label || id;

  return (
    <section className="border border-zinc-800/60 rounded-lg p-4 space-y-3">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-zinc-600">Your API keys</p>
        <p className="text-xs text-zinc-400 mt-1">
          Your own keys pay for your model and search calls. A key is stored encrypted and never shown again, only its
          last four characters.
        </p>
      </div>
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
      {notice && <p className="text-xs text-[#00ffaa]">{notice}</p>}
      {keys === null ? (
        <p className="text-[11px] text-zinc-500">Loading…</p>
      ) : (
        safeMap(PROVIDERS, (provider) => (
          <KeyRow
            key={provider.id}
            provider={provider}
            stored={byProvider[provider.id]}
            busy={busy}
            onSave={(id, value) => run(() => setProviderKey(id, value), `${label(id)} key saved.`)}
            onRemove={(id) => run(() => deleteProviderKey(id), `${label(id)} key removed.`)}
          />
        ))
      )}
    </section>
  );
}
