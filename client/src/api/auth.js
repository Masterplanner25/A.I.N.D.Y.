import { authRequest } from "./_core.js";

export { bootIdentity, loginUser, registerUser } from "@aindy/ui-kit";

/**
 * Consume an emailed verification token and start the session (aindy-runtime >= 2.0.0).
 *
 * Registration returns 202 with no token; this is where the access token comes from.
 * Idempotent server-side — following an already-used link succeeds rather than erroring,
 * so a double-click or a prefetching mail client does not break the flow.
 */
export async function verifyEmailToken(token) {
  const response = await authRequest("/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
  const accessToken = response?.access_token ?? response?.data?.access_token;
  if (!accessToken) {
    throw new Error("Verification succeeded but no session token was returned. Please sign in.");
  }
  return accessToken;
}

/**
 * Start password recovery (aindy-runtime >= 2.0.0).
 *
 * **Always resolves on success regardless of whether the address exists** — the runtime
 * returns a uniform 200 so the endpoint cannot be used to test which emails are
 * registered. Callers must not infer anything from it, and must not report "no such
 * account".
 *
 * The one legitimate failure is 503: no email channel is configured on the deployment.
 * That describes the *server*, identically for every caller, and leaks nothing about any
 * account — so it is safe (and useful) to surface plainly.
 */
export async function requestPasswordReset(email) {
  await authRequest("/auth/password/forgot", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  return true;
}

/**
 * Consume an emailed reset token and set a new password (aindy-runtime >= 2.0.0).
 *
 * Deliberately returns **no** session token: completing a reset does not prove the caller
 * holds a session, so they are sent to sign in with the new password. Do not try to
 * auto-login from this response — there is nothing in it to log in with.
 */
export async function resetPassword({ token, newPassword }) {
  await authRequest("/auth/password/reset", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  return true;
}

/**
 * Rotate the signed-in user's password (aindy-runtime >= 1.11.0).
 *
 * Not re-exported from @aindy/ui-kit: the route is newer than the kit's auth surface,
 * so it is written against the runtime-owned `/auth` prefix directly.
 *
 * Returns the freshly-versioned access token. The change bumps `token_version`, which
 * invalidates **every** session including this one — the caller must store the returned
 * token or the next request 401s and the user is bounced to the login screen.
 */
export async function changePassword({ currentPassword, newPassword }) {
  const response = await authRequest("/auth/password/change", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
  const token = response?.access_token ?? response?.data?.access_token;
  if (!token) {
    throw new Error("Password changed, but no new session token was returned. Please sign in again.");
  }
  return token;
}
