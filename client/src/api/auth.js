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
