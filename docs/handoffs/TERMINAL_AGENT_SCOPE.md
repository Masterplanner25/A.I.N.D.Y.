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
- **Audit already exists.** Syscalls dispatch through the same pipeline as everything else, so
  terminal-originated calls land in execution records like any other.

---

## 7. This is also the Nodus coding agent

Decided 2026-08-06: **one piece of work, not two.**

A terminal client with filesystem access, shell access and A.I.N.D.Y.'s capability surface *is*
a coding agent when pointed at a repository. Nodus is the execution substrate and the natural
home, and ARM's tools (`arm.analyze`, `arm.generate`, `arm.autotune`) become its hands rather
than a separate product surface — which is also what §2 of `SURFACE_IDENTITY_BRIEF.md` concluded
for independent reasons.

The corollary: **ARM's six product routes can retire without losing the capability**, because
the terminal is where code analysis actually wants to happen.

---

## 8. What this does not do

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

## 9. Phases

1. **Dependency + smoke.** Add the `[mcp]` extra; run `aindy-runtime mcp-server --transport
   stdio` against the local stack; confirm the nine default tools appear in a real MCP client.
2. **Tier 1 allowlist.** Derive read-only app syscalls from capability; set
   `AINDY_MCP_SERVER_TOOLS`; document in `.env.example` and compose. Ship here.
3. **Tier 2–3, deliberately.** Add authoring, then acting, one capability at a time with a reason
   recorded for each.
4. **Nodus coding agent.** Point it at a repository, with ARM's tools as its hands.

Phase 1–2 are a day's work and carry no state-changing risk. Phases 3–4 are where the design
questions below have to be answered.

---

## 10. Open questions

- **Syscalls or agent tools?** MCP exposes syscalls. The 16 agent tools are curated, carry risk
  levels, and drive the approval gate. A terminal client seeing raw syscalls bypasses that
  curation. Options: expose syscalls and accept it, expose a tool-shaped facade, or register the
  agent tools as MCP tools separately.
- **Where does approval live for terminal-initiated work?** Today the human gate is in the agent
  run path. An MCP call has no equivalent. Tier 1 sidesteps this; tier 3 cannot.
- **Does terminal work feed the loop?** If the agent completes tasks from a shell, that effort
  should reach Infinity, the MasterPlan's WCU and emergent domain detection
  (`MASTERPLAN_DOMAIN_ENGINE_SPEC.md` §5a) — otherwise the most productive surface is the one the
  system cannot see, which is the exact blind spot §5a exists to close.
- **One identity or many?** stdio pins a single user. Fine for the owner's machine; not a product.
