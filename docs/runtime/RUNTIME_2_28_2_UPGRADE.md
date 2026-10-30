---
title: "Runtime 2.28.2 adoption"
last_verified: "2026-10-27"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.28.2 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.28.2.md` (tag `v2.28.2`, commit `efcaa7d`). A security
patch: no schema change (head stays `0020`, contract `2026-09-20`), no behaviour, route, scope or default
change, no ui-kit release (2.1.1 stays). `publish.yml`'s job names and production gate are unchanged, so
the release watcher (`release_handoff_watch`) is unaffected; only action SHA pins moved.

## 1. The two security fixes

pip-audit flags a 2.28.1 image for both, and **neither gets an audit ignore** (the runtime's ask):

| Package | Move | Advisory | Exposure here |
|---|---|---|---|
| `pymongo` | 4.18.2 → 4.18.3 | CVE-2026-106435 / GHSA-98qm-wvgf-w4cf (high): out-of-bounds read in the BSON C extension, availability only | nil in practice (runtime's assessment) |
| `dnspython` | 2.8.0 → 2.9.0 | CVE-2026-114605 / GHSA-45c3-73f7-pv4m (high): CPU burn on DNS name decompression | reached only when pymongo resolves a `mongodb+srv://` URL. **Ours is plain `mongodb://`** (`docker-compose.mongo.yml`), so it is not reachable on this stack |

Both are exact pins in the runtime (`pymongo==4.18.3`, `dnspython==2.9.0`), so the only way to take
them is the runtime release. We pin neither.

## 2. python-dateutil 3.0.0 (major)

2.28.2 also moves `python-dateutil` 2.9.0.post0 → `==3.0.0`. Its breaking changes are all in
`dateutil.tz`: PEP 495 offsets for times in a DST gap, `TZPATHS` removed, relative `gettz` keys raise,
`dateutil.zoneinfo` deprecated. The runtime never imports dateutil (pendulum uses only `dateutil.parser`).
**No app code imports dateutil at all** (`git grep dateutil -- apps scripts tests`: none, 2026-10-27).

`python-dotenv` is still `==1.2.3`, so the `pytest-env <1.8` hold in `dependabot.yml` (#477) stays.

## 3. Done here

The pin and the floor moved together: `constraints.txt` `==2.28.2`, `pyproject.toml` `>=2.28.2,<3.0`,
`test_runtime_dependency_contract.py`, and the CLAUDE.md contract block.

## 4. Not yet: the rebuild

**The image must be rebuilt for the fixes to reach the container**, and it is deliberately deferred: the
owner cannot take a rebuild until about 2026-10-29. That is also when window 3 of
`aindy_payload_identity_mismatch_total` is owed (`RUNTIME_2_28_0_UPGRADE.md` §4). **Read the counter
before the recreate**: it resets with the container.

Until the rebuild the api runs 2.28.1 with pymongo 4.18.2 and dnspython 2.8.0. Per §1, neither is
reachable here. After the rebuild, check in the container:

```bash
docker exec <api> python -c "import AINDY, AINDY._version as v, pymongo, dns.version, dateutil; print(v.__version__, list(AINDY.__path__), pymongo.version, dns.version.version, dateutil.__version__)"
# expect: 2.28.2 ['/usr/local/lib/python3.11/site-packages/AINDY'] 4.18.3 2.9.0 3.0.0
```

and then `/health`, the schema head, and the `AgentContinuation` log, as in `RUNTIME_2_28_1_UPGRADE.md` §3.
The same rebuild brings anthropic 2.x into the image (#500); see the first planner run after it.

## 5. Verified

Window 3 of the identity counter was read first (0 over 793 dispatches, `RUNTIME_2_28_0_UPGRADE.md` §4).
Then the image was rebuilt from `main` at #504 (`a27fed397a14`, 4 min 50 s), and the api recreated at
**2026-10-30 02:36:51Z**. That opens window 4. Healthy after ~40 s, 0 restarts.

| Where | Result |
|---|---|
| api container | `2.28.2 ['/usr/local/lib/python3.11/site-packages/AINDY'] 4.18.3 2.9.0 3.0.0`; anthropic `2.3.0` |
| `/api/version` | `boot_profile=default-apps`, `app_plugins_loaded=True`, `app_plugin_count=16` |
| schema | runtime `0020`; app `wk3shared0001 → sd1share0001` at boot; all 229 existing `drop_points` `share_drafts = skipped` |
| Nodus flags; approve token | all four `1`; `AINDY_GITHUB_APPROVE_TOKEN` set |
| agent runs `executing`; `AgentContinuation` log | 0 before and after; empty (soak row 4) |

This rebuild also brought #486 → #501 live (the four Nodus workflows, release phase 3, share drafts). Still to check:
the 07:00 UTC log line `(N via nodus)`, RippleTrace's order and the YouTube feed, "Read as:" in the SEO
meta, and the first planner run on anthropic 2.x.
