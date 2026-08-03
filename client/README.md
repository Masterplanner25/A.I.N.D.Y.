# A.I.N.D.Y. Client

React + Vite frontend for the A.I.N.D.Y. application shell.

## Rendering Safety

The frontend now treats array-shaped data as untrusted until proven otherwise.

- Shared guards live in `client/src/utils/safe.js`
- `safeArray(value)` returns `value` only when it is an actual array
- `safeMap(value, fn)` logs a development warning and returns `[]` when `value` is not an array

Use `safeMap(...)` for UI list rendering and other array iteration in React components instead of direct `.map(...)` calls.

Example:

```jsx
import { safeMap } from "../utils/safe";

{safeMap(data.items, (item) => (
  <Row key={item.id} item={item} />
))}
```

This is now the required pattern for:

- profile data
- memory results
- dashboard collections
- agent run lists
- RippleTrace graph inputs

Direct member `.map(...)` calls are disallowed by ESLint outside the safe utility implementation.

## Identity Boot Flow

The client now boots the application in two stages:

1. `POST /auth/login` returns a JWT
2. the client immediately calls `GET /identity/boot`

Signup reaches that path only after email verification (aindy-runtime >= 2.0.0):

1. `POST /auth/register` returns **202 with no token** and emails a verification link.
   The response is identical whether or not the address already exists — that uniformity
   is what closes the account-enumeration oracle, so the UI must never infer from it.
2. the user opens the link, which lands on `/verify-email?token=...`
3. `POST /auth/verify-email` returns the JWT; it is stored and the client calls
   `GET /identity/boot`

The register page lives at `/register` and ends on a "check your email" screen — there is
no token to auto-boot with. `/verify-email` is where the session actually begins.

Password recovery sits outside the authenticated shell, since anyone who needs it cannot
sign in:

1. `/login` links to `/forgot-password`
2. `POST /auth/password/forgot` **always** returns 200 — the confirmation must stay
   neutral about whether the address exists. A 503 means the deployment has no email
   channel; that is safe to show, as it describes the server rather than an account.
3. the emailed link lands on `/reset-password?token=...`
4. `POST /auth/password/reset` returns **no** token, so the user is sent to `/login` with
   a notice rather than being logged in

Both URL templates are runtime settings and must point at these routes:
`AINDY_EMAIL_VERIFY_URL_TEMPLATE` → `/verify-email?token={token}`, and
`AINDY_PASSWORD_RESET_URL_TEMPLATE` → `/reset-password?token={token}`.

`/identity/boot` is the canonical hydration source for:

- `user_id`
- recent memory
- recent agent runs
- current metrics
- active flows
- derived `system_state`

Immediately after signup, boot should include:

- the initial `"User account created"` memory node
- one initialized execution placeholder in recent runs
- baseline metrics with `score = 0.0` and `trajectory = "baseline"`

This state is stored in:

- `AuthContext` for token, login, register, and logout
- `SystemContext` for booted application state

Protected routes require a token. If boot has not completed yet, the app stays behind the boot gate instead of rendering an empty dashboard.

## Token Handling

The client stores the JWT in both:

- `localStorage["token"]`
- `localStorage["aindy_token"]`

The second key is retained for backward compatibility with existing code paths.

All API requests sent through `client/src/api.js` attach:

`Authorization: Bearer <token>`

`client/src/api.js` also normalizes common array response fields before returning parsed JSON to React. If a known array field arrives as `null`, `undefined`, or a non-array value, the client converts it to `[]`.

## Development

Typical commands:

```bash
npm install
npm run dev
```

Production build:

```bash
npm run build
```

Linting enforces the safe mapping rule:

```bash
npm run lint
```
