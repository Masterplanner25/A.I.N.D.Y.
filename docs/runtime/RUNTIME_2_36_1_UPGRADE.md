---
title: "Runtime 2.36.1 adoption"
last_verified: "2026-11-18"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.36.1 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.36.1.md` (tag `v2.36.1`, #976). We come from 2.36.0, live since
2026-11-16 13:34:49Z (the recreate that took directing phase A live). **A security patch that answers FR-69.**
**No schema step:** Alembic stays `0022`, schema contract `2026-11-09`. No runtime behaviour, route, scope or default
changed. No ui-kit or aindy-sdk release.

Pin: `constraints.txt` `aindy-runtime==2.36.1`, floor `>=2.36.1,<3.0`, moved together
(`test_runtime_dependency_contract.py`).

## 1. FR-69: `dnspython` 2.9.2

The runtime moves `dnspython==2.9.0` → `==2.9.2`, which fixes GHSA-vvf4-9x63-8xvv. Still an exact pin, not the range
we asked for: the runtime's owner keeps DEC-102's range exception for certifi alone, because dnspython has an API. We
accept that; the cost is a runtime patch per future dnspython advisory, which the runtime says it will cut the same way.

**Our audit ignore for GHSA-vvf4-9x63-8xvv is removed** (`.github/workflows/security-audit.yml`), its stated removal
condition. `PYSEC-2026-3740` (nltk) is again the only ignore. FR-69 closes on this PR's `Python Dependency Audit`
running clean against 2.36.1 without the ignore.

## 2. `python-dateutil` 4.0.0

`parser.isoparse` and its siblings now refuse numeric fields of the wrong width. **Nothing of ours is affected:** no
code in `apps/`, `scripts/` or `tests/` imports `dateutil` or `pendulum` (checked 2026-11-17), the same as at 3.0.0
(`RUNTIME_2_28_2_UPGRADE.md` §2).

## 3. The rest of the batch

`idna` 3.20, `regex` 2026.11.9, `tzlocal` 5.4.5 (runtime pins; `constraints.txt` pins none of them); the platform SPA's
vite/postcss and two native-crate build dependencies, neither of which we build. SQLAlchemy stays 2.0.x; we do not pin it.

## 4. Live

Merged as #620 (its `Python Dependency Audit` passed on 2.36.1 without the ignore: **FR-69 closed**). Built
2026-11-18 (image `461eaf9bc8d3`, about two minutes with api and `mcp` stopped first for memory) and brought up with
all three profiles at **03:40:58Z**; api healthy at 03:41:28Z.

```
$ docker exec <api> python -c "import AINDY, AINDY._version as v, importlib.metadata as m; print(...)"
2.36.1 2.9.2 4.0.0 ['/usr/local/lib/python3.11/site-packages/AINDY']
```

`mcp` reports 2.36.1 too. Schema heads unchanged: runtime `0022`, app `dt1directing0001`. `/health` 200, the public
`/mcp` answers 401 without a token, postgres logged no reinitialisation.

**Counters:** the window opened 2026-11-16 13:34:49Z (the directing phase A recreate) was read just before the stop,
at 2026-11-18 03:37:20Z: **0** `aindy_payload_identity_mismatch_total` and **0** `tenant_mismatch` (neither series
present), 32 gated effects (`reserved`). A new window opened at 03:40:58Z.
