import ProviderKeysCard from "./ProviderKeysCard";
import WatcherKeysCard from "./WatcherKeysCard";

// Account settings: your own provider API keys (FR-59) and your watcher key (audit D1).
export default function Settings() {
  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-zinc-600">Settings</p>
        <h1 className="text-lg text-zinc-100">Your account</h1>
      </div>
      <ProviderKeysCard />
      <WatcherKeysCard />
    </div>
  );
}
