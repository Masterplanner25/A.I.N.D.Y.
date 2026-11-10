---
name: live-probe
description: Probing the running A.I.N.D.Y. container: minting a token, admin promotion and revert, /platform/syscall, /metrics, site-packages vs /app.
---

<!-- Moved from the root CLAUDE.md on 2026-11-09 so it loads only when working here. -->

## Live probes against the container — the recipe, so it is not re-derived

- **A token without a password:** mint one in-container with the runtime's own function —
  `docker exec <api> python -c "from AINDY.services.auth_service import create_access_token; print(create_access_token({'sub': '<user uuid>', 'email': '<email>', 'is_admin': False}, token_version=0))"`.
  Use the designated test account (`kingknight845@gmail.com`) for anything that writes; the
  owner's account only for read-only GETs on the real plan, and say so.
- **`/platform/*` needs `platform.admin`.** The test account is not admin. Approved practice:
  `UPDATE users SET is_admin=true …` before, revert after, every time — never leave it.
- `POST /platform/syscall` takes `{"name": …, "payload": …}` — the field is `name`, not `syscall`
  as the 2.19.0 handoff writes it. A user JWT carries no capabilities there (`403 … caller has
  []`); a scoped API key does.
- `/metrics` redirects (307) to **`/metrics/`**; curl the trailing slash.
- `python /tmp/script.py` inside the image imports the **site-packages** `apps`, not `/app/apps`
  — `pip install .` there is non-editable. Add `-e PYTHONPATH=/app` (or run from a mounted
  `/src`) or you audit the previous build.
- The stack must be up with `--profile full`; if `/health` is 500 and `/api/version` is 200,
  that is redis missing, not the code (Commands, above).
