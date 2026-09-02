---
title: "Runtime 2.7.0 upgrade — adoption"
last_verified: "2026-09-02"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.7.0 upgrade — adoption

Floor moved `>=2.6.0,<3.0` → `>=2.7.0,<3.0`. Plain `pip install`: no schema step, no
migration, no flag to flip. The upstream handoff's verification of that is reproduced
below rather than taken on trust.

Three sections of that handoff needed a decision from us. Two of them we do not land in
the way a quick read would suggest.

---

## 1. §1 applies to us — and the handoff's table would suggest otherwise

`AINDY_ASYNC_SCHEDULER_DISPATCH` is new and defaults on. Where it applies, queued work
goes to the thread pool instead of executing inside the 1-second scheduler tick. It is
the fix for FR-15.

The handoff scopes it by `EXECUTION_MODE`, and its table reads:

> `EXECUTION_MODE=distributed` — *what `docker-compose.prod.yml` sets* — Nothing changes.

**That sentence is about the runtime's own compose file, not ours.**
`aindy-runtime/docker-compose.prod.yml:39` sets `EXECUTION_MODE: distributed`. Our
`docker-compose.prod.yml` does not set it anywhere — the only occurrence is a comment at
line 12 explaining how to opt in. Nothing in our `.env` files sets it either. The runtime
default is `thread` (`AINDY/config.py:341`), and `_SCHEDULER_ASYNC_DISPATCH_DEFAULT` is
`True`.

So we are in the **first** row of that table, in production as well as in dev: dispatch
behaviour changes for us. Reading the handoff as "our prod is distributed, so §1 is not
our problem" would have been the natural mistake and it would have been wrong.

Confirmed at boot on this branch:

```
EXECUTION_MODE : thread
```

### Why this matters beyond a config note

FR-15's defect is that `schedule()` was the only queue drainer, ran each item
synchronously, and was registered `max_instances=1` — so **one slow flow blocked every
other queued item**, plus wait expiry and stale-wait cleanup, which share that tick.

That is the mechanism `CLAUDE.md` describes as the scheduler saturation trap, and it is a
live candidate explanation for the unexplained stall half of `GENESIS-TURN-LATENCY-1` —
the ~14–18 minute whole-API outage that #257 explicitly did **not** claim to fix. It is a
hypothesis, not a finding: nothing here measures it. See TECH_DEBT.md.

Observability is new too, and is the only way to tell which behaviour is live, because
reading the env var cannot answer it (distributed mode overrides the setting):

```
aindy_execution_dispatch_total{mode="async"}    # new behaviour
aindy_execution_dispatch_total{mode="inline"}   # old behaviour
```

Opt out with `AINDY_ASYNC_SCHEDULER_DISPATCH=0`.

---

## 2. §3 — the new dispatch refusal, checked against the call site we added last week

`dispatch()` now raises `UndistributableWorkError` rather than enqueueing work onto the
distributed queue with no `log_id` in its context
(`AINDY/core/execution_dispatcher.py:395`).

This is worth more than a skim for us specifically, because **#257 added a new dispatch
call site** — `genesis_message_orchestrate` submits `sys.v1.job.submit` for
`analytics.infinity_recalc`. The handoff says a new call site is exactly what trips this.

Verified safe, by following the path rather than assuming it:

- `sys.v1.job.submit` → `_handle_job_submit` → `submit_async_job`, which creates a
  `JobLog` row and dispatches with `context={"log_id": log_id, ...}`
  (`async_job_service.py:657`, and the retry path at `:1324`).
- The guard reads `context.get("log_id")`, which is populated on both.
- It only fires on the distributed path in any case, and we run `thread`.

No change required.

---

## 3. §4 — the nltk exemption, on our own grounds

2.7.0 pins `nltk==3.10.3`. That **closes FR-24** (`PYSEC-2026-3726`, the symlink
arbitrary file read that reddened `main` from 2026-08-31). It also introduces a *new*
finding: `PYSEC-2026-3740` / `CVE-2026-81726` / `GHSA-8mgp-746c-j5xp` is open against
3.10.3 **with no fix released**.

We now carry it as an ignore in `.github/workflows/security-audit.yml`, alongside the
existing `PYSEC-2026-1325` (ecdsa).

**The runtime's first ground for its own exemption does not transfer to us, and must not
be copied.** It states that `import nltk` has zero hits across the runtime. That is false
here — `apps/search/services/seo_services.py:7` imports nltk directly. FR-24 said as much
and used it as the reason *not* to add an ignore then.

So this was assessed against our own call sites:

| ground | our finding |
|---|---|
| affected component is `TransitionParser` | zero references in `apps/`, `tests/`, `scripts/` |
| requires a caller-controlled model path | our only `nltk.data.find` passes the literal `"tokenizers/punkt"` (`seo_services.py:21`) |
| other call surface | `nltk.word_tokenize(normalized)` (`seo_services.py:35`) — takes text, not a model path |

The exemption comment records the condition that voids it: app code calling
`TransitionParser`, or passing a non-literal path to `nltk.data.find` or any nltk loader.

**Do not "fix" this by pinning nltk back to 3.10.0.** That reintroduces
`PYSEC-2026-3726`, which *does* have a fix — trading a fixed vulnerability for an unfixed
one to quiet a scanner.

---

## 4. Steps taken

1. `pyproject.toml` floor → `aindy-runtime>=2.7.0,<3.0`.
2. `tests/unit/test_runtime_dependency_contract.py` asserts the exact specifier string —
   moved in lockstep to `"<3.0,>=2.7.0"`. It fails loudly if these drift.
3. `.github/workflows/security-audit.yml` — added `--ignore-vuln PYSEC-2026-3740` with
   the assessment above.

---

## 5. Verification

Local runtime code is exactly v2.7.0: the sibling checkout is two commits past the tag
and `git diff --name-only v2.7.0..HEAD` filtered of `*.md` and `docs/` is empty, so the
extra commits are documentation only.

| check | result |
|---|---|
| `test_runtime_dependency_contract.py` | pass |
| app-profile subset (7 files, `-m app_profile`) | 55 passed |
| boot smoke | `boot_profile=default-apps`, `app_plugins_loaded=True`, count **16** |
| `scripts/check_app_imports.py` | 37 declared, 0 undeclared |
| `ruff check apps/ tests/` | clean |
| `pip-audit` with both ignores | **nltk no longer flagged** |

Upstream's own verification of the "nothing to do" claim, re-run here:

```bash
git diff v2.6.0..v2.7.0 -- AINDY/db/models/ AINDY/memory/memory_persistence.py   # empty
git diff v2.6.0..v2.7.0 -- alembic/versions/                                     # empty
git diff v2.6.0..v2.7.0 -- AINDY/routes/ | grep enforce_api_key_scope            # no hits
```

### What this does not establish

The local `pip-audit` run is against a developer machine's global site-packages, which
carries findings for packages that are not in this project's dependency closure (`pip`
itself among them). It is evidence that the nltk ignore works, not that CI is green.
Linux CI is the authority on that.

Nothing here exercises §1's behaviour change. The dispatch metric is the instrument;
reading it needs a running stack.

---

## 6. Deliberately NOT in this plan

- **No `EXECUTION_MODE` change.** We stay on `thread` by default. Switching to
  `distributed` would *disable* the FR-15 fix (the runtime refuses async scheduler
  dispatch there, deliberately and for good reason — see §1 of the handoff), and it is a
  deployment decision, not an upgrade step.
- **No `AINDY_ASYNC_SCHEDULER_DISPATCH` override.** The default is on and we want it on.
- **No nodus-lang action.** §2's three security fixes arrive with the pin; we changed no
  code for them.
