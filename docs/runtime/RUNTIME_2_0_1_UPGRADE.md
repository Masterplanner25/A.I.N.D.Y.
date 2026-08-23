---
title: "Upgrading to aindy-runtime 2.0.1"
last_verified: "2026-08-05"
api_version: "1.0"
status: current
owner: "platform-team"
---

# Upgrading to `aindy-runtime==2.0.1`

**Released 2026-08-05. Patch — no breaking changes. It fixes the 2.0.0 upgrade path itself,
which means it fixes the three defects this deployment reported (FR-8, FR-9, FR-10).**

This is not a generic changelog restatement. Every claim below was checked against **this**
stack — the running containers and the live database — on 2026-08-05. Where something needs
no action, that is a measured result, not an assumption.

---

## TL;DR

| | Action |
|---|---|
| Version pin | **None.** `aindy-runtime>=2.0.0,<3.0` already admits 2.0.1. |
| Database / migrations | **None.** No DDL changed; Alembic head stays `0014`. |
| FR-8 unverified accounts | **None.** Already grandfathered here — verified below. |
| FR-9 `email` connector | **One decision.** Transactional mail moves off the `email` type. |
| FR-10 compose workaround | **None.** Optional cleanup only. |
| Platform UI | **Expect a visible change.** First wheel shipping the Tailwind 4 SPA. |

```bash
docker compose build --no-cache api    # picks up aindy-runtime==2.0.1
docker compose up -d api
```

---

## 1. The version pin already allows it

`pyproject.toml` line 14 pins `"aindy-runtime>=2.0.0,<3.0"`. 2.0.1 satisfies that, and the
runtime's advertised `recommended_runtime_requirement` stays `>=2.0,<3.0` — a patch does not
move the major series. **Nothing to edit.** Rebuild the image and the new wheel is picked up.

---

## 2. FR-8 — no action needed here, and it is worth knowing why

The runtime fix makes `bootstrap-schema --reconcile` grandfather rows that predate a newly
added column, so a *fresh* wheel deployment no longer leaves pre-existing accounts unverified.

**It does not retroactively repair a database that was already reconciled under 2.0.0** — the
backfill runs when the column is first added, and here that already happened. So the question
is whether this database still carries the residue.

It does not. Measured 2026-08-05:

```
 is_verified | count
-------------+-------
 f           |     2
 t           |    15
```

Both `false` rows are legitimately new accounts, not residue:

```
verify-f6997338@example.com | 2026-08-03 | f
shawn@local.test            | 2026-08-05 | f
```

The 12 pre-existing accounts grandfathered by hand in **PR #190** are all `true`, and
`alembic_version_runtime` is stamped `0014`.

**So `AINDY_REQUIRE_VERIFIED_LOGIN` is safe to enable on this stack** whenever the product
wants it — no account is stranded. What 2.0.1 buys is that the *next* deployment built from a
clean database will not need the PR #190 manual step at all.

> If another environment was upgraded to 2.0.0 and has **not** had the manual grandfathering
> applied, check it the same way before enabling the flag:
>
> ```sql
> SELECT is_verified, count(*) FROM users GROUP BY 1;
> ```
>
> and if pre-existing rows are `false`:
>
> ```sql
> UPDATE users SET is_verified = true,
>                  verified_at = COALESCE(verified_at, created_at, now())
>  WHERE is_verified = false
>    AND created_at < '<timestamp of the 2.0.0 upgrade>';
> ```

---

## 3. FR-9 — the one real change, and it is a decision

**What changes:** the runtime no longer dispatches transactional mail (verification,
password reset) to the `email` connector type. It now uses a reserved **`transactional_email`**
type that an app connector cannot intercept.

**What that means here.** `apps/automation/services/automation_execution_service.py`
registers six connectors, including `"email"`:

```python
handlers = {
    "social": _social_connector,
    "crm": _crm_connector,
    "email": _email_connector,      # <-- stops receiving runtime transactional mail
    "webhook": _webhook_connector,
    "stripe": _stripe_connector,
    "subscription": _subscription_connector,
}
```

After the upgrade, `_email_connector` keeps serving user-authored automations exactly as it
does today, and **stops** being handed runtime mail. Nothing is registered under
`transactional_email`, so the runtime falls back to its own SMTP — which is already configured
on this stack (`AINDY_SMTP_HOST=mailpit`, `AINDY_SMTP_FROM` set). **Password reset and
verification mail keep working**, over a different route.

Pick one:

**Option A — do nothing (recommended).** Runtime SMTP carries transactional mail. The
shape-multiplexing added to `_email_connector` in PR #190 becomes dead code and can be
deleted, along with the two regression tests covering the transactional shape. The automation
path is untouched.

**Option B — keep owning delivery.** Register a seventh handler under `transactional_email`
and drop the multiplexing branch, because the shape is now single and published:

```python
{"type": "send", "to": "<recipient>", "subject": "<subject>", "body": "<plain text>"}
```

Branch on `action["type"]` and treat anything unrecognised as unhandled. Contract:
`docs/runtime/CONNECTOR_CONTRACT.md` §5a in the runtime repo.

**Either way, a failure is now loud.** A registered-connector failure on transactional mail
logs at **ERROR** naming the type, instead of the single WARNING that made this defect so hard
to find. The no-fallback rule is unchanged and deliberate — a broken registered connector does
**not** silently reroute to SMTP.

---

## 4. FR-10 — nothing to do

`docker-compose.prod.yml` already carries the workaround on both affected variables:

```yaml
AINDY_REQUIRE_VERIFIED_LOGIN: "${AINDY_REQUIRE_VERIFIED_LOGIN:-false}"   # line 56
AINDY_NEXT_ACTION_ACTING:     "${AINDY_NEXT_ACTION_ACTING:-false}"       # line 115
```

That keeps working. With 2.0.1 the runtime treats an empty value as unset and falls back to
the field default, so the bare `${VAR:-}` form is safe again and **28 typed bool settings** are
covered, not just these two.

Reverting to `${VAR:-}` is optional and there is no reason to. The explicit `:-false` doubles
as documentation of the intent, and the warning comments above each line stay accurate as
history.

---

## 5. Expect the Platform UI to look different

**2.0.1 is the first release whose wheel ships the Tailwind 4 SPA.** The runtime's Platform UI
is packaged inside the wheel (`AINDY/platform/dist/**` as package data), not built by the
Dockerfile — so the api container serves whatever UI was packaged into the pinned version.

After the rebuild, `/platform` will render from a rebuilt stylesheet: vite 6→8, tailwind 3→4,
react-router 6→7, `@aindy/ui-kit` 1.x→2.0.0. It was verified in a browser before release —
buttons, borders, dark theme, ui-kit components and charts — not just by a green build, because
Tailwind 4 can compile cleanly while emitting the wrong rules.

Flagging it only because it is a **visible change nobody here asked for**, and an unexplained
UI shift during an unrelated upgrade is exactly the kind of thing that costs an afternoon.

---

## 6. Also in this release (no action)

- **`cryptography` 49.0.0 → 50.0.0** — CVE-2026-69247, a Bleichenbacher oracle in PKCS7
  decryption. Not reachable in the runtime (the only consumer is Ed25519 extension signing;
  no PKCS7 or S/MIME call exists, and JWT signing is HS256), but patched rather than exempted.
  The release's sandbox-escape gate resolved `cryptography-50.0.0`, so the published artifact
  demonstrably carries it.
- **Dependency bumps:** fastapi 0.141.1, uvicorn 0.52.0, pytest 9.1.1, certifi, tqdm.
- **Sandbox posture unchanged** — the Linux escape gate returned 17/17 PASS on the `v2.0.1`
  tag (audit log Entry 013). No change to `sandbox_runner.py`, the OCI flags, the capability
  set, or the container image.

---

## 7. Schema — read this if anything asserts on the contract version

`SCHEMA_CONTRACT_VERSION` moves **`2026-08-02` → `2026-08-05`**, and **no DDL changed.**

The bump is mechanical: `orm_hash` is a content hash of every file under `AINDY/db/models/`,
and the FR-8 fix added an `info={"reconcile_backfill": ...}` declaration to two columns on
`User`. Alembic head stays `0014`. A schema diff before and after will show nothing.

If any test, health assertion, or deployment gate here pins the expected contract version,
**update it to `2026-08-05`** — that is the only code change this upgrade can require.

---

## 8. Verification after the rebuild

```bash
# 1. Runtime version
docker exec <api> python -c "import importlib.metadata as m; print(m.version('aindy-runtime'))"
# expect: 2.0.1

# 2. Boots clean — this is what FR-10 broke
docker compose ps          # api Up, not restarting
docker compose logs --tail=50 api | grep -i "validation error"   # expect nothing

# 3. Transactional mail still lands (FR-9 route change)
#    Register a throwaway account, then check mailpit at http://localhost:8025
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"upgrade-check@local.test","username":"upgradecheck","password":"upgrade-8chars"}'
# expect: 202, and a verification mail in mailpit

# 4. No unverified residue
docker exec <postgres> psql -U aindy -d aindy -c \
  "select is_verified, count(*) from users group by 1;"
```

Step 3 is the one that matters — it exercises the FR-9 route change end to end. A `202` with
**no** mail in mailpit means transactional delivery is broken, which is precisely the failure
2.0.1 exists to prevent; check the api logs for an `[email]` ERROR line, which will now name
the connector type.

---

## References

- Runtime CHANGELOG: `aindy-runtime` `CHANGELOG.md` § 2.0.1
- Connector contract: `aindy-runtime` `docs/runtime/CONNECTOR_CONTRACT.md` §5a
- Sandbox audit: `aindy-runtime` `docs/runtime/SANDBOX_ESCAPE_AUDIT.md` Entry 013
- Runtime tracking: `aindy-runtime` `TECH_DEBT.md` → `APP-FR-*` → FR-8/9/10
- This repo: `docs/runtime/RUNTIME_FEATURE_REQUESTS.md` (where FR-8/9/10 were filed),
  PR #190 (the manual grandfathering + `_email_connector` multiplexing)
