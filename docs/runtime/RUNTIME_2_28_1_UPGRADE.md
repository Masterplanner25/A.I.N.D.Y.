---
title: "Runtime 2.28.1 adoption"
last_verified: "2026-10-22"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.28.1 adoption

From `aindy-runtime/docs/upgrades/APP_HANDOFF_v2.28.1.md`. A security patch: no schema change (head
stays `0020`, contract `2026-09-20`), no behaviour change, no ui-kit release. It answers **FR-54**,
filed by us the same day.

## 1. FR-54: certifi (security)

`Python Dependency Audit` went red on #481 (a resolution-check change) with nothing of ours involved:
**PYSEC-2026-4320 / GHSA-6q48-6c7w-9gw2**. `certifi` before 2026.10.18 bundles *emSign ECC Root CA - G3*,
and eight eMudhra intermediates chaining to it have compromised, revoked keys, so anyone holding one
can issue a certificate for any hostname that `requests`/`httpx` would trust. Ours trust it for every
outbound call: OpenAI, DeepSeek, Anthropic, Perplexity, GitHub.

Runtime 2.28.0 pinned `certifi==2026.7.22` exactly, so we could not take the fix. #482 ignored the
advisory with a removal condition and filed FR-54; the runtime shipped 2.28.1 the same day (#846) with
**`certifi>=2026.10.19`, a lower bound on purpose (DEC-102)**: a CA bundle is the one dependency whose
newest release is the safest, so the next one installs without a runtime release. Our pip-audit runs
were the first signal: the runtime's own audit had last run before the advisory reached OSV.

**Done here:** the pin and the floor moved together (`constraints.txt` `==2.28.1`, `pyproject.toml`
`>=2.28.1,<3.0`, `test_runtime_dependency_contract.py`); the `PYSEC-2026-4320` ignore removed from
`security-audit.yml`, its condition met; FR-54 marked shipped. **We do not pin certifi ourselves**, and
if we ever add a constraint for it, it must be a lower bound too, or it re-creates the problem from
our side.

**The image must be rebuilt.** A container keeps the CA bundle it was built with.

## 2. The rest of the release

The runtime's 2026-10-19 dependency batch (#845): pydantic 2.14.1, alembic 1.20.0, pendulum 3.3.0,
MarkupSafe 3.0.4, tzdata 2026.5, react/react-dom 19.3.1 in the platform SPA, and build-time pyo3/cc for
the native crate. None is a security fix and none of them is pinned by us.

`python-dotenv` is still `==1.2.3` in 2.28.1, so the `pytest-env <1.8` hold in `dependabot.yml` (#477)
stays.

## 3. Verified

| Where | Result |
|---|---|
| api container: `AINDY._version`, `AINDY.__path__`, `certifi.__version__` | pending the rebuild |
| `/health` | pending the rebuild |
| schema | runtime `0020`; app head `wk3shared0001` (#481, applied by the same rebuild) |
| agent runs `executing` after the restart; `AgentContinuation` log | pending the rebuild |
