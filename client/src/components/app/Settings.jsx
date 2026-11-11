import ConnectedAppsCard from "./ConnectedAppsCard";
import ProviderKeysCard from "./ProviderKeysCard";
import WatcherKeysCard from "./WatcherKeysCard";

// Account settings: your own provider API keys (FR-59), your watcher key (audit D1), and the AIs connected over
// MCP (FR-66; owner, 2026-11-11).
export default function Settings() {
  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-zinc-600">Settings</p>
        <h1 className="text-lg text-zinc-100">Your account</h1>
      </div>
      <ProviderKeysCard />
      <WatcherKeysCard />
      <ConnectedAppsCard />
    </div>
  );
}
