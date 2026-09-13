---
title: "Runtime 2.13.0 upgrade — adoption"
last_verified: "2026-09-13"
api_version: "1.0"
status: current
owner: "app-team"
---

# Runtime 2.13.0 upgrade — adoption

Floor moved `>=2.12.0,<3.0` → `>=2.13.0,<3.0`; build pin `==2.12.0` → `==2.13.0`; the dependency
contract test asserts the two agree. Handoff: `aindy-runtime/docs/runtime/APP_HANDOFF_v2.13.0.md`.

**No schema step, no required code change.** Verified rather than taken from the handoff:
runtime Alembic head unchanged at `0018`; `git diff v2.12.0 v2.13.0 -- AINDY/db/models
AINDY/memory/memory_persistence.py` is empty. The diff under `AINDY/` is 25 files; ten of them
are modules this repo imports from, and **every one is additive on the symbols we take**:

| Module we import | What changed in it | Our symbols affected |
|---|---|---|
| `platform_layer/llm_client.py` | adds `LLMBudgetExceededError(LLMCallError)`, `find_budget_refusal`; `call_method`/`chat` now pass through a budget reservation (inert until a cap is set) | `LLMCallError`, `get_llm_client` — unchanged |
| `platform_layer/trace_context.py` | adds `trace_scope()`; documents `ensure_trace_id` | `ensure_trace_id`, `get_current_trace_id` — unchanged |
| `agents/runtime_api.py` | `create_agent_run_runtime` answers a budget refusal with 429 (was 500); uses `trace_scope` internally | signature unchanged |
| `kernel/syscall_registry.py` | `flow.run` lifts a `partial` marker onto its envelope | `SYSCALL_REGISTRY`, `SyscallContext`, `SyscallEntry` — unchanged |
| `platform_layer/async_job_service.py` | two ContextVar resets on early-return paths | our four functions unchanged |
| `kernel/resource_manager.py`, `kernel/syscall_dispatcher.py`, `core/execution_gate.py`, `platform_layer/metrics.py` | tokens as a resource dimension; reaping of minted units; declared ceilings enforced; four new counters | we import nothing that changed shape |

`register_tool` and every `register_*` hook: byte-identical. Nothing removed anywhere.

---

## 1. The dev venv is on the right runtime this time

The 2.12.0 adoption found this venv importing a stale 2.6.0 and fixed it. Re-checked before
this adoption, printing the path (the only instrument that says where it answered from):

```
$ venv/Scripts/python.exe -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
2.12.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # before
2.13.0 ['C:\\dev\\aindy-apps-monolith\\venv\\Lib\\site-packages\\AINDY']    # after pip install -c constraints.txt
```

So the unit suite below ran against 2.13.0, not against a memory of it.

---

## 2. Gained on adoption, nothing to wire

- **Our planner's spend is attributed.** `planner_anthropic.py` calls
  `get_llm_client("anthropic").call_method("messages_create", …)` from inside the runtime's
  `generate_plan`, which now declares the tenant around whichever backend runs. The runtime
  side of this (#635) was verified live against **our image** on 2026-09-13: one plan →
  `aindy_llm_calls_total{attributed="unit",provider="anthropic"} 1`, `aindy_llm_tokens_total`
  prompt 2021 / completion 223. **We changed nothing for it.**
- **Route envelopes are coherent.** A syscall dispatched inside one of our requests carries the
  request's `trace_id` (== `X-Trace-ID`) and `execution_unit_id`; before 2.13.0 each dispatch
  minted its own UUID and leaked a usage snapshot per call. `test_trace_id_envelope_contract.py`
  (the 2.12.0 probe) still passes — this extends the same property to the syscall envelope.
- **A scheduler-thread trace bug is gone** (#633): the first flow a scheduler thread ran pinned
  that thread's `trace_id` for every later flow. Our watcher/task flows run from the scheduler;
  if two unrelated runs ever shared a trace id in RippleTrace, that was the cause.

---

## 3. The one consumer-visible change, checked against our source: `flow.run` can return `partial`

Only when a flow declares `FanOutEdgeGroup(..., join="any" | "quorum")` and a branch fails.
**We declare none** — `grep -rn FanOutEdgeGroup apps/` → 0 files — so no flow of ours can
produce it. The 2.9.0 rule (branch `!= "success"`, never `== "error"`) is now load-bearing rather
than latent. Our two remaining `== "error"` sites were read, not grepped:

- `apps/rippletrace/services/content_ingest.py:743` — a `poll_source` outcome dict, not a
  syscall envelope.
- `apps/social/routes/social_router.py:196` — the canonical HTTP response in an adapter, not a
  syscall envelope.

Both fine. If we adopt fan-out later, `all` (the default) fails whole exactly as before.

---

## 4. Not taken: the three opt-in knobs — shipped, off, and staying off for now

| Knob | Why not yet |
|---|---|
| `AINDY_QUOTA_MAX_TENANT_TOKENS` | The governor works (verified live against our image: admit, admit, **429** at an 8,000-token window). But the reservation is the caller's `max_tokens` — ours is **4096** in `planner_anthropic.py`, so each plan reserves ~5.2k until it reconciles to ~2.3k. A window sized from typical actuals would refuse the second plan. **Decide the window against `max_tokens × plans-per-window-you-mean-to-allow`, with a number from `aindy_llm_tokens_total` in production first**, not this week. |
| `AINDY_QUOTA_MAX_TOKENS` | Per-execution; does not cover planning (the run does not exist yet). Same sizing rule. |
| `AINDY_RUN_SCOPED_QUOTA` | Makes the 100-syscall cap real for a whole guest script / agent run. Read `aindy_syscall_unowned_unit_total` on the container first — it names exactly what this moves. |

Alarm on `aindy_llm_budget_outcomes_total{outcome="refused"}` when a cap is eventually set.

---

## 5. Verification

```bash
# venv imports 2.13.0 from site-packages (path printed) — §1
venv/Scripts/python.exe -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
#  expect: 2.13.0 ['...\\venv\\Lib\\site-packages\\AINDY']

# declared range and pin agree, and the interpreter satisfies them
venv/Scripts/python.exe -m pytest tests/unit/test_runtime_dependency_contract.py -q

# In the container, after the rebuild
docker exec <api> python -c "import AINDY, AINDY._version as v; print(v.__version__, list(AINDY.__path__))"
#  expect: 2.13.0 ['/usr/local/lib/python3.11/site-packages/AINDY']
curl -sL http://localhost:8000/metrics/ | grep -cE "^# HELP aindy_(llm_calls|llm_budget_outcomes|syscall_unowned_unit|resource_usage_evicted)_total"
#  expect: 4   (note /metrics 307s to /metrics/ — a bare /metrics reads 0 families)
```

### Unit suite on 2.13.0 (2026-09-13, this venv)

Full `tests/unit` suite against the installed 2.13.0 (path printed, §1): **exit 0, reached 100%, zero failures or errors** — run to a file, not piped through `tail`. The count is not quoted: the suite's `-q` config suppresses the summary line, and a number read off progress dots has been wrong before (runtime #605).

### Container rebuilt and verified (2026-09-13, later the same day)

`docker compose ... build --no-cache api` → image `d79a5bc9060f`, `Successfully installed ...
aindy-runtime-2.13.0`. Full stack up (`--profile full --profile mail`, both compose files);
api `healthy` in ~40 s. Every §5 container check passed, each read rather than assumed:

| Check | Result |
|---|---|
| version + path in the container | `2.13.0 ['/usr/local/lib/python3.11/site-packages/AINDY']` |
| `aindy-runtime bootstrap-schema` | exit 0 |
| Alembic heads | runtime `0018`, app `ga1shadow0001` — unchanged |
| four new `# HELP` families on `/metrics/` | all four present |
| `aindy_llm_budget_outcomes_total{outcome="refused"}` | **no sample** — the only grep hit is the HELP line, whose text contains the word "refused"; a `grep -c` reads 1 and lies |
| `/api/version` | `boot_profile=default-apps`, `app_plugins_loaded=True`, `app_plugin_count=16` |
| the three §4 knobs in the container | all unset |
| logs after boot | 0 postgres cluster reinits, 0 tracebacks, 0 scheduler-saturation lines |

The labelled counters (`aindy_llm_calls_total`, `aindy_llm_budget_outcomes_total`,
`aindy_syscall_unowned_unit_total`) have no samples until something fires them — that is a
correct reading of an unfired labelled counter, not an absent meter. `aindy_resource_usage_evicted_total`
is unlabelled and reads `0.0`.

**Cost of `--no-cache` on this host, for the next adoption:** the apt layer re-downloaded ~80
Debian packages over a link measuring ~78 kB/s *from Windows itself* (not a VM problem), which
took ~25 minutes before pip ever ran. `constraints.txt` is `COPY`'d before the pip `RUN`, so the
pip layer invalidates on a pin move by itself; `--no-cache` buys re-running apt, nothing more.
Check `curl -w '%{speed_download}' http://deb.debian.org/...` before choosing it.

### What this does not establish

The handoff's step 4 — one planner call, then `aindy_llm_calls_total{attributed="unit"}` — was
not run here: it spends a real Anthropic call and writes an `AgentRun` into the owner's database,
so it is the owner's to trigger. The runtime team's live measurement of that path (#635) was
against our image with the 2.13.0 wheel installed, sharing this compose stack's Postgres/Redis.
