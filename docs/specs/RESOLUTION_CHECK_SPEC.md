---
title: "The Resolution Check — does AI search resolve your entities, correctly and connected"
last_verified: "2026-09-30"
api_version: "1.0"
status: draft
owner: "app-team"
---

# The Resolution Check — does AI search resolve your entities, correctly and connected

**Status:** phase A BUILT 2026-09-30 (owner took §7 decisions 1–4 as recommended, and added §2.2); phase B BUILT 2026-10-01 (§6.1); C not started. Scoped 2026-09-30 from the owner's own definition of success.

**The owner, which is the whole spec:**

> *"It's about how well you resolve. At the end of the day, what I do is basically knowledge, entity
> and semantic optimization. It's not necessarily about did I rank for x, y, z, and more so: if
> someone directly searches for Masterplan Infinite Weave, does it bring back the right entity. OK,
> what is it saying about the entity. How much can it say about the entity that's actually correct.
> Semantically, can it pick up on the connections between the entities: Shawn Knight and Masterplan
> Infinite Weave, Nodus, aindy-runtime. How well can it pick those connections up."*

That definition is now on the AI Search Optimization Work (`works.success_criteria`, #438) and in every
plan's context. This spec makes it **measured**: three numbers the owner defined, checked against the
facts the owner has already confirmed, tracked over time. Nobody's rankings.

---

## 1. Baseline — what the engines say today (measured 2026-09-30)

Probed read-only with the keys the stack already holds. Perplexity `sonar` answered four questions;
OpenAI (`gpt-4.1` + `web_search`, Responses API) and Claude (`claude-sonnet-5` + `web_search`) one each.
OpenAI's `gpt-4o-search-preview` is retired (404) and is not an option.

| Question | Right entity? | What it said | Connections |
|---|---|---|---|
| *What is Masterplan Infinite Weave?* (all three engines) | **yes, on all three** | Shawn Knight's AI-native ecosystem / execution framework / content network; founder named; Phoenix, Arizona; "an LLC in Arizona" (Perplexity) | → Shawn Knight (founder), → A.I.N.D.Y. |
| *Who is Shawn Knight, the creator of Masterplan Infinite Weave?* | yes | founder; "AI Search Optimization Specialist"; author of the 2025 ChatGPT Case Study Series; created A.I.N.D.Y.; notes transcripts spelling "Sean Knight" | → the series, → A.I.N.D.Y. |
| *What is aindy-runtime?* | yes | a self-hosted execution substrate beneath agents, workflows and apps; durable runs, capability tokens, memory; PyPI package | — |
| *How are Nodus and aindy-runtime related?* | **mixed** | correct: "aindy-runtime embeds Nodus; `nodus-lang` is a dependency". But it also cited **nodus.com** and **nodalninja.com**, other things named Nodus | Nodus ↔ aindy-runtime: **found** |

Three things this shows, before anything is built:

- **The brand resolves.** The hardest part of the owner's criterion (1) already holds on every engine.
- **Nodus has a disambiguation problem.** Answers about it pull in unrelated entities with the same
  name. That is exactly what criterion (1) is for, and the most actionable finding here.
- **Some claims only the owner can judge** ("an LLC in Arizona", the spelling in transcripts). A check
  needs a place for those, not just right/wrong.

---

## 2. What is checked: entities, facts, connections

The ground truth is what the owner has already **confirmed**. Nothing here is inferred.

- **Entities.** The owner's confirmed Works (7 today: Nodus, aindy-runtime, A.I.N.D.Y., the companion
  packages, the two series, AI Search Optimization), plus **two the Work model does not hold yet**:
  the owner as a person (*Shawn Knight*, aliases) and the brand (*Masterplan Infinite Weave*). Decision 1.
- **Facts.** Each entity's summary in the owner's words, and the owner's own published writing (199
  pieces, in memory since #435) as supporting evidence.
- **Connections.** The 7 confirmed `work_links` (aindy-runtime *built on* Nodus, A.I.N.D.Y. *built on*
  aindy-runtime, both series *demonstrate* AI Search Optimization, …), plus person→brand→works once
  those two entities exist.

### 2.1 The questions, generated from the model

| Kind | Asked | Measures |
|---|---|---|
| Direct | *"What is {entity}?"* per entity | criterion 1 (right entity) and 2 (what it says) |
| Person | *"Who is Shawn Knight?"* bare, and with context | criterion 1 for the hardest entity: a common name |
| Relation | *"How are {A} and {B} related?"* per confirmed link | criterion 3 (connections) |

Generated, not hand-written, so a new Work or link is checked from the next run without anyone
editing a list.

### 2.2 The owner's presence: a control, and connections (added by the owner, 2026-09-30)

> *"We don't need it to pull all the content from across the web, but we can use the content/sites as
> a control … LinkedIn has this as my header … Facebook has this … Medium … my point here is that these
> things are also connections."*

Each Work can carry its **presence**: the platforms it is on, the address, and its header or bio there in
the owner's words (`work_presence`, declared, never crawled). It does two jobs:

- **A control for accuracy.** A header is the owner's canonical statement about the entity. It becomes a
  confirmed fact the judge checks answers against ("On LinkedIn it describes itself: AI Search Optimization
  Specialist | Founder, Masterplan Infinite Weave …").
- **Connections.** A profile *is* the entity, elsewhere. Citations are matched against the owner's presence
  hosts (`own_sources_cited`), so a check shows which of the owner's own places an engine connects to the
  entity and which it never surfaces.

The check also shows the owner's self-descriptions **side by side**. For entity optimization, whether one's
own profiles say the same thing is itself part of the picture (on 2026-09-30, LinkedIn led with *AI Search
Optimization Specialist*, Facebook with *Helping you get found in AI Search*, Medium with *AI-powered
execution, systems thinking, and digital strategy*). Shown, not judged.

As built: Work kinds `person` and `brand`, and the relation `created`; a person is implicitly connected to
every Work whose role is creator or author. Judge: `gpt-4o` at temperature 0. Engines: Perplexity `sonar`,
OpenAI `gpt-4.1` + `web_search`, Claude + `web_search` (`AINDY_RESOLUTION_ENGINES` narrows them). A check
is answered six answers a minute by `masterplan_resolution_tick`.

---

## 3. How an answer is scored — the owner's three criteria, as numbers

Each answer is stored raw (text and citations, per engine), then judged by one model call against the
entity's confirmed facts. The judge reports facts; code computes the scores (the rule that fixed the
lead judge, `MARKET_MODEL_SPEC` §5.3).

| Criterion (owner's words) | Score | Computed from the judge's facts |
|---|---|---|
| *"Does it bring back the right entity"* | **Resolution** — resolved · mixed · wrong · unknown | whether the answer is about the owner's entity, another entity of the same name, or a blend (the Nodus case) |
| *"How much can it say about the entity that's actually correct"* | **Accuracy** — correct claims, incorrect claims, and *coverage* (how many of the entity's confirmed facts it stated) | each claim in the answer, matched to the confirmed facts or the owner's writing: correct · incorrect · unverifiable |
| *"Can it pick up on the connections"* | **Connections** — confirmed links stated, out of confirmed links that touch the entity | per link, whether the answer states the relation (in the direct answer or the relation question) |

Supporting, not scored: **which sources it cited**, and how many are the owner's own
(the-master-plan.com, the Medium publication, DEV, Substack, LinkedIn, PyPI). That shows *why* an engine
knows what it knows.

**Unverifiable claims go to the owner**, like every proposal in this system: *"Perplexity says Masterplan
Infinite Weave is an LLC in Arizona. True?"* A confirmed claim becomes a declared fact and is scored as
correct from then on; a denied one is scored as incorrect. The ground truth grows from the owner's answers,
never from the engines'.

---

## 4. Where it shows

- **Work panel, a Resolution section**: per entity, per engine, the three scores and their trend; the
  answers to read in full; the open claims to confirm or deny. The Nodus disambiguation problem would be
  the first thing on screen.
- **The planner** (phase C): one line per entity in the Work block (*"Nodus: mixed on 1 of 3 engines,
  confused with nodus.com"*), so an AI Search plan targets what is actually weak rather than generic work.
- **The score**: not wired. Works feed the loop, not the score (`WORLDVIEW` decision 3). Whether the
  owner's own success measure should become a KPI is decision 5.

---

## 5. Cadence and cost — bounded, because RippleTrace's sweep was retired for cost

The paid echo sweep was retired at about $65 a month for about three citations in eighteen months
(`rippletrace-data-supply`). This check has a hard monthly cap and a small default, and every call is
metered through `perform_external_call` like the rest.

| | Questions | Engine calls (3 engines) | Judge calls | Rough cost per run* |
|---|---|---|---|---|
| **Core** (brand, person ×2, Nodus, aindy-runtime, A.I.N.D.Y., 3 key links) | 9 | 27 | 27 | ~$0.75 |
| **Full** (all 9 entities, person ×2, all links) | ~18 | ~54 | ~54 | ~$1.50 |

\* Estimates from published per-call prices, to be measured on the first real run: Perplexity `sonar`
about $0.005–0.01 a request, OpenAI's web search tool about $0.025 a call plus tokens, Claude's web search
about $0.01 a search plus tokens, a `gpt-4o-mini` judgement under $0.001.

**Recommended default: core, weekly, about $3 a month,** with `full` on demand from the panel, and a
monthly ceiling the check refuses to exceed. Engine answers move slowly; weekly is enough to see a trend
and cheap enough to forget about.

---

## 6. Rollout

| Phase | What | Answers |
|---|---|---|
| **A** | the person and brand entities (decision 1); question generation; the three engines; raw answers stored; the judge and the three scores; **Run a check** in the Work panel | *"How well do I resolve, today?"* |
| **B** | weekly schedule with the cost ceiling; trend per entity and engine; unverifiable claims as proposals the owner confirms or denies | *"Is it getting better?"* and a ground truth that grows |
| **C** | the planner line per entity; optionally the score (decision 5) | AI Search plans aimed at what is weak |

**A before B**, because the first real run is also the cost measurement §5 is waiting on.

### 6.1 Phase B, as built (2026-10-01)

- **Claims to settle.** Unverifiable claims from the last three checks, grouped across engines and wordings
  (token overlap ≥ 0.6), most-repeated first, minus any already answered. `true` → *"Confirmed by the owner"*
  in the next check's facts; `false` → listed to the judge as denied, so a repeat is scored incorrect;
  `skip` → not asked again (`resolution_claims`, `rc2claims0001`).
- **The ceiling.** Estimated per call (Perplexity $0.008, OpenAI $0.03, Claude $0.02, judge $0.008: published
  prices, not the bill). A check that would take the month past `AINDY_RESOLUTION_MONTHLY_CEILING_USD`
  ($10) is refused before anything is spent; an open check counts at its full estimate. A core check is
  about $0.80.
- **Weekly.** `masterplan_resolution_weekly`, Mondays 07:30: a core check for each owner who has run one
  (having run one is the opt-in), unless one ran in the last six days or is open.
- **Trend.** Per question and engine across the last eight checks, shown as ● resolved ◐ mixed ○ wrong.

---

## 7. Open decisions — the owner's

1. **The person and the brand.** Recommended: add Work kinds **`person`** and **`brand`**, so *Shawn
   Knight* and *Masterplan Infinite Weave* are Works with summaries and links like the rest (*Shawn Knight
   created Masterplan Infinite Weave; Masterplan Infinite Weave includes A.I.N.D.Y.*). Alternative: a
   separate identity record. Works keep one model and one panel.
2. **Engines.** Recommended: **all three** (Perplexity, OpenAI, Claude): they draw on different indexes,
   and one engine resolving you is not the same as being resolved. Cheaper alternative: Perplexity alone.
3. **Cadence and ceiling.** Recommended: **core weekly, a $10 monthly ceiling**, full on demand.
4. **Bare-name questions.** *"Who is Shawn Knight?"* alone will often find someone else; that is the honest
   test of criterion 1 for a common name. Recommended: **ask both** bare and with context, report both.
5. **Does resolution become a KPI?** It is literally the owner's success measure for AI Search
   Optimization. Recommended: **not yet**. Run B for a month first and see if the numbers are stable
   enough to steer by.

---

## 8. What this spec does not claim

- It does not claim engines are deterministic. Answers vary by run and by engine; the trend is the signal,
  not any single answer.
- It does not claim the baseline is complete: four questions on one engine, one on two others.
- It does not decide what to *do* about a weak entity (the Nodus disambiguation, for instance). That is
  AI Search Optimization work, which `content.draft` and the planner can now help with, measured by this.
- The costs in §5 are estimates until the first run measures them.
