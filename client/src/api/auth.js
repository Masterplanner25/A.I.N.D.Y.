import { authRequest } from "./_core.js";

export { bootIdentity, loginUser, registerUser } from "@aindy/ui-kit";

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
