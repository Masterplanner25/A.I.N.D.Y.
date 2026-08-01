import { useState } from "react";
import { useAuth } from "../../context/AuthContext";

// Mirrors the runtime's MIN_PASSWORD_LENGTH so the obvious failure is caught before a
// round trip. The server still enforces it — this is a courtesy, not the guard.
const MIN_PASSWORD_LENGTH = 8;

export default function ChangePasswordDialog({ onClose }) {
  const { changePassword } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");

    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setError(`Your new password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("The two new passwords don't match.");
      return;
    }
    if (newPassword === currentPassword) {
      setError("Your new password must be different from your current one.");
      return;
    }

    setBusy(true);
    try {
      await changePassword(currentPassword, newPassword);
      setDone(true);
    } catch (err) {
      // The runtime distinguishes these, and the difference matters to the user:
      // 401 means they mistyped the current one, 400 means the new one was rejected.
      const status = err?.status ?? err?.response?.status;
      const detail = err?.data?.detail;
      if (status === 401) {
        setError("That current password isn't right.");
      } else if (status === 403) {
        setError("This account is disabled.");
      } else if (typeof detail === "string") {
        setError(detail);
      } else {
        setError(detail?.message || err.message || "Could not change your password.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div className="w-full max-w-md rounded-3xl border border-zinc-800 bg-zinc-950 p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-[#00ffaa]">
              Account
            </p>
            <h2 className="mt-2 text-lg font-semibold text-zinc-100">Change password</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-zinc-800 px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200"
          >
            Close
          </button>
        </div>

        {done ? (
          <div className="mt-5 space-y-4">
            <p className="text-sm text-emerald-400">Your password has been changed.</p>
            <p className="text-xs text-zinc-500">
              Any other devices you were signed in on have been signed out. This one stays
              signed in.
            </p>
            <button
              type="button"
              onClick={onClose}
              className="w-full rounded-2xl bg-[#00ffaa] px-4 py-3 text-sm font-black uppercase tracking-[0.18em] text-black"
            >
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="mt-5 space-y-3">
            <label className="block text-xs text-zinc-400" htmlFor="current-password">
              Current password
            </label>
            <input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              className="w-full rounded-md border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-sm text-zinc-100"
            />

            <label className="block text-xs text-zinc-400" htmlFor="new-password">
              New password
            </label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              className="w-full rounded-md border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-sm text-zinc-100"
            />

            <label className="block text-xs text-zinc-400" htmlFor="confirm-password">
              Confirm new password
            </label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              className="w-full rounded-md border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-sm text-zinc-100"
            />

            {error && <div className="text-xs text-red-400">{error}</div>}

            <p className="text-[11px] text-zinc-600">
              Changing your password signs out every other device.
            </p>

            <button
              type="submit"
              disabled={busy || !currentPassword || !newPassword}
              className="w-full rounded-2xl bg-[#00ffaa] px-4 py-3 text-sm font-black uppercase tracking-[0.18em] text-black disabled:opacity-40"
            >
              {busy ? "Changing..." : "Change password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
