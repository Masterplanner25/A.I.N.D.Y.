---
title: "Terminal Agent — working with the Collaborator from a shell"
last_verified: "2026-08-06"
api_version: "1.0"
status: current
owner: "app-team"
---

# Terminal Agent — working with the Collaborator from a shell

**Status:** scope, not started. Written 2026-08-06.

Raised as *"we'll need CLI/filesystem access for the agent — the person's actual files"*, then
sharpened to the thing that actually matters: **being able to work with the agent from the
terminal.** That second framing is a different and much smaller problem, and most of it is
already built.

---

## 1. The reframe — don't give A.I.N.D.Y. a filesystem

The first framing was *give the agent access to the user's files*. Under that reading,
deployment shape decides everything: a hosted multi-tenant app cannot read a local disk, so you
are choosing between upload, a sync client, or a local runner — all expensive, all with their
own security surface.

The second framing inverts it:

> **Don't give A.I.N.D.Y. a filesystem. Give a client that already has one access to A.I.N.D.Y.**

An MCP client (Claude Code, Claude Desktop, Codex) already runs on the user's machine with real
file and shell access. What it lacks is *durable context* — a plan, a memory graph, a scoring
history, an execution record. A.I.N.D.Y. has exactly those and lacks the filesystem.

Neither side needs to grow the other's capability. They need to be connected.

**This is not analogy.** The session that produced this document ran in the owner's terminal with
full access to the repository, while A.I.N.D.Y.'s MasterPlan, memory and tools sat behind an API
the session could not see. Wiring the two is the whole feature.

---

## 2. What already exists — audited 2026-08-06

`aindy-runtime` ships an **MCP server subcommand**. From its own help text:

> *"Expose an allowlist of AINDY syscalls as MCP tools, as a standalone process an MCP client
> spawns (stdio) or connects to (SSE). Over stdio, every call runs as the single configured
> identity `AINDY_MCP_SERVER_USER_ID`. Over SSE with `AINDY_MCP_SERVER_MULTI_TENANT=true`, each
> session's `Authorization: Bearer` / `X-Platform-Key` header resolves to a real user and calls
> dispatch as that identity (MEB-3a). Read-only tools by default."*

So the transport, the identity model, the multi-tenant story and the safety default are all
already decided and implemented — `AINDY/platform_layer/mcp_server.py`.

| Piece | State |
|---|---|
| stdio transport (local operator) | ✅ built |
| SSE transport + per-session Bearer identity | ✅ built (MEB-3a) |
| Read-only by default | ✅ built |
| `AINDY_MCP_SERVER_ALLOW_WRITES` opt-in | ✅ built |
| `AINDY_MCP_SERVER_TOOLS` allowlist override | ✅ built |

**The surface it can expose is large.** Measured on the running stack: **89 registered syscalls,
77 of them app-owned** — tasks, masterplan, leadgen, search, social, rippletrace, identity,
genesis, analytics, arm, freelance, agent.

---

## 3. What is missing — and it is small

1. **The `[mcp]` extra is not installed.** `import mcp` → `ModuleNotFoundError` in the app image.
   One dependency (`aindy-runtime[mcp]`).
2. **The default allowlist is runtime-only.** Nine entries: `memory.read/search/list/tree/trace`
   read-side, plus `memory.write`, `memory.delete`, `flow.run`, `event.emit` behind the writes
   flag. **None of the 77 app syscalls are exposed.** That is correct as a default and wrong as
   an end state.
3. **No app-side configuration.** No compose entry, no documented allowlist, nothing in
   `.env.example`.

That is the entire gap: a dependency, an allowlist, and the config to carry it.

---

## 4. The real design work — choosing the allowlist

Every `SyscallEntry` carries a `capability`, and the naming is consistent
(`<domain>.read`, `<domain>.write`, plus explicit verbs like `leadgen.act`, `task.complete`,
`masterplan.cascade_activate`, `nodus.execute`, `job.submit`). So the allowlist can be
**derived from capability**, not hand-maintained — which matters, because a hand-written list of
77 entries goes stale the first time a domain adds a syscall.

Proposed tiers:

| Tier | Rule | Contains | Default |
|---|---|---|---|
| **1 — Context** | capability ends `.read`, or is `*.query` | masterplan/task/memory/social/rippletrace/identity/search reads | **on** |
| **2 — Authoring** | `task.create`, `task.write`, `memory.write`, `score.feedback`, `search.feedback` | the agent can record work and give feedback | opt-in |
| **3 — Acting** | `task.complete/start/pause`, `leadgen.act`, `arm.*`, `freelance.optimize_pricing` | changes state or drafts outbound | explicit, per-capability |
| **4 — Never by default** | `flow.run`, `agent.execute`, `nodus.execute`, `job.submit`, `memory.delete`, `task.delete_by_ids`, `masterplan.cascade_activate` | arbitrary execution or destruction | off |

**`flow.run` deserves naming.** It is in the runtime's *default write* set, and it can run any
registered app flow — so flipping `AINDY_MCP_SERVER_ALLOW_WRITES=true` grants far more than
"writes". Set `AINDY_MCP_SERVER_TOOLS` explicitly rather than relying on the writes flag.

**Tier 1 alone is already worth shipping.** A terminal client that can read your MasterPlan, your
tasks, your memory graph and your scores — while holding your actual files — is the product
thesis working, with no state-changing risk at all.

### 4a. Scope the allowlist to an *agent*, not to a connection

A flat `AINDY_MCP_SERVER_TOOLS` answers "what may any MCP client call". The better question is
"what may **this agent** call" — and the platform already models agents.

Audited 2026-08-06:

| Piece | State |
|---|---|
| `agents` table — `id` (varchar), `owner_user_id`, `memory_namespace`, `agent_type`, `is_active` | ✅ exists |
| Seven live agents, each with its own memory namespace (arm, genesis, nodus, sylva, platform, runtime, memory) | ✅ running |
| `agent_capability_mappings` — capabilities bound to an `agent_type` or an `agent_run_id` | ✅ 15 rows |

So agent-scoped memory and per-agent-type capability scoping are not concepts to invent.

**The durable identity should be the role, not the vendor.** Register
`development.main-runtime` (type `terminal`), and treat the client as swappable metadata —
`provider: codex` today, `provider: claude_code` tomorrow. The agent keeps its id, its memory
namespace and its history across the switch. The intelligence implementation is replaceable;
the platform identity persists — which is the substrate thesis applied to identity.

```
Claude Code / Codex / other client
        ↓  authenticates as
agent: development.main-runtime   (type=terminal, provider=codex, workspace=aindy-runtime)
        ↓
agent-scoped memory namespace · capability mapping · events · approvals
        ↓
MCP syscalls · watcher signals · task completions
```

**What this buys beyond a flat allowlist:**

- **Attribution.** Commits, completions, watcher sessions, memory writes and syscall calls all
  belong to a real platform actor rather than to "some MCP client" — which is exactly what
  emergent domain detection (`MASTERPLAN_DOMAIN_ENGINE_SPEC.md` §5a) needs to attribute effort.
- **Memory hygiene.** Repo context lands in the terminal agent's namespace instead of polluting
  the Collaborator's working memory, and the existing federated model decides what is private,
  shared, or promoted.
- **Delegation becomes possible.** The Collaborator delegates a scoped goal to
  `development.main-runtime`; you open whichever client; it authenticates as that agent,
  inherits the namespace and the goal, works locally, reports back. Every step maps onto
  something that already exists.

**Caution — capabilities bind to `agent_type`, not to agent id.** So all agents of type
`terminal` share one capability set. That is probably right (policy per class, not per
instance), but it means `development.main-runtime` and `development.client-work` cannot differ
without differing types. Decide deliberately rather than discovering it later.

**Two gaps, both runtime-owned** — filed as FR-12 and FR-13 in
`RUNTIME_FEATURE_REQUESTS.md`: there is no agent *registration* surface (the seven are a
hardcoded list in the runtime's `startup.py`), and `agents` has no metadata field for
provider/workspace/branch. Until those land, the flat allowlist in §4 is the shipping path and
this section is the target.

**Also worth noting:** `AGENT_USER = "user"` exists as a constant but has no `agents` row, so
the Collaborator itself is not a registered agent either. Registering both makes the model
symmetric instead of special-casing the terminal.

---

## 5. Deployment — local now, hosted later, both already supported

- **Now (local stack):** `--transport stdio`, spawned by the MCP client, pinned to one identity
  via `AINDY_MCP_SERVER_USER_ID`. No network exposure; the client is the only caller.
- **Later (hosted):** `--transport sse` with `AINDY_MCP_SERVER_MULTI_TENANT=true`, each session's
  Bearer resolving to a real user. Same allowlist, per-user dispatch.

The choice does **not** have to be made now, which is what makes this cheap — stdio is a config
file on one machine, and the SSE path is already implemented for when there are users.

---

## 6. Security posture

This is the first capability that lets an outside process act as a user against their own data,
so the posture should be stated rather than inherited:

- **The allowlist is the gate.** Not the client, not the prompt. Everything else is defence in
  depth.
- **Read-only stays the default.** Tier 1 ships first and alone.
- **Consistent with #194.** That PR replaced "guess whether this path is sensitive" with "prove
  it is inside the boundary". The allowlist is the same move: enumerate what is permitted rather
  than filter what is not.
- **The filesystem risk moves to the client, where it belongs.** A.I.N.D.Y. gains no file access,
  so #194's confinement is untouched. The user's files are reached by a process they already run
  and already trust with them.
- **Identity is real, not asserted.** stdio pins one configured user; SSE resolves a token. There
  is no "trust the caller's claimed user_id" path.
- **Identity-scoped beats connection-scoped.** The end state (§4a) is not "an MCP client
  connected, therefore 77 syscalls" but "this is agent `development.main-runtime`, type
  `terminal`, and its capability mapping says these". That is the same move as #194 one layer
  up: authorise the actor, not the channel. The flat allowlist is the interim.
- **Audit already exists.** Syscalls dispatch through the same pipeline as everything else, so
  terminal-originated calls land in execution records like any other.

---

## 7. Do not build a coding agent — be what coding agents connect to

**Revised 2026-08-06.** An earlier draft of this section said the terminal agent *is* the Nodus
coding agent, and that they are one piece of work. That was the right instinct applied one step
too short. The better answer is not to build one at all.

The principle is the one already applied twice in this codebase — ARM is an organ rather than a
surface, and A.I.N.D.Y. gets no filesystem — stated generally:

> **Do not own a layer merely because you can build it.**

Mature coding agents exist and are improving fast. The differentiated asset is not the
intelligence operating the terminal; it is **what that intelligence can be given access to**.
So instead of

```
A.I.N.D.Y.  ->  builds a Nodus coding agent  ->  competes with Codex / Claude Code
```

the shape is

```
Claude Code ─┐
Codex ───────┤
             ├──  MCP  ──>  A.I.N.D.Y.   (MasterPlan · Infinity · memory ·
other agent ─┤                            workflows · RippleTrace · governance)
your agent ──┘
```

**Nodus does not need to be an agent — it is a language.** Existing coding agents already learn
unfamiliar languages, CLIs, conventions and test procedures from a repository. So ship what they
learn *from*: the language, the CLI, docs, examples, the MCP tools and the runtime execution
contract. Everything learned building Nodus becomes context and tooling for coding agents rather
than another coding-agent implementation.

**Why this is strategically better, not just cheaper:** you stop betting that your agent beats
Codex. Anthropic improves Claude Code and A.I.N.D.Y. gets better; OpenAI improves Codex and
A.I.N.D.Y. gets better; an open-source agent leapfrogs both and A.I.N.D.Y. gets better. You end
up **downstream of intelligence commoditization instead of competing with it** — which is where a
substrate wants to be.

### What is still worth owning

- **The Collaborator** (`SURFACE_IDENTITY_BRIEF.md` §1) stays. It is the native face for working
  with the *system* — planning, reasoning over the MasterPlan, deciding what to do. And it has
  something external agents structurally will not: 16 curated tools carrying risk levels and a
  human approval gate. External agents get syscalls; the Collaborator gets judgment.
- **The bridge itself.** The commercial boundary is not "access to Nodus" — it is *your execution
  environment follows you into the terminal*, maintained as the ecosystem moves: MCP/auth changes
  in Codex, behaviour changes in Claude Code, syscall-contract evolution, new Collaborator
  capabilities, permissions found to be too broad. That is ongoing product work with real
  operational cost, which is a legitimate thing to charge for. The open pieces stay open; anyone
  sufficiently technical can wire their own.
- **A "Nodus mode" preset** — enabling it in Codex/Claude Code supplies the Nodus language, docs,
  CLI, examples and the A.I.N.D.Y. MCP allowlist in one step. That is configuration and
  curation, not a new agent.

**The cost this creates, stated plainly:** selling a maintained bridge means selling **contract
stability**. `SyscallEntry` already carries `stable`, `deprecated`, `deprecated_since` and
`replacement`, so the machinery exists — but syscalls have so far been added and changed freely
because nothing external consumed them. The moment external agents bind to them, that freedom
ends. The commercial promise *is* the constraint.

---

## 8. Observability — how A.I.N.D.Y. knows what the coding agent did

**This is the prerequisite for the commercial story, not a nice-to-have.** "Your execution
environment follows you into the terminal" is only half true if context flows *out* and results
never flow *back*. If an external agent does the most valuable work of the week and A.I.N.D.Y.
cannot see it, the most productive surface becomes the one the system is blind to — the exact
blind spot `MASTERPLAN_DOMAIN_ENGINE_SPEC.md` §5a exists to close — and the differentiator
quietly inverts.

Audited 2026-08-06, and **three channels already exist**. Two of them close the loop today.

**1. Syscalls self-report.** Anything the agent does *through* A.I.N.D.Y. dispatches on the
normal pipeline, so it lands in execution records like any other call. `sys.v1.task.complete`
over MCP is a real completion: it recalculates the plan's ETA and WCU and cascade-activates,
identically to a click in the web UI. **No work needed.**

**2. The Watcher — a shipped, contract-stable activity pipeline.** This is the important one,
and it is more complete than a syscall.

| Layer | Where | State |
|---|---|---|
| Client | **`aindy-sdk`** — `aindy_sdk/watcher/` (`watcher.py`, `classifier.py`, `session_tracker.py`, `signal_emitter.py`, `config.py`) | ✅ shipped |
| Transport | `POST /watcher/signals`, `GET /watcher/signals`, API-key auth | ✅ shipped, **contract-stable** |
| Storage | `watcher_signals` — `app_name`, `window_title`, `activity_type`, `session_id`, `duration_seconds`, `focus_score`, `signal_metadata` | ✅ |
| Scoring | `infinity_service` computes **`focus_quality`** from `session_ended` / `distraction_detected` / `focus_achieved` | ✅ wired |

The runtime's own `CROSS_REPO_COMPATIBILITY.md` lists both endpoints as **stable** with a
compatibility test (`test_watcher_endpoint_registered`), naming `aindy-sdk`'s watcher client as
the consumer. So this is not a loose end — it is a maintained cross-repo contract.

The client is a real activity tracker: a `classifier` mapping `(app_name, window_title)` →
activity type, a `session_tracker` state machine (`IDLE → WORKING → DISTRACTED`), and a
`signal_emitter` that batches over a background thread and never blocks its caller.

**What this means for the terminal agent: the reporting convention does not need inventing.**
A terminal client emits the same six signal types over the same stable endpoint, and
`focus_quality` receives it. Better still, `aindy_sdk.watcher.signal_emitter` is a
non-blocking batched emitter that can be reused directly rather than reimplemented.

`watcher_signals` currently has **0 rows on this deployment**, which says the watcher is not
running against this stack right now — not that the capability is missing. (Test data was
cleared earlier in this stack's life, so the count is not evidence either way.)

**3. `sys.v1.event.emit`** is already in the runtime's default MCP write set, so an external
agent can raise domain events into A.I.N.D.Y. directly.

### What is genuinely missing

- **Attribution.** §5a needs effort mapped to a domain, or explicitly mapped to none. Watcher
  `signal_metadata` is the natural carrier (repo, branch, files touched), but nothing populates
  or reads it that way yet.
- **Artifact ingestion.** Commits, PRs and releases are proof-of-work the agent produces but does
  not report. RippleTrace already ingests *external* artifacts for published content — the same
  shape applied to work artifacts is the obvious reuse, not a new subsystem.
- **A reporting convention.** The *contract* exists (six signal types, stable endpoint, a
  reusable emitter); what is undecided is whether the agent is *asked* to report
  (prompt/preset) or *required* to (a wrapper emitting `session_started`/`session_ended` around
  the session). The second is reliable; the first is honest about what an external agent will
  actually do. `context_switch` and `heartbeat` already exist as types and map cleanly onto
  repo/branch changes and long-running sessions.

**Sequencing note:** channel 1 is free, channel 2 is a signal emission, and both should exist
before tier 3 of the allowlist. Otherwise the agent gains the ability to change state before the
system gains the ability to see it.

---

## 9. What this does not do

- Does not build a bespoke A.I.N.D.Y. CLI. MCP clients already exist; building a competing one is
  work with no payoff until the protocol is insufficient.
- Does not give the hosted app filesystem access. That remains out of scope, deliberately.
- Does not expose the 16 **agent tools**. MCP exposes *syscalls* — the lower, schema'd layer. The
  agent tool list is a curated layer above it, and whether the terminal should see tools or
  syscalls is an open question (§10).
- Does not change the approval gate. Risk levels and human approval live in the agent run path;
  a syscall called over MCP does not pass through it. This is a real difference and §10 records
  it.

---

## 10. Phases

1. **Dependency + smoke.** Add the `[mcp]` extra; run `aindy-runtime mcp-server --transport
   stdio` against the local stack; confirm the nine default tools appear in a real MCP client.
2. **Tier 1 allowlist.** Derive read-only app syscalls from capability; set
   `AINDY_MCP_SERVER_TOOLS`; document in `.env.example` and compose. Ship here.
3. **Tier 2–3, deliberately.** Add authoring, then acting, one capability at a time with a reason
   recorded for each.
4. **Report back.** Reuse `aindy_sdk.watcher.signal_emitter` to emit `session_started` /
   `session_ended` (and `context_switch` on repo change) from the terminal client, so
   `focus_quality` receives real signals; decide the attribution convention (§8).
5. **"Nodus mode" preset.** Language, CLI, docs, examples and the allowlist bundled so an
   existing coding agent can be pointed at a repository in one step.

Phases 1–2 are a day's work and carry no state-changing risk. **Phase 4 should not trail phase
3** — see §8: the agent should not gain the ability to change state before the system gains the
ability to see it. Phase 5 is packaging.

---

## 11. Open questions

- **Syscalls or agent tools?** MCP exposes syscalls. The 16 agent tools are curated, carry risk
  levels, and drive the approval gate. A terminal client seeing raw syscalls bypasses that
  curation. Options: expose syscalls and accept it, expose a tool-shaped facade, or register the
  agent tools as MCP tools separately.
- **Where does approval live for terminal-initiated work?** Today the human gate is in the agent
  run path. An MCP call has no equivalent. Tier 1 sidesteps this; tier 3 cannot.
- **One identity or many?** stdio pins a single user. Fine for the owner's machine; not a product.
