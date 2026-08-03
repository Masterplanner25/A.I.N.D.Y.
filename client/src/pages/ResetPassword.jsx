import React, { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { resetPassword } from "../api/auth.js";
import { useAuth } from "../context/AuthContext";

// Mirrors the runtime's MIN_PASSWORD_LENGTH.
const MIN_PASSWORD_LENGTH = 8;

/**
 * Landing page for the emailed password-reset link (aindy-runtime >= 2.0.0).
 *
 * The runtime builds the link from `AINDY_PASSWORD_RESET_URL_TEMPLATE` with `{token}`
 * substituted, so that setting must point here — e.g.
 * `https://<host>/reset-password?token={token}`. Left empty, the runtime mails a bare
 * token with nowhere to paste it, so the field below also accepts one typed by hand.
 *
 * Reset returns **no** session token: completing it does not prove the caller holds a
 * session. So this ends at the sign-in page rather than dropping the user into the app.
 */
export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const tokenFromUrl = params.get("token") || "";
  const [token, setToken] = useState(tokenFromUrl);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!token.trim()) {
      setError("That link is missing its reset token.");
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Your new password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (password !== confirm) {
      setError("Those passwords do not match.");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      await resetPassword({ token: token.trim(), newPassword: password });
      // No token comes back by design — send them to sign in with the new password.
      navigate("/login", {
        replace: true,
        state: { notice: "Password updated. Sign in with your new password." },
      });
    } catch (err) {
      if (err?.status === 429) {
        setError("Too many attempts. Wait a minute and try again.");
      } else {
        setError(
          err instanceof Error
            ? "That reset link is invalid or has expired. Request a new one."
            : "Could not reset your password."
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#09090b] px-6 text-[#fafafa]">
      <div className="w-full max-w-md rounded-3xl border border-zinc-800 bg-zinc-950/90 p-8 shadow-2xl">
        <div className="mb-8">
          <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-[#00ffaa]">
            Account Recovery
          </p>
          <h1 className="mt-3 text-3xl font-black tracking-tight text-white">
            Choose a new password
          </h1>
          <p className="mt-2 text-sm text-zinc-500">
            Reset links expire 30 minutes after they are sent.
          </p>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          {!tokenFromUrl ? (
            <label className="block">
              <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
                Reset token
              </span>
              <input
                type="text"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                className="w-full rounded-2xl border border-zinc-800 bg-zinc-900 px-4 py-3 text-sm text-zinc-100 outline-none transition-colors focus:border-[#00ffaa]/50"
                placeholder="Paste the token from your email"
              />
            </label>
          ) : null}

          <label className="block">
            <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
              New password
            </span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-2xl border border-zinc-800 bg-zinc-900 px-4 py-3 text-sm text-zinc-100 outline-none transition-colors focus:border-[#00ffaa]/50"
              placeholder="At least 8 characters"
            />
          </label>

          <label className="block">
            <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
              Confirm new password
            </span>
            <input
              type="password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              className="w-full rounded-2xl border border-zinc-800 bg-zinc-900 px-4 py-3 text-sm text-zinc-100 outline-none transition-colors focus:border-[#00ffaa]/50"
              placeholder="........"
            />
          </label>

          {error ? (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-2xl bg-[#00ffaa] px-4 py-3 text-sm font-black uppercase tracking-[0.18em] text-black transition-colors hover:bg-[#00ffaa]/80 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400"
          >
            {submitting ? "Updating..." : "Set new password"}
          </button>
        </form>

        <p className="mt-6 text-sm text-zinc-500">
          Need a new link?{" "}
          <Link className="text-[#00ffaa] hover:text-[#7dffd2]" to="/forgot-password">
            Request one
          </Link>
        </p>
      </div>
    </div>
  );
}
