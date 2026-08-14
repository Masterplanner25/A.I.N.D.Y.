---
title: "Session Handoff — 2026-08-06"
last_verified: "2026-08-06"
api_version: "1.0"
status: current
owner: "app-team"
---

# Session Handoff — 2026-08-06

**Arc:** started as a runtime 2.0.0 adoption, became a security fix and a cleanup pass, and ended
as a product-identity settlement — four open design decisions resolved and three new specs, all
grounded in build docs that turned out to be years ahead of the surface.

**15 PRs merged (#188–#202).** `main` at `aa8fab2`. Stack on `aindy-runtime==2.0.1`, healthy.

---

## 1. What shipped

| PR | Area | What |
|---|---|---|
| **#188** | runtime / client | Adopt 2.0.0 — pin move + "check your email" register flow, together |
| **#189** | auth | Password recovery UI — forgot + reset pages |
| **#190** | email | Unbreak transactional mail: the `email` connector was swallowing it |
| **#191** | docs | File FR-8/9/10 |
| **#192** | runtime | Adopt 2.0.1 — retire the FR-9 workaround, close FR-8/9/10 |
| **#193** | masterplan | Scope the Domain Engine (structural path) |
| **#194** | arm | **Security:** confine file analysis to the project root |
| **#195** | chore | Remove four dead twins; fix the nodus flake and a wrong CLAUDE.md note |
| **#196** | docs | Refresh two stale handoffs against the code |
| **#197** | masterplan | Domain Engine Phase 5 — emergent domain detection |
| **#198** | docs | Settle what each surface is for (walk items 10, 17, 19, 23) |
| **#199** | client | Name the agent face **Collaborator**; realign trust tiers to canon |
| **#200** | docs | Scope the terminal agent |
| **#201** | docs | Spec self-trust as calibration |
| **#202** | docs | Spec cognitive operations |

---

## 2. The security fix (#194) — walk item 20, closed

ARM analyzes files on the **server's** filesystem. `validate_file_path` guarded with a
blocked-segment list and an extension allowlist, and never checked containment. Verified against
the running container **before** the fix:

```
/usr/local/lib/python3.11/this.py  -> ALLOWED
/etc/passwd                        -> refused, but only for lacking an allowed suffix
```

Any authenticated user could read any `.py`/`.js`/`.json`/`.yaml`/`.md` **anywhere on the host**,
and the contents went to an external LLM. Fixed with `resolve_project_root()` (CWD default,
`AINDY_ARM_PROJECT_ROOT` override) checked **before** the other guards; `.resolve()` handles
traversal and symlinks; containment is checked before existence so it is not an existence oracle.

**The duplicate went with it.** `deepseek/__init__.py` held a byte-identical `SecurityValidator`
importable as a *different class object* — the fix would have been bypassable by importing the
package instead of the module.

---

## 3. Two corrections I made to my own work

Recorded because both were wrong in ways that would have misled the next reader.

**The nodus flake (#195).** In #194 I added a CLAUDE.md note blaming a module-level `apps.*`
import in a test file for a `test_reasoning_nodus_apply` failure. That was inferred from two
consecutive failures plus a passing placeholder — correlation, not causation. It failed again
with no test file added, then passed on a re-run of identical code. The real cause was in the log:
`Nodus worker exceeded 45000ms hard limit`. `pytest.ini` now widens the budget the way
`docker-compose.prod.yml` already does, and three consecutive full-suite runs are clean.

**The watcher.** I wrote that `watcher_signals` was "built for a desktop activity watcher that
never shipped" — inferred from 0 rows, on a stack whose test data I had cleared earlier in the
same session. It shipped: `aindy-sdk/aindy_sdk/watcher/` is a real client (classifier, session
state machine, batched non-blocking emitter), `POST /watcher/signals` is **contract-stable** with
a cross-repo compatibility test, and `infinity_service` already computes `focus_quality` from it.

**Both share a shape:** reasoning about history from current state. An empty table says nothing
about whether something was built.

---

## 4. Four design decisions, settled (#198)

The walk left items 10, 17, 19 and 23 as "owner's decision". They were one question asked four
times, and the build docs already answered it:

> *"You didn't build an MVP. You built a platform container. Everything else becomes a tab."*

Everything sorts into **two faces**: the agent that plans and executes with you, and the trust
layer that shows what the work amounts to. ARM, Nodus, the runtime and the registry are
*mechanisms*, not faces — exposing them as product surfaces is the recurring mistake.

| Item | Resolution |
|---|---|
| **17** — four disconnected surfaces | One face, mode-switched. `Assistant.jsx` already called itself "the user-facing face for the agent" and already had an `agent \| plan` mode bar. |
| **19** — what is ARM for | An organ, not a surface. Already registered as agent tools feeding Infinity; six product routes against 0 rows in four of five tables. |
| **23** — Identity | Two products sharing a word. Operating parameters → the agent face; semantic footprint → the trust layer, fed by RippleTrace. |
| **10** — the Trust Feed | Social is a mode, not a product. Target shape is the Creator Dashboard, not posts-and-likes. `TrustTier` and `engagement_score` already exist unsurfaced. |

**Also settled: "what is an agent?"** — open since the registry discussion. *Your agent* is the
face; *the registry* is the substrate. And the face is now named **Collaborator** (#199), from the
plan's own subtitle. SYLVA was rejected on evidence: it is a live system-agent namespace with a
specific role in the ARM blueprint.

---

## 5. The social cold-start question, answered by dissolving it

*How do you run a trust network with no users?* The valuable half is **single-player** — Creator
Dashboard, Content Hub, Framework Forge all concern your own output, and the network they measure
against is the outside world via RippleTrace, not a local user table.

Tiering: **n=1** (dashboard) → **n=1 + world** (external echo) → **n>1** (trust between users).
Only the last needs population, and it may never be needed:

> The formulas are the digital representation of you. External signals are inputs.

That turns Moltbook (third-party, `github.com/moltbook/moltbook-web-client-application`) from a
template into a *signal source*, and reframes attestation — a computed standing is a **mirror**,
not a credential, so no third party has to believe it.

Which produced the sharper question: not *who trusts you*, but **how much do you trust yourself**
— specced in #201.

---

## 6. Three new specs

- **#193 + #197 — Domain Engine.** `Goal`/`GoalState` already *are* the designed `Domain`
  abstraction, mis-parented to `user_id` with no `masterplan_id` (grep count: 0) and 0 rows.
  Phase 5 adds emergent domain detection, evidenced by counting the owner's four real MasterPlan
  versions: **Nodus and the runtime appear 5 times in ~150k characters of planning** — the
  highest-leverage work is the least-planned.
- **#200 — Terminal agent.** Don't give A.I.N.D.Y. a filesystem; give a client that already has
  one access to A.I.N.D.Y. The runtime already ships an `mcp-server` subcommand with stdio/SSE,
  read-only default and an allowlist override. Gap is three things: the `[mcp]` extra, an
  allowlist, config. Also concludes **don't build a coding agent** — be what coding agents connect
  to.
- **#201 — Self-trust.** Calibration, in two flavours: declaration (integrity) and model
  (legibility), with the **divergence** as the signal — Breakout, Anomaly, Steady, Known
  over-commit. Model side is rich (194 scored predictions, 16 users); declaration side has **0
  pairs** but both writers exist, so it is a usage gap.
- **#202 — Cognitive operations.** The system already names operations and infers them:
  `loop_adjustments` holds **210 decisions** across four `decision_type`s. The vocabulary is four
  verbs; the machinery for two-thirds of the rest already exists unnamed. **Inferred, not
  selected** — do not build a mode picker.

---

## 7. The recurring pattern — and it is the main finding

Almost nothing this session was construction. Each of these was built to a written design and
stopped one wire short of a surface:

| Built | Missing |
|---|---|
| `mcp-server` (stdio + SSE + allowlist) | the `[mcp]` extra and an app allowlist |
| Watcher → `focus_quality` → Infinity | nothing emits signals here |
| `TrustTier`, `engagement_score` | nothing renders them |
| `suggest_tools_for_kpi` | consumed only by the operator console |
| `agents` + `memory_namespace` + capability mappings | no registration API |
| 210 recorded decisions, per-type expectation models | no surface names them |
| `critical_path`, `topological_order` | unreachable by name |

**Reading the original build docs before writing code was the highest-yield move every time**, and
twice it corrected a wrong inference. The specs were right; the surface layer stopped early.

---

## 8. Open — runtime

Filed this session; next id **FR-14**.

- **FR-11** 🟢 — `invoke_runtime_callback`'s hardcoded 10s budget. *Mechanism corrected by the
  runtime team:* it is a cold subprocess import, **not** a 16-app bootstrap.
- **FR-12** 🔴 — no way to register an agent; the roster is a hardcoded seven in `startup.py`.
  Confirmed by the runtime team: 7 rows, all `agent_type='system'`, `count(owner_user_id)=0`.
- **FR-13** 🟡 — `agents` has no JSONB and no `updated_at`, so identity cannot outlive the vendor.
- **FR-7** ✅ — closed. All four memory fixes shipped in 2.0.0; only our doc was stale. **Per-domain
  memory policy work is unblocked.**

---

## 9. Environment

- `aindy-runtime==2.0.1`, api healthy, both email flows verified end to end via Mailpit.
- **Mailpit is profile-gated** — `docker compose -f docker-compose.prod.yml --profile mail up -d`,
  inbox at `:8025`. It is a sink; never start it against a real deployment.
- **The container is hot-patched ahead of its image.** The ARM fix (#194) and the email-connector
  fix (#190) are `docker cp`'d, not baked. Protected now, lost on a recreate. **A rebuild is the
  one outstanding operational task** — no PR or CI needed, just bandwidth (~30 kB/s here, and
  `--no-cache` is required or the cached pip layer silently keeps the old runtime).
- 12 pre-existing users grandfathered to verified during the 2.0.0 upgrade; the reconcile does
  **not** do this on a wheel install (FR-8).

---

## 10. Where to pick up

Ordered by leverage. All scoped against verified code.

1. **Domain Engine phases 1–2** (#193) — plan physics become the user's own. Everything
   measurement-related waits on this.
2. **Cognitive operations phase 1** (#202) — surface what `reasoning.evaluate` and
   `suggest_tools_for_kpi` already choose. Wiring only, no new operations.
3. **Terminal agent phases 1–2** (#200) — `[mcp]` extra + tier-1 read-only allowlist. A day.
4. **Complete the Collaborator face** (#198) — fold Tasks and MasterPlan in as modes.
5. **Retire the six ARM product routes** (#198) — purely subtractive.
6. **Self-trust phase 1** (#201) — aggregate the 194 existing predictions.

Owner decisions still open: the five Identity sub-decisions, whether social tier 3 is deferred or
deleted, and how many cognitive-operation verbs before the vocabulary is noise.

---

## 11. One honest note

Two claims in this session were wrong and both had the same cause: inferring history from present
state. "The watcher never shipped" and "the module-level import broke the nodus test" were each
plausible, each written down, and each false. The corrections are in §3 and in the docs
themselves, struck through rather than quietly rewritten.

The lesson that actually generalises is the one in §7: **when something looks unbuilt here, check
the build docs and the sibling repos before concluding it.** This codebase's dominant shape is a
working engine behind a missing surface, and an empty table is not evidence of an absent feature.
