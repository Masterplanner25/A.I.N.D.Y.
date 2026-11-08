import ProviderKeysCard from "./ProviderKeysCard";

// Account settings. For now, one card: your own provider API keys (FR-59).
export default function Settings() {
  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-zinc-600">Settings</p>
        <h1 className="text-lg text-zinc-100">Your account</h1>
      </div>
      <ProviderKeysCard />
    </div>
  );
}
