---
title: "Release handoff — A.I.N.D.Y. carries a release to the end after you start it"
last_verified: "2026-10-15"
api_version: "1.0"
status: current
owner: "app-team"
---

# Release handoff — A.I.N.D.Y. carries a release to the end after you start it

**Status:** SCOPED 2026-10-14. **Phase 1 BUILT 2026-10-14** (§7.1): decisions 1 and 2 taken that day (§8).
Proven against the recorded 2.27.0 responses, then **live on 2026-10-15** on the test account: the api's
scheduler walked the finished 2.27.0 run to `done` in one tick (approver Masterplanner25, gate wait 634 s),
completed the release task, wrote the note, created the adoption task and delivered the email through Gmail.
The first real use (2.28.0, with a live gate) is still owed.

**Where it comes from.** The owner's product review on 2026-10-14 named this as the first real test of
*persistent execution*. The use case was the owner's own: *"hand a release off to A.I.N.D.Y.,
continue developing, receive a notification at the approval gate, approve, and let execution
continue."* The owner settled the product question the same day (#467): **the Infinity Algorithm is the
product, and outside systems are access to its state.** So the handoff is judged by one rule: does it
feed the algorithm? A release becomes an outcome the algorithm records (a completed task, a memory note,
events). A transcript of it does not count. MCP read access (#468) was step 1. This is step 2.

---

## 1. How a release runs today (measured 2026-10-14)

aindy-runtime is the only repository with a gate. Its release is:

1. A release PR (`release: 2.27.0`: version, folded changelog, `APP_HANDOFF_v<X>.md`), merged.
2. A `v*.*.*` tag. It starts `.github/workflows/publish.yml`:

   | Job | Notes |
   |---|---|
   | `validate-version`, `lint`, `platform-ui-build` | parallel, seconds |
   | `build` → `install-smoke-test` | about 1.5 min |
   | `publish-testpypi` | environment `testpypi`, no protection |
   | **`publish-pypi`** | **environment `production`, protection `required_reviewers`**, the gate |
   | `verify-published-wheel` | boots the wheel from PyPI (`smoke-postgres.yml`) |
   | `github-release` | |

3. The app adopts it: pin and floor move together (`constraints.txt` and `pyproject.toml`),
   `RUNTIME_<X>_UPGRADE.md`, rebuild, verify. That is the work this session does every release.

**Most of the run is waiting for the owner.** The gate wait is the end of `publish-testpypi` to the start
of `publish-pypi`:

| Release | Run | Whole run | Waiting at the gate |
|---|---|---|---|
| 2.25.0 | 36961041217 | 10 min 12 s | 6 min 12 s |
| 2.26.0 | 37231275081 | 10 min 36 s | 6 min 25 s |
| 2.27.0 | 38025672838 | 14 min 18 s | **10 min 34 s** |

GitHub records who approved (`GET /actions/runs/{id}/approvals`: `Masterplanner25 approved
production` on 2.27.0). The owner already approves on GitHub. What is missing is being *told* when to
approve, without watching the run.

## 2. What the handoff does

The owner, or Claude in the runtime repo, prepares the release as today, up to the tag. Then:

1. **Handoff.** A.I.N.D.Y. is given the repository and the tag (from Collaborator, or from Claude Code
   over MCP in phase 2). It finds the `publish.yml` run for that tag and takes it from there.
2. **It follows the run** and records each stage (§3).
3. **At the gate it notifies the owner** with the version, how long the run took to reach the gate, and
   the direct link to GitHub's approval page.
4. **After approval** it follows PyPI, the wheel check and the GitHub Release.
5. **It records the outcome where the algorithm sees it** (§5): a completed task, a memory note, events,
   and the next task (*Adopt aindy-runtime X in A.I.N.D.Y.*, with the handoff doc's link).
6. **A failure is an outcome too.** A failed job notifies the owner with the job's name and log link,
   and the task records it. A run cancelled or rejected at the gate stops the handoff. Nothing retries
   on its own.

**It stops at "published, the wheel verified, the adoption task created".** The adoption needs judgment:
reading the handoff and deciding what to verify. That stays with the owner and Claude (decision 5).

No AI is needed while the handoff runs. Every step is a fact read from GitHub. The review's point, which
is the design: *"autonomy does not require continuous AI reasoning."*

## 3. Stages

`release_handoffs.stage`, moved forward only by the watcher (§4):

| Stage | Entered when (GitHub Actions, the tag's `publish.yml` run) | Then |
|---|---|---|
| `requested` | the handoff is recorded | the watcher looks for the run |
| `running` | the run is found and in progress | |
| `at_gate` | `GET /actions/runs/{id}/pending_deployments` lists `production` | **notify** |
| `approved` | the gate clears: `publish-pypi` starts; `approvals` names who and when | |
| `published` | `publish-pypi` succeeds | |
| `done` | `verify-published-wheel` and `github-release` succeed | **record the outcome, notify** |
| `failed` | any job concludes `failure`, or the run `cancelled` / rejected at the gate | **notify**, record |

Every transition writes one row of history: stage, time, the job or approval behind it. A transition
is idempotent: the watcher reads the current truth from GitHub each tick, so a missed tick or a restart
loses nothing. **A run not found within 30 minutes of the handoff** fails as `no_run` (a tag that was
never pushed, or a workflow that did not start), and the owner is notified. A handoff with no stage
change in 3 hours fails as `stalled`. Both limits are settings.

## 4. How it is built

**A record and a watcher job, not an agent run and not a waiting flow.**

- **`release_handoffs`** (app migration, guarded like every other): `id`, `user_id`, `repo`, `tag`,
  `version`, `run_id`, `stage`, `stage_at`, `history` (JSON list), `approved_by`, `approved_at`,
  `failure` (job, conclusion, URL), `task_id`, `created_at`. The domain is `automation`, which already owns
  scheduled work.
- **`release_handoff_watch`**, a scheduled job every minute (`register_scheduled_job`) in the api process.
  For each handoff not in `done` / `failed` it reads the run, its jobs, its pending deployments and its
  approvals, and moves the stage forward. Four GitHub calls per active handoff per minute, against a
  limit of 5,000 an hour.
- **Events.** Each transition emits a system event, `release.<stage>`, so the runtime's ledger and the
  Infinity loop see the release as it happens.
- **GitHub access** through one small client (`apps/automation/services/github_actions.py`) with the
  token from the environment (decision 2). Network calls go through the runtime's external-call
  wrapper, as the drafter's and the Resolution Check's do, so they are counted and time-limited.

**Why not a waiting runtime flow.** The flow engine waits on *events*, with a typed resume and a timeout,
and restores waits after a restart. A *time* wait is a rehydration fallback "for future time-based WAIT
nodes" (`core/flow_run_rehydration.py`), not a node, so *"check again in a minute"* has no clean shape.
And a wait registered by a process other than the api is invisible to the api until it restarts
(FR-44), which is exactly where an MCP handoff would start one. A table plus a job survives restarts
with nothing extra, is tested like any service, and needs nothing from the runtime. If time waits
become a node, the watcher can become a flow without changing §3.

**Why not an agent run.** Nothing here needs a plan or a model, and a run that waits ten minutes ties up
an agent run for ten minutes.

## 5. What the algorithm records

| Record | Feeds |
|---|---|
| A task, *Release aindy-runtime X*, created at handoff, completed at `done` (`time_spent` = handoff to done, in seconds) | `execution_speed` (tasks), the plan's progress if it sits on a strategy |
| On failure the task stays open. **Tasks have no notes field**, so the failing job, its conclusion and its link live on the handoff record (`failure`, shown on the card) and in the failure email | the support loop sees work that did not finish |
| A memory note at `done`: version, the stage times, who approved, the gate wait, the release URL. **A note of the outcome, not a log.** | recall: the next plan or adoption can find it |
| `release.<stage>` system events | the runtime's ledger, the Infinity loop's event counts |
| A new task, *Adopt aindy-runtime X in A.I.N.D.Y.*, linking `docs/upgrades/APP_HANDOFF_vX.md` | the next piece of work, where the owner will look |

## 6. Notifications

Sent at `at_gate`, `done` and `failed`, and never more than once per stage per handoff:

- **Email**, through the runtime's `email_channel.send_email` (the same path outreach uses). On this
  stack `AINDY_SMTP_HOST=mailpit`, so mail lands in Mailpit (`localhost:8025`), which the owner
  would not see away from the desk. Real delivery needs real SMTP settings (decision 1).
- **A Collaborator card**: *"aindy-runtime 2.28.0 is waiting for your approval (gate reached 04:56)"*,
  with the link and the stage history. It clears itself once the stage moves.

The gate notification carries the GitHub approval link (the run's page). In phases 1 and 2 **the owner
approves on GitHub**, and A.I.N.D.Y. sees it within a minute.

## 7. Phases

| Phase | Builds | Needs |
|---|---|---|
| **1. Follow and notify** | the table and migration, the watcher, the GitHub client, events, the tasks and memory note, email and the Collaborator card, `POST /apps/releases` (handoff) and `GET /apps/releases` | decisions 1, 2 |
| **2. Hand off from Claude Code** | `sys.v1.release.handoff {repo, tag}` and `sys.v1.release.status` on the MCP launcher. **The first write tool there.** It only *records* the handoff (caller-scoped, `ctx.user_id`), and the api's watcher does the rest, so no wait is ever registered outside the api (FR-44). The launcher stays read-only for everything else. | phase 1 |
| **3. Approve from A.I.N.D.Y.** | an Approve or Reject button, and an MCP tool, that answer GitHub's pending deployment (`POST /actions/runs/{id}/pending_deployments`) as the owner | decision 3, a token that can approve |
| **4. Other repositories** | Nodus packages, aindy-sdk, ui-kit, once one has a gate | decision 4 |

### 7.1 Phase 1 as built (2026-10-14)

| Piece | Where |
|---|---|
| Table | `release_handoffs`, migration `rh1handoff0001` (adds `notified`, `run_url`, `task_name`, `adoption_task_id`, `memory_node_id`, `finished_at` to §4's list) |
| GitHub client | `apps/automation/services/github_actions.py`: `find_run` (the tag is the run's `head_branch`), `get_run`, `jobs`, `pending_deployments`, `approvals` |
| Watcher | `release_handoff_service.release_handoff_watch`, scheduled job `release_handoff_watch`, every minute; `observe()` turns the four responses into stages and is pure |
| Routes | `GET /apps/releases`, `POST /apps/releases` (`docs/api/API_REFERENCE.md`, Releases) |
| Card | `client/src/components/app/ReleasePanel.jsx`, on Collaborator's empty screen above Recent runs; the handoff form is folded behind "Hand off a release" |
| Settings | `AINDY_GITHUB_TOKEN`, `AINDY_RELEASE_NOTIFY_TO` (default: the account's email), `AINDY_RELEASE_REPOS`, `AINDY_RELEASE_NO_RUN_MINUTES` (30), `AINDY_RELEASE_STALL_MINUTES` (180) |
| Tests | `tests/unit/test_release_handoff.py` (17), `client/src/test/release-panel.test.jsx` (4) |

Where the build settled what the design left open:

- **The gate is read from two facts.** `pending_deployments` naming `production` while the run waits, or
  `Publish to PyPI` having started once it has passed. Its time is TestPyPI's `completed_at`, so the gate
  wait is computed from the run's own job times (634 s on 2.27.0), not from when a tick happened to look.
- **The gate notification goes out only while the run is still waiting there.** A tag handed off after
  its gate, or a run that passes the gate between two ticks, has nothing to ask of the owner, so it gets
  only the `done` (or `failed`) email.
- **A notification is recorded whether or not it was delivered** (`notified[stage]`, with the error), and
  is not retried every minute.
- **A tag handed off again after a failure reuses its open release task**, so a retried release does not
  leave duplicate tasks.
- **A released tag cannot be handed off again** (409). Found live: a second handoff of the done 2.27.0
  wrote a second adoption task.
- **No token, no handoff.** `POST` answers 503 without `AINDY_GITHUB_TOKEN`; a handoff that no tick could
  read would sit at `requested` forever.
- **The stall limit applies at the gate too.** A run left unapproved for 3 hours stops being followed, and
  the owner is told; hand the tag off again to resume.
- **The release task is completed through `sys.v1.task.complete_full`**, the same path as the agent's
  `task.complete`, so the Infinity re-score runs.

**Proof before a real release.** Point the watcher at the finished 2.27.0 run (38025672838). It must
walk `running → at_gate → approved → published → done` from the run's own job times, name the
approver, compute the 10 min 34 s gate wait, and write the task and the note. That is a test against
recorded GitHub responses, and once against the live API, read-only. **Then the first real use is
2.28.0.**

**Tests (phase 1):**
- each stage from recorded job and deployment responses;
- a failed job, a cancelled run, a rejected gate;
- no run found, and stalled;
- restart safety: the same tick twice changes nothing;
- one notification per stage;
- the outcome records;
- the handoff is caller-scoped.

## 8. Open decisions — the owner's

1. **Where notifications reach you.** **DECIDED 2026-10-14: real email**, with the card as well. Recommended: **real email**, SMTP settings in `.env` (for example a
   Gmail app password), with the Collaborator card as well. Alternative: Mailpit and the card only,
   which works only at the desk.
2. **A GitHub token for A.I.N.D.Y.** **DECIDED 2026-10-14: fine-grained, aindy-runtime only, Actions: read**, as
   `AINDY_GITHUB_TOKEN` (compose lists it). Recommended: **fine-grained, aindy-runtime only, Actions: read**, in
   `.env` as `AINDY_GITHUB_TOKEN`, never in the repository. That is enough for phases 1 and 2 (runs,
   jobs, pending deployments, approvals).
3. **Who approves.** Recommended: **GitHub only, to start** (phases 1 and 2). Phase 3 gives A.I.N.D.Y. the
   authority to release as you. It needs a token that can approve deployments (to verify: the
   fine-grained permission GitHub requires for `pending_deployments` POST) and is worth taking only
   after a few releases have run through phase 1.
4. **Which repositories.** Recommended: **aindy-runtime only**, the one with a gate.
5. **Where "done" ends.** Recommended: **published, the wheel verified, the adoption task created.**
   Adoption stays with you and Claude, because it needs judgment. An agent run that prepares the adoption
   PR could follow later. It would be its own decision.
