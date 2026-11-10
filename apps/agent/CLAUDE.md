# Agent runs

<!-- Moved from the root CLAUDE.md on 2026-11-09 so it loads only when working here. -->

## Where an agent run's tool steps actually execute — `nodus_vm`, in the worker

`apps/agent/bootstrap.py::_select_execution_backend` makes **`nodus_vm` this app's default** on
every real boot (the runtime's own default is `agent_flow`). A plan is compiled to a native Nodus
workflow and its tool steps run as the worker's `call_tool` host function → `execute_tool`,
**in the warm-pool worker process** (`nodus_worker.py --serve`, a separate PID with its own
import of the 16-app graph). Four consequences, the first three measured 2026-09-16 and filed:

- **A tool step's LLM usage is metered in the worker** and, since runtime 2.20.0 (**FR-35**,
  #712), rides the worker's reply back and is recorded in the api process — `/metrics`, the
  Redis tenant window and the run's `score.computed.llm_tokens` all read it. Before 2.20.0 none
  of them did, so the cost governor saw planning and nothing else on this backend; now the
  tenant window moves on tool steps too, and `AINDY_QUOTA_MAX_TENANT_TOKENS` (unset here) would
  refuse guest calls it never used to see.
- **The authority gate (`register_tool(on_denial="wait")`) fires on `nodus_vm` since 2.22.0**
  (FR-38; proven 2026-09-23, `RUNTIME_2_22_0_UPGRADE.md` §4.1): a denied `leadgen.act` parks the
  run and `POST /apps/agent/runs/{id}/resume {"decision": "skip"|"abort", "note"}` decides it.
  **A park made by a process other than the api is invisible to the api until it restarts**
  (agent waits rehydrate at boot only, FR-44): a resume then answers 200 `resuming` with
  `waiters_notified: 0` and the run does not move. Read `waiters_notified`, not `run_status`.
- **The worker needs this repo pip-installed** or it cannot `import apps` — see the Nodus test
  section below. A guest execution's memory is bounded by `AINDY_NODUS_MAX_MEMORY_MB` (256,
  compose) inside the container's `mem_limit` (1536m); `test_compose_memory_bounds.py` keeps the
  three together — do not lower the cap without re-measuring `cgroup memory.peak` across a boot.
- **A run cut off by a restart is resumed at the next boot** (`AINDY_DURABLE_CONTINUATION`, ON since
  2026-10-15 as soak register row 4; `RUNTIME_2_27_0_UPGRADE.md` §7). **The flag alone resumes no agent
  run**: the runtime continues only agent types the app declares safe, and
  `apps/agent/bootstrap.py::_declare_continuation_safety` declares ours (`default`) **only while
  `AINDY_SEARCH_OUTREACH_SEND` is off.** A resumed run re-runs the step in flight at the cut, and
  `leadgen.act` with sending on really emails, with no exactly-once gate in the worker. **After every
  api restart:** `docker logs <api> | grep AgentContinuation`, and stranded `executing` runs must be 0.
  A duplicate task or draft from a resumed run is the soak's failure signal; report the run.
