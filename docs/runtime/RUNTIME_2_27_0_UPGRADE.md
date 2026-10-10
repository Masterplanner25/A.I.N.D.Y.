---
title: "Runtime 2.27.0 adoption"
last_verified: "2026-10-10"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.27.0 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.27.0.md`. No schema change (head stays `0020`), no
ui-kit change. It answers both of our open runtime FRs: **FR-51** (python-jose replaced by PyJWT,
pymongo 4.18.2) and **FR-52** (the compatibility check on every request). Both verified live here.

## 1. The pin, and what is actually running (ask 1)

`pyproject.toml` `>=2.27.0,<3.0` and `constraints.txt` `==2.27.0`, moved together;
`test_runtime_dependency_contract.py` moves with them.

Rebuilt 2026-10-10 from a stack that was down, image `704b45b29b37`; api healthy **~30 s** after `up`
(2.26.0 took ~80 s; FR-52 was also on the boot path).

| Check | Read |
|---|---|
| version and path, in the container | `2.27.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| boot | `boot_profile=default-apps`, `app_plugins_loaded=True`, `app_plugin_count=16`; `/health` 200 |
| compatibility | `aindy-apps-monolith` `<3.0,>=2.27.0`, **`satisfied`**, from `site-packages/aindy_apps_monolith-1.0.0.dist-info`, `shadowed_metadata: []` |
| schema | none applied: runtime `0020`, app `rc2claims0001`; `[deploy_bootstrap] schema ready` |
| installed | `PyJWT 2.15.1`, `pymongo 4.18.2`, `starlette 1.7.0`; `python-jose`, `ecdsa`, `rsa`, `pyasn1` absent |
| local unit suite on 2.27.0 | green, no changes needed |

## 2. FR-51: the audit ignores come off (ask 2)

Removed from `security-audit.yml`: the four FR-51 ignores (`GHSA-3qf3-8w2g-rqmx`, `GHSA-qx36-8mw2-4r3x`,
`GHSA-v4x9-3549-crwv`, `GHSA-vp6j-j7w5-5xjj`), their stated removal condition being this adoption.

**Also removed: `PYSEC-2026-1325` (ecdsa).** Its whole ground was that ecdsa came in through
python-jose; with jose gone ecdsa is not installed, so the exemption guarded nothing. The handoff did
not list it; the runtime dropped its own copy for the same reason.

Only `PYSEC-2026-3740` (nltk, no fix released, assessed against our own call sites) remains.
`pip-audit --desc --ignore-vuln PYSEC-2026-3740` on the 2.27.0 tree: **no known vulnerabilities.**

No source of ours imports `jose`, `ecdsa`, `rsa` or `pyasn1` (checked, matching the runtime's own
check). A local venv upgraded in place keeps the four as orphans (`pip` does not remove them); a
fresh build does not have them.

## 3. FR-52: the per-request ~3 s is gone (ask 3)

`GET /apps/scores/me` on the live api, warm (3 discarded), 30 calls, owner's account (read-only):

| Run | p50 | p95 | max |
|---|---|---|---|
| 09-30, runtime 2.24.0 (before the regression) | 880 ms | 1,284 ms | |
| 2.25.0 as shipped, fresh process (`RUNTIME_2_25_0_UPGRADE.md` §7) | 3,780 ms | | |
| 2.25.0, check stubbed out | 820 ms | | 1,040 ms |
| 2.26.0 live, 10 calls | 5,081 ms | | 6,570 ms |
| **2.27.0 live, 30 calls, 30/30 OK** | **715 ms** | **1,080 ms** | 1,238 ms |

Faster than the stubbed run and the pre-regression baseline, on a host with ~440 MB available.
**Soak row 2's latency check passes again.** `idle in transaction` sampled once a second across a
20-request burst: 0–2 connections (was 2–5 on 2.25.0/2.26.0), each now about one 700 ms request long.

## 4. Dependency bumps (§3): nothing of ours

Checked against our source: no `BaseHTTPMiddleware` (so starlette 1.7.0's background-task timing
change does not reach `task_router.py`'s `BackgroundTasks`), no `import regex`, no `pyphen`.

## 5. Still owed

- **From 2.26.0:** after the first real agent runs, `docker logs <api> 2>&1 | grep
  RESOURCE_LIMIT_EXCEEDED`, and report any hit with the run's step count (ask 4). No agent runs since
  10-01, so still unmeasured.
- `AINDY_MEMORY_RECALL_OWN_SESSION` will default ON in a later release (DEC-083, from our row 1
  readout). We already run it on; that release changes nothing here.
