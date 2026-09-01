import React, { useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { requestPasswordReset } from "../api/auth.js";
import { useAuth } from "../context/AuthContext";

/**
 * Request a password-reset link (aindy-runtime >= 2.0.0).
 *
 * Reached from the login page, because someone who needs this cannot sign in — it must
 * live outside the authenticated shell.
 *
 * `POST /auth/password/forgot` always returns 200 whether or not the address exists, so
 * the confirmation below is deliberately neutral. The only error worth showing is 503
 * (no email channel configured), which is a property of the deployment rather than of
 * any account.
 */
export default function ForgotPasswordPage() {
  const { isAuthenticated } = useAuth();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!email.trim()) {
      setError("Enter the email address on your account.");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      await requestPasswordReset(email.trim());
      setSubmitted(true);
    } catch (err) {
      if (err?.status === 503) {
        setError(
          "Password reset is unavailable: this deployment has no email channel configured. Contact your administrator."
        );
      } else if (err?.status === 429) {
        setError("Too many reset requests. Wait a minute and try again.");
      } else {
        setError(err instanceof Error ? err.message : "Could not send the reset link.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Identical whether or not the address is registered — saying otherwise would turn this
  // into an account-enumeration oracle, which is exactly what the uniform 200 prevents.
  if (submitted) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#09090b] px-6 text-[#fafafa]">
        <div className="w-full max-w-md rounded-3xl border border-zinc-800 bg-zinc-950/90 p-8 shadow-2xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-[#00ffaa]">
            Check Your Email
          </p>
          <h1 className="mt-3 text-2xl font-black tracking-tight text-white">
            Reset link sent
          </h1>
          <p className="mt-3 text-sm text-zinc-400">
            If <span className="text-zinc-200">{email.trim()}</span> has an account, a
            password reset link is on its way.
          </p>
          <p className="mt-3 text-xs text-zinc-600">
            The link expires in 30 minutes.
          </p>
          <Link
            to="/login"
            className="mt-6 inline-block rounded-2xl border border-zinc-700 px-4 py-3 text-sm text-zinc-300 hover:border-zinc-500 hover:text-zinc-100"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#09090b] px-6 text-[#fafafa]">
      <div className="w-full max-w-md rounded-3xl border border-zinc-800 bg-zinc-950/90 p-8 shadow-2xl">
        <div className="mb-8">
          <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-[#00ffaa]">
            Account Recovery
          </p>
          <h1 className="mt-3 text-3xl font-black tracking-tight text-white">
            Reset your password
          </h1>
          <p className="mt-2 text-sm text-zinc-500">
            Enter your email and we will send you a link to choose a new password.
          </p>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
              Email
            </span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="w-full rounded-2xl border border-zinc-800 bg-zinc-900 px-4 py-3 text-sm text-zinc-100 outline-hidden transition-colors focus:border-[#00ffaa]/50"
              placeholder="you@aindy.ai"
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
            {submitting ? "Sending..." : "Send reset link"}
          </button>
        </form>

        <p className="mt-6 text-sm text-zinc-500">
          Remembered it?{" "}
          <Link className="text-[#00ffaa] hover:text-[#7dffd2]" to="/login">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
