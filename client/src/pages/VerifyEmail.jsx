import React, { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useSystem } from "../context/SystemContext";

/**
 * Landing page for the emailed verification link (aindy-runtime >= 2.0.0).
 *
 * Registration returns 202 with no token; this is where the session actually starts.
 * The runtime builds the link from `AINDY_EMAIL_VERIFY_URL_TEMPLATE` with `{token}`
 * substituted, so that setting must point here — e.g.
 * `https://<host>/verify-email?token={token}`.
 *
 * Verification is idempotent server-side, so following an already-used link succeeds
 * rather than erroring. That matters because mail clients prefetch links.
 */
export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { isAuthenticated, verifyEmail } = useAuth();
  const { bootSystem } = useSystem();
  const [status, setStatus] = useState("verifying");
  const [error, setError] = useState("");
  // StrictMode double-invokes effects in dev; verifying twice is harmless server-side
  // but would race two boots, so guard it.
  const startedRef = useRef(false);

  const token = params.get("token") || "";

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    if (!token) {
      setStatus("error");
      setError("That link is missing its verification token.");
      return;
    }

    (async () => {
      try {
        const accessToken = await verifyEmail(token);
        await bootSystem(accessToken);
        setStatus("done");
        navigate("/dashboard", { replace: true });
      } catch (err) {
        setStatus("error");
        setError(
          err?.data?.detail?.message ||
            err?.message ||
            "That verification link is invalid or has expired."
        );
      }
    })();
  }, [token, verifyEmail, bootSystem, navigate]);

  if (isAuthenticated && status === "done") {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#09090b] px-6 text-[#fafafa]">
      <div className="w-full max-w-md rounded-3xl border border-zinc-800 bg-zinc-950/90 p-8 shadow-2xl">
        <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-[#00ffaa]">
          Email Verification
        </p>

        {status === "verifying" && (
          <>
            <h1 className="mt-3 text-2xl font-black tracking-tight text-white">
              Confirming your address
            </h1>
            <p className="mt-3 text-sm text-zinc-400">One moment.</p>
          </>
        )}

        {status === "error" && (
          <>
            <h1 className="mt-3 text-2xl font-black tracking-tight text-white">
              Could not verify
            </h1>
            <p className="mt-3 text-sm text-red-400">{error}</p>
            <p className="mt-3 text-xs text-zinc-600">
              Verification links expire after 48 hours. Register again to get a new one.
            </p>
            <div className="mt-6 flex gap-3">
              <Link
                to="/register"
                className="rounded-2xl bg-[#00ffaa] px-4 py-3 text-sm font-black uppercase tracking-[0.18em] text-black"
              >
                Register
              </Link>
              <Link
                to="/login"
                className="rounded-2xl border border-zinc-700 px-4 py-3 text-sm text-zinc-300 hover:border-zinc-500 hover:text-zinc-100"
              >
                Sign in
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
