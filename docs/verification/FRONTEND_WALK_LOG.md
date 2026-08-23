---
title: "Frontend Walk Log — live user-path walkthrough"
last_verified: "2026-08-05"
api_version: "1.0"
status: current
owner: "app-team"
---

# Frontend Walk Log

Running record of the live frontend walkthrough — clicking the app as a real user, on the
real stack, and writing down what a user would actually experience.

This is deliberately broader than a bug list. It captures three kinds of finding:

- **Defect** — something is broken and should be fixed.
- **Design** — the app behaves as built, but the behavior is worth a decision.
- **Papercut** — small friction that isn't wrong, just costs the user something.

**Every entry must also carry an Owner** — `app`, `runtime`, `both`, `undecided`, or `env`.

This field was added 2026-08-22, retroactively, after an audit asked why a phase whose stated
purpose was *proving the runtime* produced almost entirely app-side fixes. The answer was that
ownership was never asked as a question: findings arrive wearing app clothes because the walk is
driven from the UI, and the cheapest fix is always the one in front of you. The dominant defect
class of the whole phase — response-shape mismatch, five defects and ~40 `safeMap` crashes — was
fixed eleven times in client code and raised with the runtime zero times, until it became
**FR-19**.

`undecided` is a real, legitimate state and must not be left blank instead. Item 28 sat undecided
for a month precisely because nobody wrote the word down: it explicitly poses the runtime-or-app
question and was never answered. A blank reads as "app" by default, which is the bias this column
exists to break.

Entries stay here until they are fixed, filed upstream, or explicitly declined.

**Environment:** `aindy-runtime==1.10.2` · native `docker.io` in WSL2 Ubuntu · pgvector/pg16 ·
client on Vite dev server at `localhost:5173` proxying to the API at `localhost:8000`.

---

## Open

| # | Kind | Owner | Area | Item | Status |
|---|---|---|---|---|---|
| 1 | Design | app | Genesis | AI interrogates but never contributes ideas | decision needed |
| 2 | Papercut | app | Genesis chat | Enter inserts a newline instead of sending | ready to fix |
| 3 | Defect | both | masterplan / memory | A 404 surfaces to the user as "Internal Server Error" | diagnosed, unfixed |
| 4 | Defect | app | network | `InfiniteNetwork` calls `/api/users`, which no route serves; also no member-list endpoint exists and signup never provisions a social profile | confirmed live; 4 consolidation options logged, decision deferred |
| 5 | Defect | app | Genesis | Leaving the page abandons the session; transcript is never stored | diagnosed, decision needed |
| 6 | Gap | runtime | auth | No password recovery — a forgotten password locks the account out permanently | runtime feature request |
| 7 | Defect | app | search / research | Research web-search provider (Perplexity) is an unwired stub — no key sent, wrong endpoint | decided: wire Perplexity (opt 1), not built |
| 8 | Design | app | auth / client | A 401 on ANY request logs the whole session out — a stray widget 401 bounces the user to sign-in | decision needed |
| 9 | Question | app | search / SEO | Who saves an SEO analysis? (answered: the system, automatically) | answered |
| 10 | Design | app | social | The social feed reads very bare on first look — presentation, and "social feed" vs "trust feed" identity | design note |
| 11 | Defect | app | social | Posts don't appear after posting — Mongo not enabled + a 500 on the created post + a false-success degrade | fixed (needs Mongo) |
| 12 | Defect | app | social / client api | The feed renders nothing and analytics shows all zeros — `social.js` never unwrapped the execution envelope | fixed |
| 13 | Defect | both | client api (systemic) | `unwrapEnvelope` coverage is inconsistent across `client/src/api/` — 8 modules have none | diagnosed, watch while walking |
| 14 | Defect | app | tasks | Created tasks never appear — `/apps/tasks/list` nests the array one level deeper than the unwrap handles | fixed |
| 15 | Question | app | tasks | Is a task tracked, or executed by the AI? (answered: tracked; AI execution is opt-in and has no UI) | answered, decision needed |
| 16 | Defect | app | masterplan | The only non-Genesis MasterPlan create route 500s — Genesis is the sole working way to get a plan | confirmed live, unfixed |
| 17 | Design | app | masterplan / genesis / tasks | The three surfaces were one section and are now disconnected tabs; no UI links a task to a plan. Includes an import-an-external-plan proposal | design decision |
| 18 | Design | app | analytics / kpi | Analytics is LinkedIn-specific and owner-specific; KPI Snapshot is a manual-entry calculator that wants to be a dashboard | owner verdict: redesign or remove |
| 19 | Defect | app | arm | ARM Analyze reads files from the **server**, the prefilled default cannot exist, and a failed analysis renders a blank screen | fixed (client); default path decision open |
| 20 | Security | app | arm | ARM has no project-root confinement — any allowlisted-extension file anywhere on the server is readable and gets sent to an external LLM | hardening recommended |
| 21 | Analysis | app | arm (whole surface) | What the six ARM screens actually do — the reasoning engine is real, but its entire input corpus is code-analysis telemetry | analysis, decisions listed |
| 22 | Defect | app | identity | Every dimension card renders blank — `identity.js` never unwrapped the envelope | fixed |
| 23 | Analysis | app | identity / memory | What both surfaces actually do — Identity is an AI personalization model (naming mismatch confirmed); Memory is a runtime-owned engine with a thin app wrapper | analysis, decisions listed |
| 24 | Environment | env | dev stack | Two API instances answered `localhost:8000`; a stale `wslrelay` shadowed the container for hours | resolved |
| 25 | Defect | app | platform / dev proxy | The dev proxy swallowed **every** `/platform` API call — no platform panel could load data | fixed (#158) |
| 26 | Defect | app | platform / registry | Registry read `registry.flows`; the route returns `flow_definitions`. Its unit test encoded the bug | fixed (#159) |
| 27 | Defect | app | platform / strategies | `ScoreBar` calls `score.toFixed(2)` on a null score — both live strategies have `score: null` | fixed |
| 28 | Defect | undecided | client telemetry | `reportClientError` POSTs to `/client/error`, which no route serves — every boundary trip 404s silently | diagnosed, unfixed |
| 29 | Design | runtime | platform UI | The operator surface is a **record**, not a control plane — the API exposes 24 write routes, the UI wires 5 | design decision |
| 30 | Defect | runtime | platform UI | The platform SPA had **no navigation at all** — 8 registered routes, 7 reachable only by typing a URL | fixed |
| 31 | Defect | app | platform / agent console | `agent.js` never unwrapped `{data: […]}` — `runs.filter is not a function` blanked the console | fixed |
| 32 | Defect | runtime | platform / executions | The Executions tab is 13 app-domain Infinity calculators on the operator surface — it shows no executions, and strands 7 panels behind admin | diagnosed, decision needed |
| 33 | Defect | runtime | runtime / tracing | Every response carries **two** trace ids — the envelope's and the header's — resolving to different graphs, unlabelled | diagnosed, unfixed |
| 34 | Gap | runtime | platform / scheduler | Scheduler status reports health but lists **no jobs** — the 5 registered jobs can't be verified from the operator surface | diagnosed, unfixed |

---

### 1. Genesis asks, but never offers — `Design`

**Observed:** working through Genesis, the user has to think of everything. The AI prompts
and probes, but never proposes options or contributes ideas back.

**Why:** this is written into `GENESIS_SYSTEM_PROMPT`
(`apps/masterplan/services/genesis_ai.py`). Its only three behavioral rules are:

```
- Responses must be 2–4 lines maximum.
- Ask clarifying questions when mechanism logic is missing.
- Extract structured signals from user input.
```

Nothing authorizes proposing or suggesting. The 2–4 line cap is the binding constraint —
there is no room to offer options *and* ask a question, so even a model inclined to
contribute gets squeezed into asking.

**Structural shape:** contribution isn't missing, it's *back-loaded*. `SYNTHESIS_SYSTEM_PROMPT`
does all the generating (phases, success criteria, risk factors, ambition score). The design is
**conversation = extraction, synthesis = generation**. The felt problem is that all generative
value sits behind a wall the user only reaches at the end.

**The part that looks unintentional:** before every turn `call_genesis_llm` recalls prior
strategic memories via `MemoryOrchestrator`, plus ARM and identity context, and injects it all
into the system prompt — but the prompt never tells the model to *use* that context to
contribute. Retrieval is paid for, and its only sanctioned use is asking a better question.
That is where the plumbing and the prompt disagree.

**Tradeoff (why this isn't an obvious fix):**

- *Keep extractive:* if the AI proposes a mechanism, users anchor on it, and a plan you were
  led to isn't one you own. Worse, mid-conversation suggestions would contaminate
  `state_update` — the model would extract signals it authored as though the user said them,
  inflating `confidence` on its own ideas. Synthesis is currently the only place inference is
  labelled as inference (`synthesis_notes`).
- *Add contribution:* Genesis is one-time, high-stakes onboarding. A user who doesn't know
  what's possible can't answer "what's your mechanism?", and if they stall there they never
  reach synthesis at all.

**Proposed middle path (if changed):** contribute only when the user is stuck, and don't
launder it as theirs — offer 2–3 options when `confidence` hasn't moved across turns, mark them
as the AI's, and don't write suggested content into `state_update` unless the user affirms it.
Preserves ownership and provenance. Cost: a prompt change plus a small state-update guard.

**Status:** design decision for the owner. Not scheduled.

---

### 2. Enter doesn't send in the Genesis chat — `Papercut`

**Observed:** pressing Enter in the chat box drops to a new line instead of sending. Sending
requires clicking SEND.

**Why:** `client/src/components/app/Genesis.jsx` renders a bare `<textarea>` with **no
`onKeyDown` handler** (~line 225). Enter therefore does its native newline, and the form only
submits via the SEND button. Not a bug — nothing is broken — but it breaks the chat convention
users arrive with.

**Fix:** `Enter` submits, `Shift+Enter` newlines — the standard for chat inputs. Guard on
`loading` so Enter can't double-submit mid-request, and keep the multi-line affordance since
Genesis answers are often long.

**Status:** ready to fix, small and self-contained.

---

### 3. A 404 surfaces as "Internal Server Error" — `Defect`

**Observed:** hitting a stale/absent masterplan or memory-trace link returns a 500 rather than
a not-found.

**Why:** app routes that raise `HTTPException` *before* entering the execution pipeline have
their status replaced. The runtime's `route_execution_guard` catches every exception —
including `fastapi.HTTPException`, which is legitimate control flow — and converts it into a
`RouteExecutionViolation` (500) when no execution context was entered. The runtime's own log
names the condition: `endpoint raised HTTPException before pipeline entry`.

The runtime is enforcing its ExecutionContract correctly; the violation is app-side. Within
`masterplan_router.py` the patterns are inconsistent — `lock_from_genesis` uses the pipeline,
while `get_masterplan` calls `_run_flow_masterplan` → `run_flow()` directly and never enters it.

**Confirmed affected:** `/apps/masterplans/{plan_id}`, `/apps/memory/traces/{trace_id}`.
Contrast (correct, inside the pipeline): `/apps/agent/runs/{id}` → 400,
`/apps/freelance/metrics/latest` → 404.

Three further routes 500 on malformed UUIDs rather than 422:
`/apps/rippletrace/event/{id}/upstream`, `.../downstream`,
`/apps/coordination/runs/{id}/children`.

**Note:** file-level static analysis cannot enumerate these — every file that raises
`HTTPException` *also* contains pipeline usage, so the violation is per-route. The empirical
sweep is the reliable detector.

**Status:** diagnosed, unfixed. Cosmetic for the happy path; misleading when hit.

---

### 4. `InfiniteNetwork` calls a route that doesn't exist — `Defect`

**Observed:** `/network` surface fails to load users.

**Why:** `client/src/components/app/InfiniteNetwork.jsx` falls back to `"/api/users"` when
`VITE_NETWORK_API_URL` is unset. No backend route serves `/api/users` — the only user-listing
route is `/platform/admin/users`, which is admin-gated. This is independent of the dev-proxy
prefix handling; it 404s either way.

**Status:** diagnosed, unfixed. Needs a decision: point at a real route, gate the surface, or
require the env var.

**Update (2026-07-22 walk) — confirmed live, and it's broader than a wrong URL.**

Verified against the running stack: `GET /api/users` → **404**, `POST /api/users` → **404**,
and nothing resembling it exists in the OpenAPI schema. Both halves of the page (list members,
create profile) are wired to a route that has never existed on this backend — the component is
a leftover from a standalone prototype and was never connected.

Two further findings that constrain the fix:

1. **There is no member-listing endpoint at all.** Social exposes only
   `POST /apps/social/profile` and `GET /apps/social/profile/{username}`. A "Network Members"
   list has nothing to call; it would need a new `GET /apps/social/profiles` route.
2. **`network_bridge` is not a drop-in target.** `GET /apps/network_bridge/authors` returns
   **401 with a valid bearer token** — it is API-key gated. Pointing the page at it would
   reproduce the RippleTrace logout bug (#145), where an api-key-gated call 401s and the
   global 401 handler signs the user out (open item 8).

**Related gap — profile provisioning was never moved to signup.** The owner recalled asking for
profile creation to happen at sign-up rather than on a separate tab. It was not implemented.
`apps/identity/services/signup_initialization_service.py` provisions a `UserIdentity` row, an
initial memory node, an analytics score, an initial agent run, and an `identity.created` event —
**no social profile**. Confirmed live: a freshly registered user returns **404** from
`GET /apps/social/profile/{username}`. A profile only exists once the user visits
`/profile/:username` and clicks "Create Identity Node", which is why that screen opens in
create-mode for every new account.

**Consolidation options (logged, not chosen — owner deferred the decision to keep walking):**

| # | Option | What it entails |
|---|---|---|
| A | Delete the tab; provision at signup | Remove `InfiniteNetwork` + its route; add social-profile creation to `initialize_signup_state`; `/profile/:username` becomes the single profile surface. Smallest surface, matches the original intent. |
| B | Keep a directory; build its backend | Add `GET /apps/social/profiles`, repoint the page at it, make `/network` read-only browse. Profile creation still moves to signup. |
| C | Fold into `/social` as a Members tab | Delete the standalone route, add a directory tab beside the Trust Feed. Still needs the list endpoint; consolidates social into one destination. |
| D | Park it | Disable the route so nobody hits a dead page; treat consolidation as a redesign decision. |

All four share two prerequisites: profile creation moves into signup, and any directory needs a
new social list endpoint. Note also that `/network` and `/profile/:username` are two UIs for one
concept built against two different backends, one of which doesn't exist — a redesign /
consolidation candidate in the owner's own framing, consistent with the "underspecified
presentation over working backends" theme running through this walk.

---

### 5. Genesis doesn't survive leaving the page — `Defect`

**Observed:** navigated away from Genesis and back. It asked to initialize again, the whole
chat was gone, and no plan had been created.

Three separate problems sit underneath that, and they need separate answers.

**a) `POST /genesis/session` always creates a new session — it never resumes.**
Verified: two POSTs for the same user returned `session_id=7` then `session_id=8`, and the DB
now holds *two rows both `status=active`* for that user. So returning to the page orphans the
previous session and starts over. Duplicate active sessions also accumulate silently, which is
a data-integrity problem independent of the UX.

```
 id | status | synthesis_ready | has_state
----+--------+-----------------+-----------
  7 | active | f               | t
  8 | active | f               | t
```

**b) The progress itself was NOT lost — only orphaned.** Session 7 still holds its extraction:

```json
{"vision_summary": "Run an AI consulting studio", "time_horizon": "5 years", ...}
```

`GET /apps/genesis/session/7` returns it intact (`status`, `summarized_state`,
`synthesis_ready`, `draft_json`). So the plan state survives a page change today — it is simply
unreachable, because nothing resumes it.

**c) The transcript is genuinely unrecoverable.** `genesis_sessions` has no message column at
all — `id, user_id, status, summarized_state, synthesis_ready, draft_json, locked_at,
created_at, updated_at`. Only the *distilled* state is persisted, never the conversation. No
client fix can restore the messages; that needs a schema change.

**Client side:** `getGenesisSession()` exists in `client/src/api/masterplan.js` but is **never
called anywhere**. The client also never persists `session_id`, and there is no
"get my active session" route — so resuming needs either client-side id storage or a new
backend lookup.

**Fix options, cheapest first:**

1. **Make session creation idempotent** — return the user's existing `active` session instead
   of creating another. Restores progress on return, stops orphan accumulation, and needs no
   schema change or client state. Highest value per unit of risk.
2. **Resume on mount client-side** — call `getGenesisSession()` and rehydrate the extracted
   state, so the user sees what Genesis already knows rather than a blank slate.
3. **Persist the transcript** — a `messages` JSON column or a child table. Only this restores
   the chat itself. It is a real decision, not just plumbing: it means storing verbatim
   personal life-planning conversation, with the retention and privacy implications that
   carries, where today the design deliberately keeps only the distillation.

**Recommendation:** do (1) and (2) — they recover the plan, which is the part that matters —
and treat (3) as a deliberate product/privacy decision rather than an implied bug fix.

**Status:** diagnosed. (1) and (2) ready to build on approval; (3) needs a decision.

---

### 6. No password recovery — `Gap`

**Observed:** an internet drop ended the session (logged out), and the account could not be
signed back into. There is no "forgot password" path anywhere in the UI or the API — a
forgotten or mistyped-then-forgotten password locks a real user out permanently, with no
self-service way back in.

**Confirmed:** the entire auth surface is `POST /auth/register`, `POST /auth/login`,
`POST /auth/logout`, `POST /auth/admin/invalidate-sessions/{user_id}`. No reset-request, no
reset-confirm, no email verification, no change-password. Login itself is healthy — verified a
fresh register+login returns 200, a wrong password returns 401 — so this is purely a missing
recovery flow, not a broken one.

**Ownership:** auth lives in the runtime (`AINDY/routes/auth_router.py`,
`AINDY/services/auth_service.py`), not in `apps/`. This is therefore a **runtime feature
request**, not an app-repo change. A minimal version needs:

- `POST /auth/password/reset-request` (email → tokenised link; must not leak whether an
  address exists)
- `POST /auth/password/reset-confirm` (token + new password → `hash_password`, then invalidate
  existing sessions — the `admin/invalidate-sessions` primitive already exists to build on)
- an email-sending capability (a connector), which the runtime does not currently ship
- optionally `POST /auth/password/change` for a signed-in user

**Immediate workaround used during this walk:** the walkthrough account
(`shawnknight@the-master-plan.com`) was reset directly against the local stack using the
runtime's own `hash_password`, verified with a real login. This is a dev-stack unblock only —
it required shell access to the database and is not a substitute for a recovery flow. A real
deployment has no such door.

**Status:** logged for the runtime team. Not an app-repo fix.

---

### 7. Research web-search provider is an unwired stub — `Defect`

**Observed:** a research query returns a summary that reads like an error — e.g. "The provided
message indicates an error due to an invalid API key." The query no longer 500s (that was a
separate route bug, fixed in `fix/research-query-request-param`), but the *content* is the
provider's own auth-failure text, summarised back to the user.

**Why:** the research path is two providers in sequence
(`apps/search/services/research_engine.py`):

1. `web_search(query)` → Perplexity, `GET https://api.perplexity.ai/search?q=…`
2. `ai_analyze(content)` → OpenAI gpt-4o, which summarises whatever step 1 returned

**OpenAI works** — it successfully produced the summary, so `OPENAI_API_KEY` is valid. The
break is entirely in `web_search`, and it is not just a missing env var:

```python
url = f"https://api.perplexity.ai/search?q={query}"
resp = perform_external_call(..., operation=lambda: requests.get(url))
```

- **No auth is ever sent** — a bare `requests.get(url)`, no `Authorization` header.
- **There is no `PERPLEXITY_API_KEY` in config at all** (`hasattr(settings, "PERPLEXITY_API_KEY")`
  is `False`), so there is nothing to send even if a key were added to `.env`.
- **Wrong endpoint** — Perplexity's API is `POST /chat/completions` (OpenAI-compatible), not a
  `GET /search?q=`.

So Perplexity rejects the unauthenticated request with "invalid API key", and gpt-4o dutifully
summarises that error. Present keys on the stack: `OPENAI`, `ANTHROPIC`, `DEEPSEEK` — none of
which is a web-search provider.

**Same gap surfaces in Lead Generation (same root cause).** `search_leads` → the same
`research_engine.web_search` → Perplexity error. Nothing parses out, so it falls back to a
single placeholder lead `{company: "External Search", context: <the raw error text>}`
(`search_service.py:343`), and then OpenAI *scores that placeholder* — producing a lead whose
summary literally reads "intent score is low due to the current API key issue" (observed:
Match Score 26, company "External Search"). So leadgen can't find real leads until the search
provider is wired. The honest-degrade fallback (below) must cover leadgen too: when the search
returns nothing real, return an empty/"no leads found" state rather than scoring an error string.

**Fix options (a decision, not just a key):**

1. **Wire Perplexity properly** — add a `PERPLEXITY_API_KEY` config field, send it as a Bearer
   header, and call `POST /chat/completions`. Requires the user to hold a Perplexity key.
2. **Switch to a search provider the stack has a key for** — none of OPENAI/ANTHROPIC/DEEPSEEK
   is a web search API, so this means adding one (Tavily, Brave, SerpAPI, …).
3. **Degrade honestly** — if no search key is configured, skip `web_search` and either research
   over memory/LLM only or return a clear "web search not configured" state, rather than
   summarising a provider error as if it were a result.

**Decision (owner, 2026-07-21): option 1 — wire Perplexity properly.** Real web research via
Perplexity, not a degrade or a swap. Scope to implement:

- add a `PERPLEXITY_API_KEY` setting (config field + `.env`); the deployment supplies the key
- rewrite `research_engine.web_search` to `POST https://api.perplexity.ai/chat/completions`
  (OpenAI-compatible body: a `sonar`/`sonar-pro` model + messages), with
  `Authorization: Bearer <key>` — routed through `perform_external_call` so the key is never
  logged
- when the key is absent, degrade honestly (option 3 as the fallback path) rather than
  summarising Perplexity's auth error as a result — so local/dev stacks without a key don't
  surface error text as content
- the OpenAI `ai_analyze` summariser stays as-is (it works); it now summarises real search
  results instead of an auth error

**Status:** decided — option 1. Not yet built. Needs a Perplexity key at deploy; safe-degrade
fallback lands with it so a missing key is a clean "web search not configured" state.

---

### 8. A 401 on any request logs the whole session out — `Design`

**Observed:** opening the Dashboard Graph tab bounced the user to the sign-in page, in a loop
(re-login → back to /dashboard/graph → bounce again). The concrete cause was fixed (GraphView
was hitting api-key-gated routes that 401 a normal user — see Resolved #145). But the reason a
*graph widget* could log the user out at all is a broader client-side design choice worth a
decision.

**Why:** the `@aindy/ui-kit` request core dispatches a global `aindy:session-expired` event on
**any** response with status 401 (`authRequest` → `status === 401 && dispatch()`). `AuthContext`
listens for it and clears the token, which drops `isAuthenticated` and sends the user to
`/login`. So a 401 from *any* endpoint — including optional, non-critical dashboard data —
tears down the entire session, even when the component itself catches the error and would have
degraded gracefully. The dispatch fires *inside* the request wrapper, before the component's own
`catch` runs, so a component cannot opt out after the fact.

**Why it's a design item, not just a bug:** treating 401 as "session dead" is correct for
*auth-critical* calls (the token genuinely expired or was revoked). It is wrong for *optional
data* calls, where a 401 may mean "you lack access to this one widget", not "your session is
over". The current all-or-nothing rule means any future endpoint that 401s for a normal user
(a permissions edge, a deprecated route, an admin-only widget on a shared page) becomes a
full-logout bug — exactly how #145 manifested.

**Ownership caveat:** the dispatch lives in `@aindy/ui-kit` (the request core), so the cleanest
fix is upstream. App-side mitigations are possible but partial.

**Options:**

1. **Distinguish auth-critical from optional requests (upstream).** Give the ui-kit a request
   variant that returns `null`/throws on 401 *without* dispatching session-expired (one already
   exists internally — some helpers do `if (status === 401) return null`). Optional widgets
   (graphs, side panels) use it; auth-critical calls keep the session-ending behavior. Correct,
   but needs a ui-kit change.
2. **Verify before logout.** On a 401, don't clear the session immediately — re-check the token
   (local `exp`, or a lightweight `/auth`-side check) and only log out if it's actually invalid.
   Prevents a single endpoint's authorization 401 from ending a valid session. App-side-ish
   (AuthContext), but the dispatch still originates upstream.
3. **Accept it, and enforce a rule:** no user-facing surface may call an endpoint that 401s for
   a normal user. Cheapest, but fragile — it's a convention with no guardrail, and #145 shows
   how easily it's violated.

**Recommendation:** option 1 (upstream) is the right long-term fix; option 2 is a reasonable
app-side stopgap. Until then, the API-route audit + the ownership tests are the only guardrail
against another #145.

**Status:** logged for a decision. Primarily a `@aindy/ui-kit` concern; app-side stopgap
possible in `AuthContext`.

---

### 9. Who saves an SEO analysis, and why "No saved searches yet" — `Question` (answered)

**Observed:** the AI SEO tool works — Analyze SEO returns a scorecard, Generate Meta returns a
description, Get Suggestions returns a strategy. But "Recent SEO Analyses" said *No saved
searches yet* after running one, prompting: who saves it — the user or the system?

**Answer: the system, automatically.** There is no "save" button and no user action anywhere in
search — every analyze / meta / research / leadgen call auto-persists to history via
`execute_durable_search`. SEO analyze *is* wired into that: verified live that
`POST /apps/seo/analyze` writes a `search_history` row with `search_type="seo_analysis"`, and
`GET /apps/search/history?search_type=seo_analysis` returns it (count=1). So it is being saved,
by the system, keyed to the user.

**Why the panel looked empty (fixed):** `SearchHistory` fetched once on mount
(`useEffect(…, [searchType])`) and never again, so a just-run analysis didn't appear until a
page reload. Fixed: the panel now takes a `refreshToken` the tool bumps after a successful
analyze, so the new entry shows immediately.

**Also fixed — meta description length:** `generate_meta_description` used `enforce_word_limit`
(a WORD limit), so the default `limit=160` produced ~160 *words* (~900+ chars) rather than the
~155–160 *characters* a SERP meta description should be. Rewritten to a character budget with
sentence-safe trimming.

**Left as-is (as the owner noted):** suggestion depth scales with the article — "light" output
reflects light input, not a defect. Worth revisiting as an upgrade, not a fix.

**Design note (feeds the frontend-redesign thought):** the auto-save-everything model and the
"Recent …" panels are worth a deliberate decision — should history be per-article, searchable,
deletable, shared across the search surfaces? Currently it's an implicit system behavior with a
thin UI. Not a bug; a design call.

**Status:** answered + the two concrete gaps fixed (panel refresh, meta length).

---

### 10. The social feed reads bare on first look — `Design`

**Observed:** the social feed looks very bare for a social feed on a first pass. Not wrong —
a design note.

**What's actually there:** the primitives exist. `Feed.jsx` renders a post composer, a
social-analytics panel (Posts / Impressions / Clicks / Avg Engagement, top posts, a trend),
post cards with interactions, a loading panel, and an empty state. So it's not unfinished
plumbing — it's minimal *presentation* over a working structure (inline styles, few visual
cues, no rich post chrome).

**The more interesting design point:** it's labelled **"Trust Feed"**, not a social feed, and
the metrics are engagement/impressions/trust-flavoured. So part of why it reads as "bare for a
social feed" may be that it isn't trying to be one — it's a trust/reputation surface wearing a
feed's shape. The design question is identity: is this meant to be a conventional social feed
(rich posts, threading, reactions, media) or a trust/reputation dashboard (scores, standing,
signal)? The current UI sits between the two, which is what makes it feel thin.

**Redesign signal:** this is the third design note in the walk (after the thin "Recent …"
history panels on SEO/LeadGen, and the search surfaces all sharing one shape). The recurring
theme: the app has the right *data and primitives* almost everywhere, but the *presentation
layer and surface identity* are underspecified. That is exactly the input a frontend redesign
wants — the bones are sound; the decisions to make are "what is each surface for, and how rich
should it be."

**Status:** design note, no code change. Feeds the frontend-redesign thread.

---

### 11. Posts don't appear after posting — `Defect`

**Observed:** post from the composer, the form clears as if it worked, but the post never shows
in the feed.

**Three layered causes (all addressed):**

1. **The social layer is MongoDB-backed, and Mongo wasn't running.** `docker-compose.prod.yml`
   ships without Mongo (social is "degradable"). With no Mongo, `create_post` and `get_feed`
   fall into their degraded branch. Added an opt-in overlay `docker-compose.mongo.yml` to run
   Mongo locally:
   `docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml up -d`.

2. **A false-success on the degraded path (the real bug).** When Mongo was absent, `create_post`
   returned a `_mongo_degraded_payload` wrapped in a **200 SUCCESS** envelope, so the client saw
   success, cleared the form, and refetched an empty feed — a silent no-op the user reads as
   "my post vanished." Now the `db is None` path raises **503** (`social_unavailable`) for both
   `create_post` and `get_feed`, so a missing/again-down social layer reads as *unavailable*,
   not *posted-and-lost*. Honest failure over silent data loss.

3. **A 500 on every successful post once Mongo WAS enabled.** `insert_one` mutates the doc in
   place, adding a Mongo `_id` (ObjectId); `create_post` returned that raw dict, and FastAPI's
   JSON encoder raised `'ObjectId' object is not iterable` → 500. (The feed was unaffected — it
   rebuilds each doc through the `SocialPost` model, which sheds `_id`.) Fixed by dropping `_id`
   after insert. Verified live: with the Mongo overlay, `POST /apps/social/post` → 200 and the
   post appears in `GET /apps/social/feed`.

**Note for deploy:** social requires Mongo. It's degradable by design, but "degraded" now means
an honest *unavailable*, not a fake success. Decide per-environment whether social is enabled.

**Status:** fixed. Social works with the Mongo overlay; the false-success + 500 are gone.

---

### 12. The feed renders nothing, and the analytics panel is structurally zeroed — `Defect`

**Observed (from the browser console, while walking `/network`):**

```
Feed.jsx:69 safeMap prevented crash. Value: {status:'SUCCESS', data: Array(7), result: Array(7), …}
```

Seven posts came back and none were on screen.

**Why:** every `/apps/social` route runs its handler through `execute_with_pipeline_sync` and
returns the standard `{status, data, result, events, next_action, trace_id}` envelope. But
`client/src/api/social.js` was the one API module with **zero** `unwrapEnvelope` calls, so the
raw envelope was handed to the components:

- `setPosts(envelope)` → `safeMap` receives an object and renders nothing. The empty state
  doesn't rescue it either: `posts.length === 0` is `undefined === 0` → false. So the stream is
  blank with no explanation — the worst of both branches.
- `analytics.overview` is read off the envelope → `undefined` → Posts / Impressions / Clicks /
  Avg Engagement all display `0`.
- View-mode `ProfileView` reads `profile.username.charAt(0)`, which throws on an envelope.

**This partly re-explains open item 10** ("the feed reads bare"). That was logged as a
presentation/identity design note, and the presentation point stands — but the analytics panel
was *also* structurally zeroed by this bug, so the surface was reading barer than it is.

**Fixed:** all six functions in `social.js` now `.then(unwrapEnvelope)`. `unwrapEnvelope` is
safe here — it only unwraps when a `data` key is present and rethrows an embedded `error`.
Regression test added at `client/src/test/social-envelope.test.jsx` (feed returns an array,
analytics exposes `overview`, profile returns the document).

**Status:** fixed.

---

### 13. `unwrapEnvelope` coverage across the client API layer is inconsistent — `Defect` (systemic)

**Observed:** item 12 was not a one-off. Auditing `client/src/api/`:

| Has `unwrapEnvelope` | Has none |
|---|---|
| `analytics`, `arm`, `tasks` | `agent`, `masterplan`, `memory`, `rippletrace`, `search`, `freelance`, `identity`, `operator` |

The same walk console also emitted ~40 `safeMap prevented crash` lines originating **inside
`@aindy/ui-kit`**, which is the same signature: a component handed an envelope where it expected
an array.

**Why it isn't a blanket fix:** not every route is enveloped — only those routed through the
execution pipeline. Applying `unwrapEnvelope` indiscriminately would corrupt any plain response
that legitimately carries a `data` key. The correct unit of work is per-module: check which of
that domain's routes wrap, then unwrap those.

**Predicted symptom while walking:** "the data exists but the screen is empty," with no error
and no empty state — precisely the shape of items 11 and 12, and previously of the dashboard
overview (#137). Tasks, MasterPlan and Memory are the next likely hits.

**Status:** diagnosed. Verify per surface as the walk reaches it rather than sweeping blind.

---

### 14. A created task never appears in the list — `Defect`

**Observed:** on `/tasks`, adding a directive appeared to do nothing — the input cleared and the
list still read "No active directives."

**The task was created correctly.** Verified live with exactly the body the UI sends
(`{name, priority}`): `POST /apps/tasks/create` → **200**, row persisted with `task_id=2`, and
`GET /apps/tasks/list` → **200** returning that task. Both ends of the round trip work.

**Why nothing rendered:** `/apps/tasks/list` nests its array one level deeper than the other
list routes. After `unwrapEnvelope` the caller holds:

```json
{ "tasks": [ { "task_id": 2, "task_name": "…" } ], "execution_envelope": { … } }
```

— an object, not an array. `TaskDashboard` then does
`Array.isArray(data) ? [...data] : []`, which discards it and falls through to the empty state.
So the screen reported "no tasks" while the API was returning one.

This is the *second* form of item 13. The first (social, item 12) was a missing unwrap; this one
has the unwrap and still fails, because a single unwrap isn't sufficient when the payload nests
the collection under a named key. Worth checking both shapes on the remaining surfaces.

**Fixed:** `getTasks` now flattens `data.tasks`, passing a bare array through unchanged and
yielding `[]` when the key is absent. Regression test at
`client/src/test/tasks-list-payload.test.jsx` (3 cases).

**Status:** fixed.

---

### 15. Is a task tracked, or executed by the AI? — `Question` (answered)

**Asked while walking `/tasks`:** the screen is titled "Execution Engine" and the input says
"Initialize new directive," which reads like work handed to the AI. Is a task something the AI
completes, or something the user tracks?

**Answer: tracked by default. AI execution exists, is opt-in, and has no UI.**

The `Task` model is a rich tracking record — status, priority, category, due/scheduled/reminder
times, recurrence, estimated hours (`duration`), actual elapsed `time_spent`, dependencies
(`depends_on` / `dependency_type`), parent/child nesting, and a `masterplan_id` link. Completing
one drives real machinery: MasterPlan ETA/WCU recalculation, the Infinity orchestrator, a TWR
score, dependency-unlock cascade.

Autonomous execution hangs off two columns — `automation_type` and `automation_config`. When
`automation_type` is set, `queue_task_automation` dispatches an `automation.execute` autonomous
job into the automation domain's connectors (social, crm, email, webhook, stripe, subscription,
content_generation).

**Two facts explain why adding a task feels inert even by design:**

1. **Automation fires on completion and unlock — never on creation.** The call sites are
   `reason="task_completed"` and `reason="task_unlocked"` in `task_service.py`. Nothing runs
   when a task is added, even a fully configured one.
2. **The UI cannot set `automation_type` at all.** `TaskCreate` accepts 13 fields; the dashboard
   sends exactly two — `{name, priority}` (`TaskDashboard.jsx` line 36). So `automation_type`,
   `automation_config`, `due_date`, `estimated_hours`, `masterplan_id`, `dependencies`,
   `recurrence`, `reminder_time` and `scheduled_time` are all reachable by the API and by agent
   tools, and unreachable from the screen.

So the surface is a plain to-do list wearing an execution engine's name, sitting on top of a
scheduler, a dependency graph, a MasterPlan link and an automation dispatcher — none of which
it exposes. The tracked-vs-executed confusion is an honest reading of what's on screen.

**Redesign signal — the strongest one yet.** Earlier notes (thin "Recent…" panels, the shared
search shape, the Trust Feed identity) were about presentation depth. This is the same pattern
at its most extreme: the backend supports scheduling, recurrence, dependencies, MasterPlan
linkage and autonomous execution, and the UI is one text input. The decision to make is what
`/tasks` is *for* — a quick capture list, a project planner over the dependency/MasterPlan
model, or the console for AI-executed work — and it can be answered without building backend.

**Status:** answered. The design decision (what to expose, and whether creation should ever
trigger automation) is open.

---

### 16. The only non-Genesis MasterPlan create route 500s — `Defect`

**Context:** raised while walking `/tasks` — "to walk the MasterPlan tab, one has to be created
via Genesis first." That is correct, and not only by design: the alternative path is broken.

There is **no** `POST /apps/masterplans`. Two creation paths exist:

1. `POST /apps/genesis/lock` → `create_masterplan_from_genesis` — the Genesis route.
2. `POST /apps/compute/create_masterplan` — a direct create from raw fields.

**Path 2 fails.** Verified live with a well-formed `MasterPlanInput` body:

```
POST /apps/compute/create_masterplan -> 500
{"detail": "'name' is an invalid keyword argument for MasterPlan"}
```

`create_masterplan_compute` does `MasterPlan(**data)`, but `MasterPlanInput` declares a `name`
field the `master_plans` table does not have. Even with `name` removed it would still fail:
`target_date` is `nullable=False` and the input never supplies it (the Genesis factory computes
it as `start_date + duration_years × 365`). The schema and the model have drifted apart, and
nothing in the client calls this route, so it went unnoticed.

**Consequence:** Genesis is the *only* working way to obtain a MasterPlan. Every downstream
surface that depends on a plan — MasterPlan dashboard, ETA/WCU projection, task→plan linkage,
the analytics masterplan endpoints — is gated behind completing a Genesis conversation.

**Note:** `GET /apps/masterplans/` returns `{plans, execution_envelope}` *unwrapped* (no
`{status, data}` envelope), and `MasterPlanDashboard` reads `data.plans` accordingly, so that
path is correct. Recording it because it is a *third* response convention alongside the two in
item 13 — enveloped, and enveloped-with-a-nested-key.

**Status:** confirmed live, unfixed. The fix needs a decision, not just a patch: `name` has no
column to land in, so either the model gains one or the schema drops it.

---

### 17. MasterPlan, Genesis/Assistant and Tasks were one section and are now disconnected — `Design`

**Observed (owner):** these three were originally a single tab/section. They are now separate
top-level routes, and the connective tissue went with the split.

**What the code confirms:**

- **Tasks cannot be attached to a plan from the UI.** `Task.masterplan_id` exists, is indexed,
  and drives ETA/WCU recalculation and the completion cascade. `TaskCreate` accepts it.
  `masterplan_id` appeared in the client only in `AnalyticsPanel` (since removed — item 18)
  and the projection context —
  **never** in the task-creation path (see item 15: the form sends `{name, priority}`).
  So every task created through the UI is permanently orphaned from every plan.
- **The link is real on the backend.** Completing a task recalculates the active plan's ETA and
  WCU and cascade-activates it (`_handle_task_completed` in `apps/tasks/bootstrap.py`). The
  machinery to make tasks and plans one system is built and running — it just never receives a
  `masterplan_id` from the surface where users create tasks.
- **Genesis is the sole entry point**, and its one alternative is broken (item 16).

So the split is not cosmetic: it severed the field that made the three surfaces one product.
This is the same "working backends, underspecified presentation" theme, but here the missing
piece is a *single field on a form*.

**Proposal raised by the owner — import a plan authored elsewhere.** Bring in a MasterPlan
drafted with an external assistant (Claude, ChatGPT), translated into A.I.N.D.Y.'s data points.
Worth recording because the insertion point is unusually clean:

- The translation target already exists. Genesis synthesis produces a **draft** — phases,
  success criteria, risk factors, ambition score, `time_horizon_years` — persisted to
  `GenesisSessionDB.draft_json`, and `create_masterplan_from_genesis` builds the plan from it
  (`structure_json`, `posture`, timeline, plus the anchor/goal fields `anchor_date`,
  `goal_value`, `goal_unit`, `goal_description`).
- So an import does **not** need a new creation pathway. It needs a translator from external
  prose into the existing draft shape, written to `draft_json` with `synthesis_ready=True` —
  after which the existing `/apps/genesis/lock` does the rest unchanged.
- That also answers where it belongs: import becomes a *way to start a Genesis session*, not a
  fourth parallel path, which keeps a single lock/versioning/audit route.
- Open questions: how much fidelity is required before a plan is "translatable"; whether the
  user reviews and edits the translated draft before locking (the audit route `/apps/genesis/audit`
  is the natural hook); and whether a low-confidence translation should drop the user into a
  Genesis conversation to fill the gaps rather than fail.

**Redesign signal:** the fourth and clearest structural one. Earlier notes were about how rich a
surface should look. This is about which surfaces should exist at all — the owner's read is that
MasterPlan, Genesis/Assistant and Tasks want to be one section again, and the orphaned
`masterplan_id` is the concrete evidence.

**Status:** design decision. The task→plan link is the smallest piece and could be fixed
independently of any redesign.

---

### 18. Analytics and KPI Snapshot — owner verdict on scope — `Design` → `Defect` — CLOSED

**Analytics (`/analytics`)** is LinkedIn analytics, and owner-specific: it reflects one person's
channel rather than anything a general user of the product would have. Flagged by the owner as a
candidate for removal rather than redesign.

**KPI Snapshot (`/kpi`)** is currently a calculate-your-own-metrics surface — the user enters
numbers and it computes. Nothing is wrong with it as built; the owner's original intent was a
**dashboard** (values derived from the system's own data), not a manual calculator.

**KPI half: CLOSED (#168).** Rewired onto the live Infinity score engine; the manual calculators
were parked in a `/tools` drawer. See `docs/archive/KPI_DASHBOARD_WIRING.md`.

---

**Analytics half: CLOSED.** Walked in depth, and the scope question was overtaken by fact — the
surface was not merely narrow, it had **never once worked**. `canonical_metrics`, the table the
whole surface exists to populate, held **0 rows**. Three independent breaks, each verified live:

1. **The form never matched its own API — HTTP 422 on every submit.** `AnalyticsPanel` sent
   `reach` / `interactions` / `followers`; `LinkedInRawInput` accepts none of those names and
   requires `scope_type` + `members_reached`, which the form never collected. Only `impressions`
   mapped 1:1. Reproduced with the exact client payload:
   `422 missing: body.scope_type, body.members_reached`.
2. **The backend fails too, on a contract-correct payload — HTTP 500.**
   `analytics_linkedin_ingest_node` serializes through a syscall (`data.model_dump()`, a dict),
   but `apps/social/services/linkedin_adapter.py:5` does attribute access (`raw.likes`):
   `AttributeError: 'dict' object has no attribute 'likes'`. The adapter was never converted
   from object to dict access when the syscall indirection landed, so the write path is
   structurally incapable of succeeding.
3. **The prerequisite could not be created either.** Analytics requires a `masterplan_id`; the
   DB held 0 masterplans and `/apps/compute/create_masterplan` returned 500 unconditionally
   (see item 34).
4. **Zero test coverage** on the whole path — no test touched `linkedin_adapter` or the route,
   which is why three simultaneous breaks went unnoticed.

**The dead-twin pattern, third instance.** As with `/kpi` (and the response-envelope class from
the prior walk), a working system-fed engine already existed and the wrong surface was wired to
the nav. `GET /apps/social/analytics` returns real `overview` / `top_posts` / `trend` / `signals`
computed from actual posts — it was only rendered inside the Trust Feed, and its `signals` field
was dropped entirely.

**Fixed.** `/analytics` now renders the live social engine (`SocialAnalytics.jsx`), including the
previously unrendered `signals`. `AnalyticsPanel.jsx` and the two dead API wrappers are deleted.
Per owner decision the **backend is parked, not deleted** — `linkedin/manual`, the masterplan
analytics reads, the flow nodes and `CanonicalMetricDB` remain in place but are unused and
unreferenced by any client. Nothing consumes `canonical_metrics`; the Infinity scoring services
do not read it, so parking costs nothing.

**Still open (owner's original point stands):** if manual channel ingest is ever wanted, it needs
all three breaks fixed plus a decision about which channels — not just LinkedIn.

---

### 34. `/apps/compute/create_masterplan` could never succeed — `Defect` — FIXED

**Found while answering item 18** (analytics needs a `masterplan_id`, and none could be made).

`create_masterplan_compute` passed the request body straight into `MasterPlan(**data)`. Two
things made that impossible:

- `MasterPlanInput` required a `name` field **the ORM has no column for** →
  `TypeError: 'name' is an invalid keyword argument for MasterPlan` → HTTP 500 on every call.
- `master_plans.target_date` is NOT NULL and was never supplied, so even without `name` the
  insert would have failed.

**A third problem sat behind those:** the compute routes returned the ORM object itself, which
the response envelope rendered as `{}` — `/apps/compute/masterplans` listed `[{}]` and a created
plan came back with no id. The route family is itself a **dead twin** of the working
`/apps/masterplans/`, which projects its rows explicitly.

**Fixed.** `name` is now optional and discarded (no column to map it to); `target_date` is
derived from the horizon exactly as `create_masterplan_from_genesis` does; `is_origin` follows
the same per-user lineage rule; and both compute routes return an explicit projection matching
the masterplan domain's own shape. Verified live: create → 200 with the plan body, list → real
rows. Covered by `tests/unit/test_compute_masterplan_create.py` (6 tests).

**Left open:** `apps/masterplan/schemas/masterplan.py::MasterPlanInput` is a second, entirely
unreferenced copy of the same schema — dead duplicate, not deleted here to keep the diff focused.

---

### 19. ARM Analyze — what is it analyzing, and how would it reach your file? — `Defect`

**Asked while walking `/arm/analyze`:** it is a small text box prefilled with `tests/example.py`.
What does it actually analyze, and how would it get access to the file?

**Answer: files on the SERVER's filesystem — never yours.** `validate_file_path` does
`Path(file_path).resolve()` and requires `path.exists()`, resolved relative to the API process's
working directory (`/app` in the deployed image). There is no upload, no repo connection, no
file picker, and no access to the visitor's machine. In practice it can only analyze code that
ships inside the container — A.I.N.D.Y.'s own source. It is a developer tool pointed at the
server's own source tree, presented as a general product surface.

**Three concrete defects behind that:**

1. **The prefilled default cannot succeed.** `tests/` is not in the deployed image — `/app`
   contains `README.md`, `apps`, `alembic`, `scripts`, `logs`, `build`, `pyproject.toml` and no
   `tests`. Verified live: `tests/example.py` → `404: File not found`. The out-of-the-box first
   run is guaranteed to fail.
2. **The failure is completely invisible.** A failed analysis returns **HTTP 200 with
   `status: "success"`**; the real error lands at `data.error` ("Node arm_analyze_code failed
   after N retries"). `ARMAnalyze` only sets its error state when the request *throws*, so
   nothing throws, `result` has no `summary` / scores / findings, every render block is falsy,
   and the screen shows **nothing at all** after Run Analysis. Same false-success class as the
   social degrade (item 11) and the dashboard envelope bug (#137) — this is the third instance.
3. **A valid path also fails on this stack**, but for an unrelated reason: `apps/arm/models.py`
   passes validation, is read, and then the outbound LLM call fails repeatedly
   (`external.call.failed`) — a local provider-key/config matter, not an ARM bug.

**Fixed (client):** `submit` now surfaces `res.error` (with `failed_node`) in the existing error
banner instead of silently rendering an empty page; the misleading default is cleared; the
placeholder states that the path is server-side and relative to the API working directory; and
an empty submit is guarded.

**Left open (needs the owner's intent):** what the default path *should* be, and more
fundamentally whether ARM Analyze is a product surface at all. If it is meant to analyze the
user's code, it needs an upload or a repo connection — neither exists. If it is meant to analyze
A.I.N.D.Y.'s own source, it is an internal/dev tool and should say so.

---

### 20. ARM has no project-root confinement — `Security`

**Found while answering item 19.** `validate_file_path` guards with three mechanisms: a blocked
path-segment list (`.env`, `venv`, `__pycache__`, `.git`, `secrets`, `credentials`, `keys`), an
extension allowlist (`.py .js .jsx .ts .tsx .json .md .txt .yaml .yml`), and a post-read content
scan for secret-shaped patterns. **There is no check that the resolved path stays inside the
project root.**

Verified directly against the validator in the running container:

```
/usr/local/lib/python3.11/this.py  -> ALLOWED
/app/apps/arm/models.py            -> ALLOWED
/etc/hostname                      -> blocked (422, no extension — not by confinement)
```

`/etc/passwd` and `../../etc/hosts` are rejected only because they lack an allowlisted
extension, not because they are outside the project. So any authenticated user can read **any
`.py`/`.js`/`.json`/`.yaml`/`.md`/… file anywhere on the server filesystem**, and its contents
are then sent to an external LLM provider. The content scan catches secret-shaped strings, but
it runs *after* the read and only matches known patterns — site-packages source, deployment
YAML, and application config that isn't shaped like a key all pass through.

**Recommended hardening:** resolve against an explicit configured root and require
`resolved.is_relative_to(root)`, rejecting anything outside it — a confinement check rather than
an extension guess. Cheap to add, and it makes the existing allowlist a second layer instead of
the only one.

**Status: ✅ FIXED (#194, 2026-08-05).** `resolve_project_root()` (CWD by default — `/app` in
the image, which is already where ARM resolves relative paths from — overridable with
`AINDY_ARM_PROJECT_ROOT`), checked **before** the segment and suffix guards, which stay as a
second layer. `.resolve()` collapses `..` and follows symlinks, so traversal and escaping links
are both caught; containment is checked before existence so the validator is not an existence
oracle. Re-probed on the live container: `/usr/local/lib/python3.11/this.py` now 403
containment, `/app/apps/arm/models.py` still resolves, `/etc/*` refused for the right reason.

The fix also removed a byte-identical `SecurityValidator` copy in
`apps/arm/services/deepseek/__init__.py` — importable as a *different class object*, so the fix
would have been bypassable by importing the package instead of the module.

The item 19 question (what ARM is *for*) remains open; it turned out not to block the root
choice, because ARM already resolves relative paths from the process CWD.

---

### 21. The whole ARM surface — what it actually does — `Analysis`

Requested instead of walking the remaining five screens. Context: ARM began as a **coding tool**
and was later reframed as the **Autonomous Reasoning Module**. This records what the code does
today, so the redesign decision is made against fact rather than intent.

**Headline:** the autonomy is real and it is the best-engineered part of the domain — but its
entire input corpus is code-analysis telemetry. ARM autonomously tunes the LLM parameters of a
code analyzer, based on how well that code analyzer performed. The reframing happened at the
naming layer; the substrate is unchanged.

**The six screens**

| Screen | Route | What it actually does |
|---|---|---|
| Analyze | `POST /arm/analyze` | The original coding tool. Reads a **server-side** file, sends it to an LLM, returns architecture / performance / integrity scores and findings. Writes `AnalysisResult`. (See items 19 & 20.) |
| Generate | `POST /arm/generate` | The other half of the coding tool: prompt + `original_code` + language → generated/refactored code, optionally linked to a prior analysis via `analysis_id`. Writes `CodeGeneration`. |
| Logs | `GET /arm/logs` | A usage ledger over `AnalysisResult` + `CodeGeneration` — file, status, tokens, execution seconds, task priority, derived tokens/sec. Not reasoning traces; session history. |
| Config | `GET/PUT /arm/config` | The LLM knobs: model ids (analysis/generation), temperatures, `max_chunk_tokens`, `max_output_tokens`, retry limit/delay, `max_file_size_bytes`, `allowed_extensions`, plus Infinity TP defaults (complexity / urgency / resource cost). Per-user row in `arm_config`. |
| Metrics | `GET /arm/metrics` | The "Thinking KPI System": execution speed (tokens/sec), decision efficiency (% successful sessions), AI productivity boost, lost potential (waste), learning efficiency (trend). |
| Suggest | `GET /arm/config/suggest` | `ARMConfigSuggestionEngine` — threshold rules over those metrics producing prioritized config changes with issue / expected impact / risk. Advisory; the user applies via `PUT /arm/config`. |

**The genuinely autonomous layer — and it has no UI.** Three routes exist that no client code
calls: `POST /arm/config/auto-tune`, `POST /arm/config/auto-tune/revert`,
`GET /arm/config/auto-tune/history`. This is the closed Reflect → Adjust → **Learn** loop, and
it is carefully built:

- a **key allowlist** of six numeric knobs — model ids and `allowed_extensions` are deliberately
  excluded so a tuner can never silently swap the model or widen the readable file surface;
- **absolute clamps** per key, independent of the suggestion engine's own step math;
- `MIN_SESSIONS = 5`, `MAX_CHANGES_PER_RUN = 3`, `COOLDOWN_HOURS = 6`;
- a 24h observation window, after which each applied change is judged on a health scalar
  (`decision_efficiency − waste_percentage`); a change that degrades health by ≥3 is
  **auto-reverted** and its key enters a **7-day penalty box**;
- full `prior_config` / `resulting_config` snapshots per run, so any run reverts exactly.

**Five structural findings**

1. **The reasoning corpus is code sessions.** `ARMMetricsService` reads only `AnalysisResult`
   and `CodeGeneration`. Nothing else writes those tables — the sole writer is
   `deepseek_code_analyzer.py`. Every metric, every suggestion and every auto-tune decision
   traces back to "how did our file analyses go."
2. **The loop is starved by design.** Metrics need ≥5 sessions; sessions only come from
   analyze/generate; analyze can only read files that ship inside the container (item 19). In a
   real deployment the autonomous layer can never accumulate the data it needs to act.
3. **Three dead models.** `ARMRun`, `ARMLog` and `ARMConfig` (the old `parameter`/`value` table)
   are never instantiated anywhere in the codebase — verified by grep across `apps/` and
   `AINDY/`. Vestigial from the coding-tool era; `/arm/logs` is served from the analysis tables
   instead. Three of ARM's seven models are dead weight.
4. **Nothing schedules it.** ARM registers no scheduled job. Auto-tune fires only on an explicit
   route call, the `arm.autotune` agent tool, or the `arm_config_autotune` flow. "Autonomous"
   means *unattended when invoked*, not *running on its own*.
5. **The quality proxy is weak, and says so.** "AI productivity boost" is the output/input token
   ratio — a more verbose response scores as more productive. The module docstring is honest
   about it being a proxy, but the suggestion engine treats it as signal.

**What is actually valuable here.** The gate/clamp/cooldown/penalty-box/auto-revert/audit
machinery is domain-agnostic, and it has **already been reused** — `revenue_intelligence_service`
(freelance) and `lead_execution_service` (search) implement the same `evaluate_outcomes`
learning-close pattern. ARM's real contribution to the product is that pattern, not its file
analysis. That is worth knowing before deciding ARM's fate: deleting the coding tool would not
cost the reusable asset.

**Decisions this surfaces**

- **Is ARM a product surface or a dev tool?** Analyze/Generate/Logs are a coding tool with no
  path to the user's code. If it stays, it needs an upload or repo connection; if not, it should
  be internal.
- **Should the reasoning engine reason about something else?** The self-tuning machinery is
  sound and domain-agnostic. Pointing it at agent runs, flow executions or task outcomes would
  make "Autonomous Reasoning Module" literally true — and those tables already have data,
  unlike `analysis_results`.
- **Six screens for one domain is disproportionate**, especially when the most autonomous part
  (auto-tune apply/revert/history) is the part with no UI at all. If ARM survives, Config /
  Suggest / Metrics / Logs are one screen, not four.
- **Drop the dead models** regardless of the outcome.

**Status:** analysis complete; no code changed. Decisions above are the owner's.

---

### 22. Every Identity dimension card renders blank — `Defect`

**Observed while auditing item 23:** the Identity screen renders, but all four dimension cards
(Communication, Tools & Tech, Decision Making, Learning Style) show no values, and the evolution
panel sits at 0 observations / 0 changes regardless of state.

**Why:** every `/apps/identity` route runs through `execute_with_pipeline` and returns the
`{status, data, …}` envelope — verified live on `/`, `/evolution`, `/context` and `/inference`.
`client/src/api/identity.js` had **no** `unwrapEnvelope`, so `IdentityDashboard` read
`profile?.["communication" | "tools" | "decision_making" | "learning"]` off the envelope, where
all four are `undefined`. `profile?.evolution` is undefined for the same reason.

The payload keys match the UI's `DIMENSION_META` exactly (`get_profile()` returns
`communication` / `tools` / `decision_making` / `learning` / `evolution`), so nothing else was
wrong — one missing unwrap emptied the whole screen.

**Fourth instance of item 13**, after social (12), tasks (14) and ARM's blank render (19).

**Note on the contrast, now pinned by a test:** the `/apps/memory` routes are **not** enveloped —
they return `{nodes, execution_envelope}` and `{results, count, …}` directly — which is why
`memory.js` correctly has no unwrap, and why Memory "seems to work" while Identity did not.

**Fixed:** all four functions in `identity.js` now unwrap. Regression test at
`client/src/test/identity-envelope.test.jsx`, which also pins the memory-side non-unwrap so a
future sweep doesn't "fix" it into breakage.

---

### 23. Identity and Memory — what they actually do — `Analysis`

Requested audit of both surfaces.

## Identity — the naming mismatch is real

**Identity is not an account/profile surface. It is a personalization model of the user, built
for the AI to condition on.** The owner's read while walking ("it seems to be tuning for the AI,
possibly with the assistant") is correct, and slightly understated: that is its entire purpose.

`UserIdentity` (runtime-owned) stores four dimensions:

| Dimension | Fields |
|---|---|
| Communication | `tone`, `communication_notes` |
| Tools & languages | `preferred_languages`, `preferred_tools`, `avoided_tools` |
| Decision-making | `risk_tolerance`, `speed_vs_quality`, `decision_notes` |
| Learning style | `learning_style`, `detail_preference`, `learning_notes` |

Plus evolution tracking: `observation_count`, `evolution_log`, `last_updated`.

The service docstring states the design principle outright: *"Identity is inferred, not declared.
A.I.N.D.Y. watches what users do and builds a picture of who they are over time."*

**Where it is consumed — confirmed by call sites:** `apps/identity/public.get_context_for_prompt`
returns an LLM-injectable string, and it is injected into

- **Genesis** — `genesis_ai.py` concatenates `GENESIS_SYSTEM_PROMPT + prior_context +
  arm_context + identity_context`;
- **ARM analysis** — `deepseek_code_analyzer.py` prepends `identity_context` to the analysis
  prompt.

So the screen is a **control panel for how the AI talks to you**, mislabelled as "Identity" —
which in every other product means account, login, profile, or the social identity that
`/profile/:username` actually owns (see item 4). Two different things share the word across the
nav.

**The inference machinery is genuinely good, and almost unfed.** `identity_inference_service`
is a transparent weighted vote over accumulated `IdentitySignal` evidence: exponential recency
decay (30-day half-life, env-overridable), a 0.6 confidence floor, `MIN_SUPPORT = 2.0`, and a
0.15 switch margin so a committed value only flips on sustained counter-evidence. Every verdict
exposes its full distribution, confidence and support.

But **`observe_identity_event` is called from exactly one place in the entire app** —
`masterplan_factory`, when a plan is locked from Genesis. One event source, and it fires once
per plan lock. An inference engine designed to watch behaviour over time is being fed a single
rare event, so in practice the profile only ever changes when the user edits it by hand — the
opposite of "inferred, not declared."

**Note:** `/apps/identity/inference` and `/apps/identity/boot` exist and have **no client
caller** — the inference verdicts (the interesting part, with distributions and confidence) are
not surfaced anywhere.

## Memory — a runtime engine with a thin app wrapper

**The memory system is runtime-owned.** `apps/memory/bootstrap.py` is 18 lines and registers
exactly two routers: traces and metrics. Everything else the browser uses —
`/apps/memory/nodes`, `/recall`, `/recall/v3`, `/suggest`, `/nodes/{id}/feedback`,
`/performance`, `/history`, `/traverse`, `/share`, `/federated/recall`, `/nodes/search`,
`/nodes/expand`, `/links`, `/agents` — is registered by the runtime and merely surfaced under
the `/apps/memory` prefix. The app owns ~289 lines; the client surface is 590.

**It works because it is actually fed.** Unlike ARM's starved loop (item 21) and Identity's
single observer, memory is populated automatically by domain events through registered capture
policies — `tasks`, `arm`, `automation`, `masterplan` and `search` each register a
`memory_policy` mapping event types to significance, node type and tags (e.g. `task_completed`
→ significance 0.5, `outcome`; `task_failed` → 0.8, `failure`). Signup also writes a first node.
So memory accumulates from ordinary product use with no user action, which is why this surface
behaves.

**What the browser exposes:** node list with tag filter, semantic recall (v3, with a scoring
formula and version returned), suggestions, per-node success/failure feedback, per-node
performance and history, graph traversal to depth 2, sharing a node, and a metrics dashboard.
That is a rich, coherent surface — the most complete one found in the walk so far.

**Observation:** memory is the one surface where the presentation matches the backend's
capability. It is also the one the owner reports as working. Worth noting for the redesign —
it is the internal benchmark for what "richness matched to the engine behind it" looks like.

## Decisions surfaced

- **Rename Identity.** It is an AI personalization/preferences surface, not identity. Candidates:
  "Preferences", "How A.I.N.D.Y. works with you", "Personalization". This also removes the
  collision with the social profile at `/profile/:username`.
- **Feed the inference engine, or drop it.** One observer for a machine built to watch
  behaviour is the core defect of the design, not the code. Task completions, agent runs and
  flow outcomes are all already-instrumented events that could call `observe_identity_event`.
- **Surface the inference verdicts, or delete the routes.** `/inference` and `/boot` have no
  caller; the distribution/confidence output is the most interesting thing Identity produces.
- **Consider folding Identity into the assistant surface.** If its only job is conditioning how
  the AI behaves, it belongs next to the AI — consistent with the item 17 view that
  Genesis/Assistant/MasterPlan/Tasks want to be one section.
- **Memory needs no rework.** Judge other surfaces against it.

**Status:** analysis complete; one defect found and fixed (item 22). Decisions above are the
owner's.

---

### 24. Two API instances answered `localhost:8000` — `Environment`

**Symptom:** the admin account created for the platform walk returned
`401 Invalid email or password` in the browser, while the identical credentials returned 200
from inside the API container.

**Cause — a stale WSL port relay, not the app.** Two listeners held port 8000:

```
PID 10840  com.docker backend   0.0.0.0:8000     (container publish)
PID 3216   wslrelay.exe       127.0.0.1:8000     (stale WSL relay)
```

Windows resolves `localhost` to loopback first, and the more specific `127.0.0.1` binding beat
Docker's `0.0.0.0` publish — so every `localhost:8000` request was relayed to a dead WSL endpoint
that still had a live listener behind it, serving older code against a different database. The
container's own listener was present and unreachable.

Proved by bypassing loopback — same port, same moment, opposite datasets:

| Path | `admin@local.test` | ghost-stack user |
|---|---|---|
| `localhost:8000` (via relay) | 401 | 200 |
| `172.23.16.1:8000` (direct) | **200** | **401** |

A standalone `aindy-runtime serve` (PID 773) was also running natively in WSL and was stopped
first; that alone did **not** fix it. Killing `wslrelay.exe` did — after which Docker's listener
was the only one on 8000 and `localhost` resolved correctly.

**Why it mattered:** for several hours the browser and the verification commands were talking to
*different stacks*. Everything "verified live" against the container during that window —
including the empty-Mongo observation — described the wrong instance. `/api/version` is identical
on both (`boot_mode`, `boot_profile`, `app_plugin_count=17`), so nothing in the API surface
distinguishes them.

**Guard for next time:** when a result contradicts what the browser shows, compare `localhost`
against the direct Docker IP *before* debugging the application. The cheap remedy is killing the
relay process, not a reboot. This is the concrete form of the "don't `wsl --shutdown` a running
stack" hazard already recorded in the local-stack-operations notes.

---

### 25. The dev proxy swallowed every `/platform` API call — `Defect`

**Observed:** `/platform/flows` crashed on load with
`TypeError: Cannot read properties of undefined (reading 'reduce')` and the error boundary blanked
the console.

**Cause:** `/platform` is **both** the SPA mount and the backend's operator API namespace (51
routes). `vite.config.ts` had **no `/platform` proxy entry at all**, while `platformHtmlFallback`
rewrote every extension-less `/platform` GET to `platform.html`. So every platform API call
returned the SPA's HTML with a **200**:

```
$ curl -H "Authorization: Bearer $TOK" localhost:5173/platform/flows/runs?limit=20
<!DOCTYPE html> …
```

**No platform panel could load data.** `FlowRunsPanel` was simply the first to dereference the
HTML (`runs.runs.reduce`).

Two non-obvious details in the fix: the split must happen in the **proxy**, because Vite installs
the proxy ahead of plugin middlewares (a middleware-only `Accept` gate was tried first and the
proxy still won); and `bypass` must return extension paths rather than proxying them, since
`/platform.html` and `/platform/assets/*` themselves start with the proxy prefix and would
otherwise be forwarded to the API and 404.

**Third dev-proxy / route-plumbing defect of the walk**, after the `/api` prefix strip (#132) and
the missing `/apps` mount (#133).

**Status:** fixed in #158.

---

### 26. Registry read a key the route has never returned — and its test encoded the bug — `Defect`

`GET /platform/flows/registry` returns `{flow_definitions, nodes, flow_count, node_count}`.
`RegistryPanel` read `registry.flows`, so `Object.keys(registry.flows)` threw
`Cannot convert undefined or null to object` on every load.

**The notable part is the test.** A unit test covering this exact panel was **passing**, because
its fixture mocked a `flows` key the API never produces — written to match the component rather
than the route. The test documented the bug and locked it in.

This is a distinct failure mode from the rest of the walk. Items 12/14/19/22 were *untested*
paths; this one was tested *wrongly*, which is worse — it produces false confidence. **A green
test proves the component matches its fixture, not that the fixture matches the API.** Worth
carrying through the remaining panels.

Each tab panel also gained its own `ErrorBoundary` keyed on the active tab: previously every tab
shared one route-level boundary, so a single panel throwing during render blanked the entire
console until a full reload.

**Status:** fixed in #159.

---

### 27. Strategies panel crashes on a null score — `Defect`

**Correction to the previous entry's diagnosis.** Strategies was initially assessed as collateral
damage from the shared error boundary, on the grounds that its payload matched what
`StrategyCard` expects. That was wrong — with panels isolated, Strategies still failed. It is its
own defect.

**Cause:** `ScoreBar` renders `{score.toFixed(2)}` with no null guard, and both live strategies
carry `score: null`:

```
id: 'default'  intent_type: 'default'  user_id: None  score: None
usage_count: 0  success_count: 0  flow: {'handler': 'select_strategy', 'type': 'default'}
```

→ `TypeError: Cannot read properties of null (reading 'toFixed')`.

Everything else in the component tolerates the null: `Math.min(100, null / 2.0 * 100)` is `0`, and
both comparisons fall through to the "failed" colour. Only the label throws.

Note the shape of it — the seeded `default` system strategies exist precisely so the panel has
something to show before any learning has happened, and they are exactly the rows that crash it.
The empty state is unreachable for the opposite reason: `strategies.length` is 2, not 0.

**Fixed:** the label renders `—` when there is no score, the bar width clamps to 0, and an
unscored strategy gets a neutral colour rather than the red used for a genuinely low score —
"never scored" and "scored badly" are different states and should not look identical. Regression
test added covering a strategy with `score: null`.

**Status:** fixed.

---

### 28. Client error telemetry has never worked — `Defect`

Seen in the console alongside every boundary trip:

```
POST http://localhost:5173/client/error 404 (Not Found)
```

`reportClientError` (`client/src/api/operator.js`) POSTs to `ROUTES.OPERATOR.CLIENT_ERROR`, which
no backend route serves. The call is wrapped in `.catch(() => {})`, so it can never break the
page — and equally can never report. Every client-side crash during this entire walk was
swallowed.

Two possible reads, and the choice matters: either the route belongs in the runtime and is
missing (making this a runtime feature request), or the client should stop pretending to report
and the call should be removed. Silently 404-ing on every crash is the one option that helps
nobody.

**Status: ✅ RESOLVED upstream.** The runtime now serves the route — re-probed 2026-08-05,
`POST /client/error` returns **204** where it previously 404'd, and the client already posts
there (`ROUTES.OPERATOR.CLIENT_ERROR` → `/client/error`). Client-side crashes are reported
rather than swallowed. No app change was needed; the first of the two possible reads turned out
to be right.

---

### 29. The platform UI is a record, not a control plane — `Design`

**Observed (owner), on finishing the Flow Engine console:** the operator surface reads as a
*record* of what happened rather than a place to *act*. Noted as a possible upgrade, not a fault.

**The code agrees, and the gap is measurable.** The `/platform` API exposes **59 operations
across 51 routes: 35 read, 24 write**. The platform UI wires **5** of those 24:

| Wired | Where |
|---|---|
| `POST /flows/runs/{id}/resume` | FlowEngineConsole — resume a waiting run |
| `POST` automation replay | FlowEngineConsole — single row, and a bulk "replay all failed" |
| approve / reject agent run | AgentApprovalInbox, AgentConsole |
| create agent run | AgentConsole |

**Not reachable from any UI (19 of 24):**

```
POST   /platform/flows/{name}/run          run a flow on demand
POST   /platform/syscall                   dispatch a syscall
POST   /platform/flows                     DELETE /platform/flows/{name}
POST   /platform/nodes/register            DELETE /platform/nodes/{name}
POST   /platform/admin/agents/register     DELETE /platform/admin/agents/{namespace}
POST   /platform/admin/users/{id}/promote
POST   /platform/keys                      DELETE /platform/keys/{key_id}
POST   /platform/observability/queue/dlq/drain
POST   /platform/queue/dead-letters/drain
POST   /platform/queue/dead-letters/{id}/replay
DELETE /platform/queue/dead-letters/{id}
POST   /platform/nodus/upload | /run | /flow | /schedule
DELETE /platform/nodus/schedule/{job_id}
POST   /platform/webhooks                  DELETE /platform/webhooks/{subscription_id}
POST   /platform/ops/rotate-secret-key
```

**Write actions per panel** — the split is stark:

| Panel | Actions |
|---|---|
| FlowEngineConsole | 2 (resume, replay) |
| AgentApprovalInbox / AgentConsole / AgentRegistry | approve, reject, create run |
| **ExecutionConsole** | **0** |
| **HealthDashboard** | **0** |
| **ObservabilityDashboard** | **0** |
| **RippleTraceViewer** | **0** |

Four of the seven panels are pure read.

**Why this is the same theme as the product walk, not a new one.** Every earlier design note came
down to *working backends, underspecified presentation*. This is that pattern at the operator
layer: the control capability is fully built and routed — it simply has no surface. The
`admin/users/{id}/promote` case makes it concrete: making the first admin for this walk required
a direct `UPDATE users SET is_admin` in Postgres, because the only route that does it is
admin-gated and has no UI, so there is no bootstrap path from a running system.

**Cheapest upgrades, if pursued** — ordered by value per unit of work:

1. **Dead-letter actions.** `ObservabilityDashboard` already reads the DLQ; replay / drain /
   delete are three buttons on data it is already showing. This is the highest-value gap: a
   dead-letter you can see but not act on is precisely a record where a control plane is wanted.
2. **`POST /flows/{name}/run`.** The Registry panel already lists every registered flow. A "run"
   button next to each turns an inventory into an operator tool.
3. **Admin promotion.** Removes the "edit the database to create your first admin" bootstrap.
4. **Nodus + node/agent registration.** Larger surface, real UI design needed; not a button.

`POST /platform/syscall` is deliberately left off that list — arbitrary syscall dispatch from a
browser is a different risk class and wants an explicit decision, not a convenience button.

**Status:** ✅ CLOSED (2026-07-31) — every write route that is *appropriate to expose as an
operator action* is now wired; what remains is design work, not wiring, and is captured as
follow-ups below. Delivered across two merged PRs (#169 phase 1, #170 phase 2).

**Phase 1 (merged #169)** — the three cheapest upgrades: **(1)** dead-letter Replay / Delete /
Drain (new DLQ panel on Observability), **(2)** run-a-flow-on-demand (Run button per FlowCard in
the Registry), **(3)** admin promotion (new `/platform/users` panel — closes the "edit the DB to
make a second admin" gap; the *first* admin still needs a DB bootstrap → FR-6). All actions
confirm-gated.

**Phase 2 (2026-07-31, branch `feat/platform-control-plane-phase2`):** **Webhooks** — new
`/platform/webhooks` panel, full list/create/delete CRUD over the previously-unwired webhook
routes (operator-created subscriptions use `owner_class=first-party-app`; external-third-party
would require declared provenance).

**Intentionally not built — design decisions, tracked as follow-ups (why item 29 is CLOSED, not
incomplete):**
- **Agent register/delete** — needs a design decision, not a button. The `/registry` panel
  (`AgentRegistry`) lists *memory-namespace* agents via `/apps/memory/agents`, but the
  register/delete routes are `/platform/admin/agents` — a **different agent concept**. Wiring
  actions onto that panel would act on a different entity than the one shown. Requires
  reconciling the two agent surfaces (or a separate "Admin Agents" panel) first.
- **Node registration** — not a browser-appropriate surface: `POST /nodes/register` needs a
  `handler` (deployed code reference) and there is no list route (only `GET /nodes/{name}`).
- **Nodus** (upload / run / flow / schedule) — bigger; schedule mgmt (cron + script picker) is
  the tractable slice for a future pass.
- **`POST /platform/syscall`** — deliberately excluded (different risk class).

### 30. The platform SPA had no navigation — `Defect`

**Observed:** "Agent Registry, Approval Inbox, Observability, Health, Execution Console,
RippleTrace don't show at all."

**Cause:** they were never missing — they were unreachable. `PlatformApp.tsx` registers **eight**
routes (`/agent`, `/flows`, `/observability`, `/health`, `/executions`, `/approvals`, `/registry`,
`/trace`), and the app rendered **no links between them**. A grep for `NavLink` or `<nav>` across
`client/src/components/platform/` returned nothing.

`/platform/flows` was reachable only because the product app's "Open platform" button happens to
land there. Every other panel could be reached only by typing its URL. All eight are real: their
backing endpoints return 200 (`/platform/observability/dashboard`, `/platform/admin/agents`,
`/platform/observability/system`, `/platform/observability/rippletrace/status`).

This is the plainest instance yet of the theme running through the whole walk — built backend,
built panel, no way in.

**Fixed:** added `PlatformNav`, a sticky bar linking all eight routes with active-state styling
plus a "Back to app" link. It renders **inside** `PlatformGuard` (so a non-admin never sees it)
but **outside** the route error boundary, so a panel that throws still leaves the operator a way
to navigate off it — which, before the per-panel boundaries landed in #159, was the difference
between a broken tab and a dead console.

Test asserts the link set matches the registered routes exactly, that the current route is marked
`aria-current`, and that the escape hatch back to the product app exists.

---

### 31. Agent Console crashed on the wrapped agent reads — `Defect`

**Observed:** `TypeError: runs.filter is not a function` at `AgentConsole.jsx:605`.

**Cause:** several `/apps/agent` read routes wrap their payload as `{data: [...]}` and
`client/src/api/agent.js` had **no** `unwrapEnvelope`. `loadRuns` did `setRuns(data || [])` —
which happily stored `{data: []}`, since an object is truthy — and the very next render called
`runs.filter(...)`.

Probed live to find which routes wrap and which do not, rather than applying the unwrap blindly:

| Route | Shape | Unwrap |
|---|---|---|
| `/apps/agent/runs` | `{data: [...]}` | yes |
| `/apps/agent/tools` | `{data: [...]}` | yes |
| `/apps/agent/suggestions` | `{data: [...]}` | yes |
| `/apps/agent/trust` | bare object | no — already flat |
| `/apps/memory/agents` | `{agents, total}` | no |

**Fifth instance of item 13**, after social (12), tasks (14), ARM (19) and identity (22) — and the
third distinct *shape* of it: a missing unwrap (12), a collection nested under a named key (14),
and now a partial envelope carrying only `data` with no `status` alongside it.

`AgentConsole`''s three list loaders were also normalised with `Array.isArray(...)`, so a shape
surprise renders an empty list instead of taking the console down. `data || []` does not protect
against this — every object passes it.

**Status:** fixed.

---

### 32. The Executions tab is app content on the operator surface — `Defect`

**Observed (owner):** the Executions tab looks like a section that shouldn''t be there — it appears
to show manual inputs for the Infinity algorithm that a human fills in and calculates, rather than
executions being run. Suspected to be something missed in the runtime/app split.

**Confirmed, and it is app-owned — not a ui-kit or runtime concern.**
`client/src/components/platform/ExecutionConsole.jsx` lives in *this* repo, and
`@aindy/ui-kit` ships no `ExecutionConsole` at all (grep of the built bundle: 0 hits). That is why
it was not visible when looking at the runtime''s frontend — it was never there. Nothing needs to
go back to the runtime repo; the fix is entirely app-side.

**What it actually is:** the component imports **13 panels from `../app/`** and calls
**zero `/platform` routes**. Its only API call is `calculateTwr`, an app analytics route.

```
Engagement · AIEfficiency · Impact · RevenueScaling · ExecutionSpeed · AttentionValue
IncomeEfficiency · MonetizationEfficiency · BusinessGrowth · EngagementRate
AIProductivityBoost · DecisionEfficiency · LostPotential
```

**The part that makes this more than misfiling — 7 of the 13 are reachable *only* here:**

```
EngagementPanel · AIEfficiencyPanel · RevenueScalingPanel · BusinessGrowthPanel
AIProductivityBoostPanel · DecisionEfficiencyPanel · LostPotentialPanel
```

The other six are also on `/kpi` via `KPIDashboard`. So seven app-domain calculators are
**admin-gated and stranded on the operator surface** — a normal user cannot reach them at all,
and an operator finds them where executions should be.

**And there is no execution console.** The tab named "Executions" shows none. The data a real one
would use exists and is already routed: `/platform/flows/runs`,
`/platform/observability/execution_graph/{trace_id}`, `/platform/observability/requests`,
plus the execution-unit records every pipeline route emits.

**Relationship to item 18.** The owner already flagged `/kpi` as "a manual calculator that was
meant to be a dashboard". This is the same content, duplicated onto the platform side — so the
KPI decision and this one should be made together rather than separately.

**Three options:**

| # | Option | Notes |
|---|---|---|
| A | Move all 13 panels to the app KPI surface; delete the platform tab | Un-strands the 7, makes `/kpi` whole, removes a tab that shows nothing it claims to |
| B | Move the panels **and** build a real execution console in the freed tab | Same as A plus an operator surface over `flows/runs` + `execution_graph` — the routes already exist (see item 29) |
| C | Delete the 7 exclusive panels outright | Only if the manual-calculator model is being dropped, which the item 18 decision may settle |

A is strictly better than leaving it; B is A plus the control-plane work already scoped in item 29.

**Status:** ✅ RESOLVED via **option B** (owner, 2026-07-31), on `feat/kpi-scores-dashboard`. The
13 app calculators moved to a new app-side `/tools` drawer (3 name-colliders deleted — `/kpi` now
computes real system-fed versions); the freed Executions tab was rebuilt into a real execution
console over `flows/runs` + `observability/execution_graph`. See
`docs/archive/KPI_DASHBOARD_WIRING.md`.

---

### 33. Every response carries two trace ids — `Defect`

Found running the Phase 2b trace-continuity check. A single `POST /apps/tasks/create` returns:

```
X-Trace-ID header : 67b4230a-2205-49fa-8e7c-a848629853e2
data.trace_id     : 67b4230a-2205-49fa-8e7c-a848629853e2   ← same as the header
envelope trace_id : cd21cbf0-29f0-4287-b88a-bd5c32aadf3f   ← different
```

Both resolve — and to **different graphs**:

| Trace id | `execution_graph` entries |
|---|---|
| header / `data.trace_id` | **12** |
| envelope `trace_id` | **2** |

So the header and the inner payload agree and point at the real work; the envelope's top-level
`trace_id` is the outer pipeline wrapper's own trace and resolves to a nearly empty graph.

**Trace continuity itself passes** — `X-Trace-ID` is observable and matches a platform
observability record, which is what the scope document asks for. The defect is that the response
body offers a *second*, more prominent id that silently leads somewhere thinner. Anyone debugging
from a copied response — the obvious thing to do — gets the 2-node graph and concludes the tracing
is broken.

**Fix is naming, not plumbing:** the outer id wants a distinct key (`pipeline_trace_id`, say) so
the two are not interchangeable-looking, or the envelope should echo the work trace.

**Status:** diagnosed, unfixed. Runtime-owned (the envelope is built by
`execute_with_pipeline`), so this is a runtime discussion rather than an app fix.

---

### 34. Scheduler status reports health but no jobs — `Gap`

`GET /platform/observability/scheduler/status` returns:

```json
{"scheduler_running": true, "is_leader": true,
 "lease": {"owner_id": "0c2f54ad3877",
           "acquired_at": "2026-07-23T03:16:44Z",
           "heartbeat_at": "2026-07-23T05:09:44Z",
           "expires_at":  "2026-07-23T05:11:44Z"},
 "tasks_domain_available": true}
```

**Liveness passes.** The lease heartbeat is current and advancing, which is itself proof that at
least one scheduled job (`background_lease_heartbeat`, 60s) is executing.

**But there is no job inventory.** `apps/tasks/bootstrap.py` registers five scheduled jobs —
`task_reminder_check` (1m), `task_recurrence_check` (6h), `background_lease_heartbeat` (60s),
`wait_recovery_poll` (60s), `resume_watchdog` — and none of them are visible from the operator
surface. There is no way to answer "is the recurrence check actually scheduled?" without reading
the source.

**Correction to an earlier note in this walk:** a previous probe reported `jobs: 0`. That was an
artefact of the probe defaulting a missing key — the payload has no `jobs` field at all. The
scheduler was never reporting zero jobs; it reports none.

**Status:** diagnosed, unfixed. A `jobs` array with id / trigger / next-run-time is the natural
addition, and it is the single piece that would make Health a real operator surface.

---

## Resolved during this walk

| Area | Item | PR |
|---|---|---|
| identity | Signup initialization never ran — no account was ever provisioned | #131 |
| client | Dev proxy stripped `/api`, 404ing `/api/version` | #132 |
| client | App routes missing the `/apps` mount — 90 of 101 routes 404ing | #133 |
| client | No scrollbar anywhere: `body{overflow:hidden}` + unbounded shell height | #133 |
| client | Freelance dashboard treated its empty state as a hard error | #133 |
| client | A tripped route error boundary poisoned every subsequent page | #133 |
| genesis | Leaving the page abandoned the session; now resumes the active one | #135 |
| dashboard | Score-history sparkline crashed the panel (undefined `score_delta`) | #139 |
| assistant | Agent run looked stuck at "planning" — response-shape mismatch | #140 |
| search | Research query 500'd — `@limiter.limit` grabbed a Pydantic body named `request` | #141 |
| dashboard | Graph tab bounced to Overview — `/dashboard/graph` route was missing | #144 |
| rippletrace | Graph tab logged the user out — GraphView hit api-key-gated routes | #145 |
| seo/leadgen | "Recent …" panels didn't refresh after a run; meta description too long | #147/#148 |
| social | Posts didn't appear — Mongo overlay + ObjectId-500 fix + honest 503 degrade | #149 |
| social | Feed rendered nothing and analytics read all zeros — `social.js` never unwrapped the envelope | #150 |
| tasks | Created tasks never appeared — the list array is nested under `data.tasks` | #151 |
| arm | Analyze rendered a blank screen on failure; the default path could never resolve | #152 |
| identity | Every dimension card rendered blank — `identity.js` never unwrapped the envelope | #154 |
| tasks | Create form could not set estimated hours or a MasterPlan — Volume axis was always 0 | #157 |
| compose | Shadow flags set in `.env` never reached the container | #156 |
| platform | Dev proxy swallowed every `/platform` API call — no panel could load data | #158 |
| platform | Registry read `registry.flows`; route returns `flow_definitions`. Panels now fail in isolation | #159 |
| platform | Strategies crashed on the seeded `default` strategies — `score.toFixed(2)` on a null score | #161 |
| platform | No navigation existed — 7 of 8 panels were reachable only by typing a URL | #163 |
| platform | Agent Console crashed — `agent.js` never unwrapped the `{data: …}` reads | (this PR) |

**Upstream:** the `/apps` mount omission belongs in `@aindy/ui-kit`; corrected app-side in
`client/src/api/_routes.js` and logged against `UIKIT-ROUTE-DRIFT-1`. The 401-logs-out-everything
behavior (open item 8) is also a `@aindy/ui-kit` request-core concern.

---

## Closed after the walk (2026-07-23 → 2026-08-05)

The table above stops at #163, which was the last PR of the walk itself. These closed
afterwards, verified against the code and the live stack on 2026-08-05 rather than taken from
the PR titles.

| Item | Resolution | PR |
|---|---|---|
| 31 — Agent Console crashed on wrapped agent reads | envelope unwrapped | #164 |
| 18 — Analytics/KPI showed dead manual formulas | `/kpi` rewired onto the live Infinity score engine; Manual Tools moved to `/tools`; collider panels deleted | #168 |
| 29 — the platform UI is a record, not a control plane | DLQ actions, run-flow, admin promotion, webhooks CRUD. Agent/node/nodus control deliberately deferred as design decisions | #169, #170, #171 |
| 34 — `/apps/compute/create_masterplan` could never succeed | repaired, with the analytics rewire | #172 |
| 16 — the only non-Genesis MasterPlan create route 500s | same fix | #172 |
| 3 — a 4xx raised before pipeline entry became an opaque 500 | swept every managed route and **guarded it in CI** (`scripts/check_route_pipeline_contract.py`) | #182 |
| 6 — no import/upload path for an existing plan | free-text import, structured by the LLM, seeded as the opening Genesis exchange | #183 |
| 20 — ARM has no project-root confinement | containment check; see the item above | #194 |
| 28 — client error telemetry has never worked | runtime now serves `/client/error`; no app change needed | upstream |

Also closed in the same window, outside the walk's numbering: the `bridge` domain retired into
`apps/memory` (#185), `network_bridge` finally wired to the sign-in event it was built for
(#184), rippletrace given a real data supply (#177, #178), runtime 2.0.0 and 2.0.1 adopted
(#188, #190, #192) with password recovery UI (#189), and four dead-twin duplicates removed
(#195).

## Still open

**Decisions, not defects** — these need the owner, not a fix:

- **17** — MasterPlan / Genesis / Assistant / Tasks want to be one section.
- **19** — what ARM Analyze is *for*: an internal dev tool pointed at A.I.N.D.Y.'s own source,
  or a product surface that would need upload or a repo connection.
- **23** — the five Identity decisions (rename, feed the inference engine, surface the verdicts,
  fold into the assistant, and "memory needs no rework — judge other surfaces against it").
- **10** — the social feed reads bare on first look.

**Diagnosed, unfixed, runtime-owned:**

- **8** — a 401 on any request logs the whole session out. Confirmed still present in the
  `@aindy/ui-kit` 1.0.6 request core, which dispatches `aindy:session-expired` on every 401.
- **33** — every response carries two trace ids resolving to different graphs. The fix is
  naming (`pipeline_trace_id`), and the envelope is runtime-built.
- **34** — scheduler status reports health but lists no jobs.
