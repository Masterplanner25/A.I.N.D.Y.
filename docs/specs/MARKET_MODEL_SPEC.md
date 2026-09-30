---
title: "The Market Model — who your work is for, and where they are"
last_verified: "2026-09-30"
api_version: "1.0"
status: draft
owner: "app-team"
---

# The Market model — who your work is for, and where they are

**Status:** phase A BUILT 2026-09-28 (owner took §9 decisions 1–4 as recommended); phase B BUILT
2026-09-30 (§5.6). **Lead-finding PARKED 2026-09-30 as data-limited, by the owner (§8.1)**; C not
started, and waits on outreach that phase B's leads may never produce. Written 2026-09-28, the day the agent's lead search first worked end to end and returned
three results that were not leads.

**The owner, which is the whole spec:**

> *"The problem is where are we looking … hmm, maybe we aren't searching for leads — maybe we're
> searching or defining the market?"*

The companion to `WORK_MODEL_SPEC.md`. That spec gave the system **what you have made**. This one
gives it **who that is for**: the buyer, what they call the problem, what else they would choose, and
where they can be found. Lead search is a search *inside* a market. It cannot define one.

---

## 0. What happened, and what it showed

Run `8b75d75d` (*"Plan how to market A.I.N.D.Y. as a platform"*) was the first where `leadgen.search`
did everything it is meant to (#424, #425): scored, saved, each lead with its own context. It saved:

| Saved as a lead | What it is | What it is actually worth |
|---|---|---|
| **Onereach** (81) | a *"top 10 AI agent platforms"* post on a vendor's blog | the **competitive set** as the market sees it |
| **Futurumgroup** (80) | an analyst firm's piece on *AgentOps* | a **name for the category**, and a claim about where it is heading |
| **Crn** (75) | a trade-press story; the company in it is **AHEAD** | a **channel**: solution providers building AI practices, who resell and integrate |

Not one is a buyer, and every one is market-definition material. The search did not fail. It was
asked a market question (*"companies and teams building AI agents …"*) by a run whose goal was a market
question (*"plan how to market …"*), and the only tool whose name sounded like the answer was
`leadgen.search`, so the answer was filed as leads.

---

## 1. What the system holds about the market today — audited 2026-09-28

| Where | What it holds |
|---|---|
| **Works** (#420) | 7 confirmed: Nodus, aindy-runtime, A.I.N.D.Y., the companion packages, the two series, AI Search Optimization. **What you made; nothing about who it is for** |
| **MasterPlan** | objectives (*Ethical AI Framework, Partnership Development, Platform Enablement*) and strategies (*Establish Authority*, …). Aims, not audiences |
| **`leadgen_results`** | 4 rows: a 2026-09-16 test row (*Acme Robotics*, `acme.example`) and the three above |
| **`search_history`** | 6 queries, 2026-09-25 → 09-28, from the agent's marketing runs, **all asking the same market question in different words**: *"AI runtime … competitor positioning"*, *"AI-native developer tool go-to-market"*, *"developers and engineering teams building AI agents"* … Each run started from nothing |
| **Memory** | 4 `agent_findings` nodes from those runs: research prose, unstructured, recalled by similarity or not at all |
| **Freelance** | `freelance_service_prices` 0 rows, `freelance_client_accounts` 0. The system does not know what you sell or to whom you have sold it |
| **The lead scorer** | `score_lead`'s prompt: *"an expert B2B analyst who scores potential leads for **AI consulting services**"*. A fixed brief that matches none of the 7 Works, and never asks whether a result is a buyer at all |
| **The web search** | `research_engine.web_search` sends `{"query", "max_results": 10}` to Perplexity and nothing else, so the whole open web, at any age |
| **"Segment" in `leadgen.act`** | the learning close's auto-suppress keys a *segment* by **the lead's `query` string** (`lead_execution_service.py`, `SUPPRESS_MIN_OUTCOMES = 3`). Agent queries are reworded every run, so no segment can ever accumulate three outcomes. **The only segment concept in the system is one that cannot learn** |

**Nowhere in the system is there a row that says *"platform teams whose agent pilots will not reach
production are a market for aindy-runtime, they call it AgentOps, and they also consider Onereach."*** That is
the gap.

---

## 2. What is missing is not research. It is somewhere to put it

The marketing runs since 09-25 did market research. It is all somewhere (search history, memory prose, three misfiled
leads) and none of it accumulates, because there is no model for it to accumulate *into*. Each run
re-asks the question, and the answer is scattered again.

The Work model solved the same problem for the owner's own work, and the same shape fits here, with
one difference that matters: **a Work is a fact; a market is a bet.** *"I made Nodus"* is true or false
and the owner knows which. *"Platform teams are a market for aindy-runtime"* is a hypothesis that
evidence strengthens or kills. The model has to carry that status, and the evidence behind it.

---

## 3. The model

Owned by **masterplan**, beside Works (decision 1, §9). A market is *who the plan's work is for*.
Search reads it through a registered `get_job`, as masterplan reads RippleTrace's containers
(`rippletrace.confirmed_containers`), so no cross-domain import is added.

### 3.1 A Segment — the unit

`market_segments`:

| Column | Notes |
|---|---|
| `id`, `user_id` | as Works |
| `name` | the owner's name: *"Platform teams shipping agents"*, *"Brands losing AI-answer visibility"* |
| `buyer` | who decides, and in what kind of organisation: *"head of platform / AI eng, 50–500-person software company"* |
| `problem` | the problem **in the buyer's words**, not the product's: *"our agent pilots work in demos and fall over in production"* |
| `trigger` | what makes them look now: *"a failed pilot"*, *"traffic from AI answers dropped"*. Optional |
| `category_terms` | what the buyer calls the thing they would buy: `["AgentOps", "agent orchestration", "agent runtime"]`. **The search vocabulary** (§5) |
| `status` | `hypothesis` · `testing` · `validated` · `abandoned`. A bet, stated as one |
| `provenance` | `declared` · `confirmed` (proposed by the system, accepted by the owner) |
| `created_at` / `updated_at` | with revisions kept, as `work_revisions` |

`segment_works` (`segment_id`, `work_id`, `note`): **which of your works serves this segment.**
aindy-runtime and Nodus serve *Platform teams*; AI Search Optimization serves *Brands losing
AI-answer visibility*. This is the join the lead scorer is missing (§5.3).

### 3.2 Market entities — what surrounds the buyer

`market_entities`: `id`, `user_id`, `segment_id` (nullable: a competitor can span segments), `kind`,
`name`, `url`, `note`, `provenance`.

| `kind` | reads as | from run 8b75d75d |
|---|---|---|
| `alternative` | what the buyer would choose instead, **including "build it themselves" and "do nothing"** | Onereach, and the other nine on its list |
| `channel` | where the buyer gathers or looks: a forum, a job board, a publication, an event | CRN as a publication read by solution providers |
| `intermediary` | who sells, integrates or recommends to the buyer | AHEAD, and solution providers as a class |
| `voice` | who shapes how the buyer thinks: analysts, newsletters, practitioners | Futurum Group |
| `exemplar` | a named organisation that fits the segment: evidence the segment is real, and the seed of a lead | none yet |

Closed vocabulary on purpose, for the same reason as `work_links.relation`: five kinds are what the
three results above needed, and a free-text kind is a label nothing can reason over.

`intermediary` maps onto an objective the plan already has: **Partnership Development**. That is the
first place this model and the strategy layer touch.

### 3.3 Evidence — why a bet is believed

`market_evidence`: `id`, `segment_id` or `entity_id`, `claim` (one sentence), `source_url`,
`source_kind` (`research` · `lead_outcome` · `owner`), `run_id` (nullable), `stance` (`supports` ·
`contradicts`), `captured_at`.

*"Gartner projects …, orchestration is now the main decision factor"* (the Onereach snippet) supports
the category term. A segment's status moves on evidence the owner can read, not on a count the
system computes (§6). `lead_outcome` evidence is how the real outcome, a converted or ignored
outreach, reaches the bet (§5.4).

---

## 4. How it is filled: proposed, then confirmed

The Work rule without exception: **nothing reaches the agent until the owner confirms it**, dismissals
are kept, and no cold forms.

1. **Seed proposals from what already exists** (no fetching, no model calls):
   - the three saved "leads" become three **entity proposals** with their evidence, and are then
     removed from `leadgen_results` once answered (§8, phase A). *As built: every saved lead with no
     outreach is asked about; confirming re-files it and retires the lead, dismissing leaves it a lead;*
   - `search_history`'s six queries become **one segment proposal** each for the two buyers they
     circle (*platform/AI engineering teams*; *brands and AI-visibility buyers*), with the queries as
     `research` evidence. *Built 2026-09-28 as two proposals recorded once through `market.propose`'s
     own path, not as code: grouping free-text queries into buyers needs judgement, and a rule
     written for six queries would be a rule about this owner's data;*
   - each confirmed Work with no segment asks *"who is this for?"*, the question the Work panel
     never asked.
2. **The agent proposes; it never confirms.** A new tool, **`market.propose`**, writes proposals only:
   `{kind, name, segment?, url?, note, evidence[{claim, source_url}]}`. A research run that learns a
   competitor's name records it here instead of into memory prose or `leadgen_results`. Under
   `enforce` validation its `args_schema` must be right before it ships.
3. **The owner answers in Collaborator**, a **Market** mode beside Work: confirm, edit or dismiss each
   card, the WorkPanel pattern. One screen shows each segment with its works, alternatives, channels
   and evidence, so the owner sees the bet whole.

---

## 5. Lead search becomes a search inside a segment

This is where the owner's question, *where are we looking*, is answered.

### 5.1 Where: the segment's channels, verified against the provider

Perplexity's Search API (checked against its reference, 2026-09-28) takes parameters we send none of:

| Parameter | Use |
|---|---|
| `search_domain_filter` (≤ 20 domains) | the segment's `channel` entities, e.g. job boards, `news.ycombinator.com`, `github.com`, subreddits |
| `search_recency_filter` (`day`…`year`) | `month` for leads. A posting or a question from last year is not a lead |
| `search_type: "people"` | a named person in the buyer role, not a company homepage |
| `country`, `search_language_filter` | if a segment is regional |

Same provider, same key, same call count. **To verify before building:** that a domain filter on a
job board returns postings rather than the board's own marketing pages, and how `people` results are
shaped.

### 5.2 What: the buyer's words, not a topic

The query is built from the segment (`problem` + `category_terms` + `buyer`), not from the planner's
paraphrase of the goal. A topic query returns articles *about* the topic; a query in the buyer's own
words, on the channels the buyer uses, returns the buyer.

### 5.3 Is it a buyer: judged against your work, not a fixed brief

`score_lead` gains two changes, still one gpt-4o-mini call per result:

- **Classify first.** *Is this result a prospective buyer in this segment?* If it is a listicle, a
  publisher, an analyst or a competitor, it is **not saved as a lead**. It becomes a `market.propose`
  entity proposal of the matching kind (the misfile of run `8b75d75d`, routed correctly). When the
  buyer is named inside someone else's page (AHEAD inside CRN), the lead is **the named organisation**.
- **Fit against the segment and its works.** The fixed *"AI consulting services"* brief is replaced by
  the segment's buyer and problem and the linked Works' summaries, the owner's own words.

### 5.4 The learning close gets a real segment

`leadgen_results.segment_id` (nullable). `leadgen.act`'s auto-suppress keys on it instead of on the
query string, so outcomes finally accumulate: three ignored outreaches to *Platform teams* suppress
that segment regardless of how each query was worded. A converted or ignored outreach is written as
`lead_outcome` evidence on the segment (§3.3), so the bet is judged by what happened, not by how
confident the research sounded.

### 5.5 The tools, as the planner sees them

- `leadgen.search` gains `segment_id`. Its description says it finds **buyers inside a confirmed
  segment**, and that market questions belong to `research.query` + `market.propose`.
- `market.propose` is described as the place research findings about competitors, channels and
  category names go.

### 5.6 As built, 2026-09-30

**§5.1's verifications, run first** against the real provider with the platform-teams segment's words:

| Search | What came back |
|---|---|
| Open web, last month | listicles (*"Best AI Agent Platforms 2026"*, *"10 best orchestration platforms"*) |
| **Job boards** (Greenhouse, Lever, Ashby), last month | **companies hiring for the problem**: Similarweb, OpenTeams, EarnIn, AmTech Software, Firmus. The employer is in the title or the address |
| HN, Reddit, GitHub, last month | GitHub repos of self-hosted agent runtimes: alternatives and voices |
| `search_type: people` | LinkedIn profiles of named people in the role |

So `where` is `hiring` by default (job boards), `channels` (the segment's confirmed `channel`
entries, refused when it has none) or `web`. **People search is not built:** saving named
individuals as leads is the owner's call, not a default.

- `research_engine.web_search_results` sends `search_domain_filter` and `search_recency_filter`.
- `segment_search.segment_lead_search`: the segment (through `masterplan.segment_brief`), a query in its
  words, one `gpt-4o-mini` judgement per result against the segment and its works (buyer or not; if
  not, which kind of entry). Buyers are saved with `leadgen_results.segment_id` (`sg1leadseg0001`) and
  deduplicated by url; non-buyers go to `masterplan.market_propose`, source `lead_search`.
- `leadgen.search` (the agent tool): with `segment`, the search above; without one, a plain web search
  that saves nothing (§9 decision 4). `POST /apps/leadgen/segment-search`, and **Find buyers** on each
  segment in Collaborator's Market mode.
- Auto-suppress groups outcomes by `segment:<id>` when a lead has one, by query otherwise.

**The judge, reworked the same day.** The first prompt asked for the verdict and called hiring for the
problem "strong buyer evidence"; on job boards every result is, so the owner's first two searches saved
13 of 13 at 80–90, including Vercel (building its own workflow product), OneTrust (a governance vendor),
two digital agencies, and an agency under *regulated enterprise*. Now the model reports facts
(`org_type`: end_user · vendor · agency · publisher · other; `matches_buyer`, including the buyer's
organisation type; `problem_evidence`) with anchored scores, and `classify` decides: only a matching
end user is a buyer; vendor → alternative, agency → intermediary, publisher → voice. The hiring query
also carries the buyer's kind of organisation, and each search re-judges the segment's saved leads it
did not return (≤ 20, none with outreach), so a lead saved by the old judge is re-filed.

**Then the judge's model and names.** On the owner's re-run, `gpt-4o-mini` at default temperature
flipped Superserve between vendor and buyer across runs, kept Robots and Pencils (an agency) as a buyer,
and proposed an anonymous posting as an organisation called "AI security company". The judge is now
`gpt-4o` at temperature 0 (`AINDY_SEGMENT_JUDGE_MODEL` overrides; about $0.10 per Find buyers press),
and an organisation must be named by the result itself (the model's name found in it and not a
description, or the job board's employer slug); otherwise the result is dropped as `unnamed`.

---

## 6. What the agent sees

A block beside the Work block, rendered on demand like `render_work_block`:

```
## Your market (confirmed by you)
- Platform teams shipping agents — HYPOTHESIS. Buyer: head of platform/AI eng, 50–500-person
  software co. Problem: "agent pilots don't survive production". Calls it: AgentOps, agent
  orchestration. Served by: aindy-runtime, Nodus. Alternatives: Onereach, build-it-themselves.
  Channels: HN, GitHub. Intermediaries: solution providers (e.g. AHEAD).
```

- **Confirmed entries only**, and **the status is always printed.** An agent told a hypothesis is a
  fact will plan as if it were one. *"HYPOTHESIS"* tells it the right next step is evidence, not outreach.
- **A budget**, as the Work block: capped lines, `validated` and `testing` segments first.
- **The block does not move a score.** Works' rule, `WORLDVIEW` decision 3: the market feeds the loop,
  never a KPI.

---

## 7. Boundaries

- **Works** are what you made; **segments** are who it is for. `segment_works` is the only join. A
  Work never gains a buyer column.
- **Strategy layer.** Strategies are *how* you pursue an objective; a segment is *whom* a strategy
  reaches. A strategy may name a segment later; not in this spec.
- **Search** keeps leads, outreach and the gate. It reads segments through a registered job and does
  not own them.
- **Freelance** prices and client accounts are what you *have* sold; a segment is who you *could* sell
  to. When freelance holds real clients, a client is `exemplar` evidence. Not wired here.
- **RippleTrace** stays yours-published. Whether your readers are a segment is a question for the
  owner, not an inference.

---

## 8. Rollout

| Phase | What | Fixes |
|---|---|---|
| **A** | `market_segments`, `segment_works`, `market_entities`, `market_evidence`; seed proposals (§4.1); the three misfiled rows proposed as entities, then removed from leads once answered; `market.propose`; the Market panel; the planner block | *"Every marketing run starts from zero."* No fetching, no new model calls |
| **B** | segment-scoped `leadgen.search` (§5.1–5.2, after its verifications); classify-then-score (§5.3); `leadgen_results.segment_id` and suppression by segment (§5.4) | *"Where are we looking."* Leads are buyers |
| **C** | `lead_outcome` evidence; status proposals (*"3 of 3 outreaches ignored, abandon this segment?"*), answered like phase-advance proposals | The bet is judged by what happened |

**A before B**, because B has nothing to search inside until a segment is confirmed, and because
until A exists B's non-buyer results have nowhere to go but back into `leadgen_results`.

**Until B ships** (recommended ahead of A, a one-line change): amend `leadgen.search`'s description to
say it returns web results, not verified buyers, so the planner stops reaching for it to answer
market questions.

### 8.1 Lead-finding parked: the ceiling is the data, not the code (2026-09-30)

> *"I think we've reached the limit of what's feasibly possible for us to build without say better
> data. Lead finding is a pretty hard thing to do in the first place but it gets a bit harder when
> the data is damn near impossible to find."* The owner, after the fourth round on phase B.

**Every round improved the judgement; none changed the input.** Four passes on the same two segments:

| Round | PR | What changed | What it showed |
|---|---|---|---|
| 1 | #431 | job boards, the segment's words, one judgement per result | 13 of 13 saved as buyers at 80–90, vendors and agencies included |
| 2 | #432 | the model reports facts, the code decides; re-judging saved leads | vendors and agencies re-filed; then too strict (an internal platform called a vendor), corrected |
| 3 | #433 | `gpt-4o` at temperature 0; organisations must be named by the result | consistent verdicts across runs; no invented names |
| — | — | the owner's observation | everything comes from job boards |

**Why more code will not move it.** A search provider returns what is publicly indexed, and the public
signal that an organisation would buy a self-hosted agent runtime is thin:

- **Job postings** (the one source §5.1 found that returns organisations with the problem) name a
  company, never a person, and mean the company has *chosen to build*. The hardest pitch there is.
- **Forums and engineering blogs** (§5.1's other sources, reachable through `where=channels` once a
  segment has confirmed channels) name people with the problem, but sparsely and unsystematically.
- **People search** returns named profiles; saving individuals as leads was never approved.

Commercial lead data (contact databases, intent data, tracked behaviour) comes from sources this system
does not have and should not imitate by scraping. Better prompts judge the same thin input better;
they cannot add to it.

**What stays, and is worth keeping:**

- **The market record** (phase A): two segments held as bets, their alternatives (Vercel, GitLab,
  OneTrust, Superserve, Backbase, Anthropic), a partner type (agencies), the voices shaping the
  category, all confirmed by the owner, in every planner context. Marketing runs no longer start from
  zero. That was §2's problem, and it is solved independently of lead quality.
- **The honest search** (phase B): *Find buyers* still runs, and no longer files an article or a vendor
  as a buyer. It stays available for an occasional look. It is not a pipeline.
- **The learning close keyed by segment** (§5.4): correct, and idle until outreach happens.

**Where buyers are more likely to come from is not search.** The owner has 214 published pieces on AI
Search Optimization and builds in public. For an author, buyers usually arrive from the work: a reader
of a series, someone who found the runtime's docs, a conversation that started from a piece. That is
the plan's own *Establish Authority* strategy, and its data is the owner's, not a provider's. The lever
there is `WORK_MODEL_SPEC` phase B (the published writing, recallable by the agent), not more lead search.

**Reopen when**, and only when, the input changes: a lead-data provider with contacts and consent, an
inbound source (form submissions, docs sign-ups, replies to published pieces) that names people who
came to the work, or real outreach outcomes for phase C to learn from. Until one of those exists, a
proposal to improve lead-finding is a proposal to judge the same thin data again.

---

## 9. Open decisions — the owner's

1. **Which domain owns the market?** Recommended: **masterplan**, beside Works, since a segment is
   *who the plan's work is for*. Alternative: **search**, which owns leads today, but then Works
   and segments live apart, and a segment would outlive nothing that search owns.
2. **Hypothesis status: yours to move, or proposed?** Recommended: **proposed by the system from
   evidence, moved only by you** (§8 C), the phase-advance pattern.
3. **Does the agent get `market.propose`, or is extraction automatic after a run?** Recommended: the
   **tool**. The agent knows while it is working what it has found; post-run extraction costs a
   model call per run and guesses.
4. **Does `leadgen.search` without a segment still run?** Recommended: **yes, as a plain web search,
   saved as nothing**. Its results come back for the run to read and propose from, and only a
   segment-scoped search saves leads.
5. **Your first segments.** The system can propose two from the six queries. Whether they are the
   right two, and whether the AI Search Optimization buyer is a business or an agency, only the owner
   knows.

---

## 10. What this spec does not claim

- It does not claim the owner has a market definition that was never entered. Defining the market
  is work, and the system should help do it, not wait for it.
- It does not claim the three results were bad research. They were good research, misfiled.
- It does not claim a domain filter will turn up buyers. §5.1's verifications come first, and B is
  built on what they show.
- It does not decide pricing, packaging or messaging. Those are downstream of a confirmed segment and
  belong to their own work.
