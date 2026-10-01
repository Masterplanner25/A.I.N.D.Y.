---
title: "The Work Model — what you have made, and how it fits together"
last_verified: "2026-09-27"
api_version: "1.0"
status: draft
owner: "app-team"
---

# The Work model — what you have made, and how it fits together

**Status:** phase A BUILT 2026-09-27 (#420); phase B BUILT 2026-09-30 (§5.1, as built); C not started. Written 2026-09-27 from the owner's question, after the agent's
first week of real work on the MasterPlan.

**The owner, which is the whole spec:**

> *"This system has no idea I'm the author of the 2025 ChatGPT Case Study Series, 2025 ChatGPT/AI
> Duality of Progress Series, no idea that I work in AI Search Optimization, no idea that those
> series were working implementations of AI search optimization. Hell, it has no idea I'm its
> creator (doesn't necessarily need to know that). Has no idea where aindy-runtime, A.I.N.D.Y.,
> Nodus or anything really … how it all fits together. That's supposed to be the MasterPlan."*

---

## 0. This is not a new idea. It is four open questions coming due at once

Four draft specs each reached the edge of this and stopped, deliberately, at a question for the
owner. This spec answers those questions rather than restating their designs:

| Spec | Where it stopped | Answered here |
|---|---|---|
| `TITLE_AS_CONTAINER_SPEC` §4b, §7 | *"Aggregate now, decide ownership later."* A `Work` record *"would not buy measurement — it would buy intent: a target, a lifecycle, a purpose"*. *"There is no row anywhere in this system that says 'the 2025 ChatGPT Case Study Series exists, it has 46 pieces, and I made it.'"* Open question 3: who owns a container | §3: the Work record, owned by the MasterPlan |
| `WORLDVIEW_AND_KNOWLEDGE_SPEC` §4 decision 4 | *"Where does knowledge/work live? … a new store or a projection over existing domains is unresolved."* | §3: a small declared store (intent) plus projections over existing domains (measurement) |
| `RIPPLETRACE_CONTENT_REPRESENTATION_SPEC` §5, §6 | Three options (feed summary, article text, embedding), *"these compose rather than compete"*; full text vs summary undecided | §5: all three, in order, bounded |
| `STARTING_POSITION_SPEC` §3 | `platform_live` is `False` *"because nothing ever set it, not because the platform does not exist"* | §7: a Work is the basis a declared baseline cites |

What none of the four has: **how the works relate to each other and to the plan**, and **the agent
seeing any of it**. That is new here (§3.2, §6).

---

## 1. What the system holds about the owner today — audited 2026-09-27

| Where | What it holds |
|---|---|
| **MasterPlan** `structure_json.key_assets` | five strings: *"Nodus (orchestration DSL)", "Aindy-runtime (self-hosted runtime for AI agents)", "A.I.N.D.Y. (persistent execution partner)", "30+ companion packages", "16 domain apps on Aindy-runtime"* (the last was wrong, by the owner's correction on 2026-09-28: A.I.N.D.Y. is one platform with 16 domains; removed from the live plan that day). No record behind any of them, no relation between them, and not passed to the planner (`masterplan.planning_context` sends IDs and strategies only) |
| **MasterPlan** objectives | three generic domains: *Ethical AI Framework, Partnership Development, Platform Enablement* |
| **RippleTrace** | 214 drop points (DEV 143, Substack 46, YouTube 15, Medium 10), Feb 2025 → May 2026: title, URL, platform, date. **No text.** Two confirmed containers: *2025 ChatGPT Case Study Series* (42 drops at decision) and *2025 ChatGPT/AI The Duality Of Progress* (53). Four content feeds, all `ok` |
| **Identity** | a profile with every field empty; **0 observations**, `identity_signals` 0 rows |
| **Memory** | 118 nodes. The only RippleTrace ones are 6 telemetry nodes (`system_event:rippletrace_*`). Not one contains a sentence the owner wrote |
| **Authorship** | `authors` is a sign-in log (`admin@local.test`, *"Signed in"*) plus the Epistemic Reclaimer. It owns no work |
| **Genesis** | 2 sessions, used to synthesise the plan and then left |
| **The agent** | 15 tools, none touching RippleTrace. Its context: KPIs, the reasoning recommendation, the plan's IDs and strategies |

**One finding the audit surfaced, stated as evidence and not as a conclusion.** The Case Study
Series' titles and the system's own calculators share names, piece for piece:

| Case Study title | Calculator in `calculation_services.py` |
|---|---|
| *Virality Formula* | `calculate_virality` |
| *Social Media Engagement Formula* | `calculate_engagement_score` |
| *Business growth* | `business_growth` |
| *Monetization Efficiency* | `monetization_efficiency` |
| *AI-Optimized Decision Making* | `decision_efficiency` |
| *Opportunity Cost of Inaction* | `lost_potential` |
| *AI Productivity Boost* | `calculate_ai_efficiency`, and the `ai_productivity_boost` KPI |

The series also includes *AI Search Optimization*, *AI Search Framework* and *AI Search
Experiment*. **Whether the formulas were taken from the articles is the owner's to confirm.** If
they were, the system's scoring is built out of the owner's published work, and the system does
not know it. That is the sharpest possible statement of this spec's problem.

---

## 2. What is missing is not data. It is the model that connects it

Every app holds a fragment, and each fragment is correct. What no app holds is the thing the owner
means by *"how it all fits together"*:

- **a work as a thing**, not a string in a list or a phrase repeated across titles;
- **what the work is for**, in the owner's words: intent, lifecycle, purpose (the §4b point);
- **how works relate**: built on, implements, demonstrates, part of;
- **how works serve the plan**: which objective, which strategy;
- **the owner's practice**: *AI Search Optimization* is not a project and not a series. It is
  what the series were *doing*.

The system was built as engines (score, plan, tasks, ripple, agent), each owning a slice. It is
`RECURRING_DEFECT_PATTERNS.md` §5 (*built, one wire short*) at the scale of the product.

---

## 3. The model

### 3.1 A Work

A new app-owned table, `works`, owned by **masterplan** (decision 1, §9). The MasterPlan is where
the owner says it belongs, and `key_assets` shows it always meant to hold this.

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `user_id` | FK, indexed. A work belongs to a person; a plan points at it |
| `name` | the owner's name for it: *"Nodus"*, *"2025 ChatGPT Case Study Series"* |
| `kind` | `project` · `product` · `series` · `practice` · `publication` · `other`. Validated against a constant set |
| `summary` | what it is, **in the owner's words**. Required: a work without one is a string with an id |
| `role` | the owner's relation to it: `creator` · `author` · `maintainer` · `contributor` |
| `status` | `active` · `finished` · `paused` · `planned`. A finished series stops reading as a failing one (§4b) |
| `started_on` / `ended_on` | dates the owner declares; may predate the system |
| `url` | canonical home, optional |
| `declared_target` | optional, the §4b "52 planned, 46 done": declared, never computed |
| `provenance` | `declared` (the owner said it) · `confirmed` (the system proposed it, the owner accepted) |
| `created_at` / `updated_at` | history is kept (§3.4) |

**Measurement is never stored on a Work.** A series' drop count, narrative average and trajectory
are already computed on demand by `GET /containers/performance` (§4b). A Work links to that
measurement; it does not copy it. That is the declared-vs-measured split this repo already applies
to worth, baselines and runway.

### 3.2 How works relate — the part no spec has

`work_links`: `from_work_id`, `to_work_id`, `relation`, `note`, `provenance`.

| `relation` | reads as | example |
|---|---|---|
| `built_on` | A runs on / depends on B | A.I.N.D.Y. `built_on` aindy-runtime |
| `executes` | A is the language / engine B runs | aindy-runtime `executes` Nodus |
| `demonstrates` | A is a working implementation of B | Case Study Series `demonstrates` AI Search Optimization |
| `part_of` | A is a component of B | the 16 domain apps `part_of` A.I.N.D.Y. |
| `informs` | A's ideas shaped B | Case Study Series `informs` the Infinity KPIs (if §1 is confirmed) |
| `precedes` | A came before B, and B continues it | one series `precedes` the next |

A small, closed vocabulary on purpose. A free-text relation is a sentence nothing can reason
over; six verbs cover the owner's own description above.

### 3.3 How works reach the plan, and the evidence

- **Work → plan:** `work_objectives` (`work_id`, `objective_id`) and optionally a strategy. *"Nodus
  serves Platform Enablement."* This is the missing half of `objective_rollup`, which today counts
  hours toward an objective and cannot say *what* was built for it.
- **Work → drop points:** a series Work carries the container's id (`works.container_id`, a soft
  reference). *Built 2026-09-27 this way round rather than as a `work_id` on the container: the link
  lives with the domain that owns intent, and RippleTrace's table is untouched.* The container stays
  RippleTrace's (it is how drops are grouped, and how new drops join at ingest). The two confirmed
  containers are the first two series proposals. This answers `TITLE_AS_CONTAINER` open question 3:
  RippleTrace holds the reference, masterplan holds the work.
- **Work → published text:** through its drop points, once §5 stores the text.

### 3.4 History, not overwrite

A Work's `summary`, `status` and links change as the work does. Changes are kept (a
`work_revisions` log or the existing refine pattern), because *"what did I think this was for, a
year ago"* is exactly the partner question `WORLDVIEW_AND_KNOWLEDGE_SPEC` §3 is about.

---

## 4. How it is filled: a conversation, proposed then confirmed

**No forms.** Every time this repo has asked the owner to fill in structure cold, it stayed empty
(identity: 0 observations). Every time it proposed and asked, it got answered: phase advance,
worth declaration, containers, strategy conclusions. The house rule, *"confirmed, not
inferred"* (§4b), applies here without exception.

1. **Seed proposals from what already exists.** The system opens with what it can already see:
   - the five `key_assets` strings → five proposed Works (*"Is 'Nodus (orchestration DSL)' a
     project of yours? What is it, in your words?"*);
   - the two confirmed containers → two proposed series Works;
   - the drop points' platforms → *"You publish on DEV, Substack, Medium and YouTube. Is that one
     body of work or several?"*
2. **A conversation, in Collaborator.** A third mode beside *Agent* and *Plan*: **Work**. The owner
   talks about their work; the system extracts proposed Works, links and objective ties, and shows
   each as a card to **confirm, edit or dismiss**. Nothing is written until confirmed. Dismissals
   are kept, so a rejected proposal is not asked again (the container rule).
3. **Proposals from evidence**, once §5 stores text: *"These 8 Case Study titles share names with
   the system's calculators. Does the series `inform` the Infinity KPIs?"* The §1 finding is the
   first such proposal, and it is one only the owner can answer.

Genesis is the model for the conversation (a partner that asks), not its host: Genesis authors
the plan; this describes the work the plan is about.

---

## 5. The evidence layer: your writing, stored (Level 2)

Answers `RIPPLETRACE_CONTENT_REPRESENTATION_SPEC` §5–§6. All three options, in order, each bounded.

### 5.1 As built, 2026-09-30

**The verifications, run first** against each platform, read-only:

| Platform | Pieces | Where the text is | Result |
|---|---|---|---|
| DEV | 143 | public API by the piece's url (`/api/articles/{user}/{slug}` → `body_markdown`); it lists all 143. The feed carries the newest 12 whole, in `description` | all fetchable |
| Substack | 46 | per-post API by url (`/api/v1/posts/{slug}` → `body_html`), back to Feb 2025; the archive listing pages short and looked like 23. The feed carries the newest 20 whole (`content:encoded`) | all fetchable |
| Medium | 10 | the feed only (`content:encoded`): 10 items, 9 with a body | the feed covers them |
| YouTube | 15 | no text without transcripts | out of scope, marked `none` |

Pieces run 5–11k characters (~1.8 MB in all); embedding them is about $0.05, once.

- **Storage** on `drop_points` (`dp1content0001`): `content_text` (capped at 50,000), `content_source`
  (`feed` · `api` · `none`), `content_fetched_at`, `content_hash`, and `content_memory_hash`, the hash the
  memory chunks were written from.
- **Going forward:** a feed poll keeps a body of 1,500+ characters (an excerpt is not kept).
- **Backfill:** `content_archive.backfill_content`, 40 pieces a batch, a 0.5 s pause between platform
  requests, through RippleTrace's guarded `fetch_url`. A platform with no text or a piece that is gone
  (404/410) is marked `none`; a transient failure is retried next run.
- **Memory:** each piece is chunked at paragraph boundaries (~1,500 characters), one memory node per
  chunk: source `published_work`, `node_type` insight, tags `published_work`, the platform,
  `drop:<id>`, `series:<name>` and `work:<name>` (through `masterplan.works_by_container`). Written
  again only when the text's hash changes. Embeddings follow in the background (nodes are saved
  `embedding_pending`).
- **When:** a scheduled job (`rippletrace_archive_published_work`, every 10 minutes) runs both until the
  catalogue is done; `POST /apps/rippletrace/content/archive` runs a batch now. The Work panel shows
  *N of M pieces recallable by the agent*, per platform.

1. **Going forward, keep what the feeds already deliver** (that spec's option 1). Feed ingest
   already fetches each new post and throws the body away (`strip_html(…, limit=2000)` is for
   theme extraction). Keep the body. **To verify per platform before building:** which feeds carry
   the full article (`content:encoded`) and which carry an excerpt.
2. **Backfill the catalogue** (option 2), per platform, because the page path gets blocked (Medium
   returned 403 on a page and 200 on its feed from the same machine, 2026-09-06):
   - **DEV (143):** the public DEV API, which serves an article's source. *To verify:* endpoint,
     rate limits, and that it serves posts by author.
   - **Substack (46):** the feed covers the most recent 20; the older 26 need their pages, which
     have generally been fetchable. *To verify.*
   - **Medium (10):** the feed has 10 entries and there are 10 drops, so the feed may cover all of
     them. *To verify.*
   - **YouTube (15):** needs transcripts. **Out of scope here**; noted, not built.
3. **Storage, bounded.** `drop_points.content_text` with a hard cap (tens of KB, decided when the
   real sizes are measured), plus `content_source` (`feed`/`api`/`page`), `content_fetched_at`,
   `content_hash`. `HEALTH-EVENT-VOLUME-1` is the standing reminder of what unbounded text costs.
   Declared themes stay; derived themes are a separate field (that spec's §6.3).
4. **Memory: your writing, recallable** (option 3). Each article is chunked into memory nodes,
   source `published_work`, tagged with its Work. Embeddings already run for memory
   (`text-embedding-ada-002`, 1536-dim); for ~200 articles the cost is small, estimated once the
   sizes are known. **This is the change that makes recall return the owner's arguments instead of
   telemetry**, `WORLDVIEW`'s *"memory recall already returns telemetry rather than meaning"*.
5. **What it unblocks:** RippleTrace's five engines on content rather than title words
   (`RIPPLETRACE-NO-CONTENT-1`); series detection and §4.3's proposals; and matching a quoted
   sentence to the article it came from, the verifier the withdrawn citations needed
   (`RIPPLE-PINGS-NOT-ECHOES-1`, amended 2026-09-23).

---

## 6. What the agent sees

The planner context (`build_planner_context`) gains one compact block, beside the plan and KPI
blocks:

```
## Your work (confirmed by you)
Practice: AI Search Optimization.
- aindy-runtime (project, creator, active): self-hosted runtime for AI agents; executes Nodus;
  serves Platform Enablement.
- A.I.N.D.Y. (product, creator, active): persistent execution partner; built on aindy-runtime.
- 2025 ChatGPT Case Study Series (series, author, finished, 46 pieces on DEV): demonstrates AI
  Search Optimization; informs the Infinity KPIs.
…
```

- **Only confirmed Works.** A proposal the owner has not answered is not a fact the agent may use.
- **A budget.** A fixed cap on lines, most relevant Works first (active, linked to the current
  phase's strategies), so the block cannot crowd out the plan.
- **Depth through memory, not the block.** The block says *what* exists; `memory.recall` over
  `published_work` returns *what it says*. The marketing run of 2026-09-25 would then have known
  the series exist, what they demonstrate, and could have cited them.
- **Collaborator shows the same block**, so the owner can see what the agent is told.

---

### 6.1 Writing from the work, and where it goes (2026-09-30)

The first run after the catalogue was stored (`0aa01e33`, *"using my published AI Search Optimization
work, design an AI Search Optimized marketing plan for Nodus"*) recalled six of the owner's own pieces
and used none of them. Three causes: `memory.recall`'s description still said its results were
"mostly system telemetry"; the agent had no tool for prose, so the planner borrowed ARM's code
generator; and nothing told the planner to hand the recalled text to the writing step. Then the owner
asked *"where does the output go?"*: a step result, a memory node and a task, none a document.

- `memory.recall` says it returns the owner's writing (`published_work`), takes `tags`, and says how
  to pass its nodes on.
- **`content.draft`** (`sys.v1.content.draft`, `gpt-4o`): a brief plus `sources` by step reference,
  written from the owner's own pieces first (`OWN WORK` sources), cited inline as [S1] and listed at
  the end; a cross-post counts once. `arm.generate` now says it is for code.
- **`work_drafts`** (`wd1draft0001`): every draft is a document, stamped with the run that wrote it,
  listed in Collaborator's Work mode to read, edit, copy, download or delete.
- Stored text drops front matter and image links (DEV's `body_markdown` carried both into every first
  chunk); text stored before that is re-cleaned and its memory rewritten by the same job.

## 7. Boundaries with the neighbouring specs

- **Worldview** (positions, principles) stays `WORLDVIEW_AND_KNOWLEDGE_SPEC`'s. This spec is its
  layer 4, *knowledge/work*, only. Positions are about what the owner believes; Works are about
  what the owner made.
- **Identity** traits (working style) stay identity's.
- **Starting position:** a Work is the natural `basis` for a declared baseline (*"platform_live:
  true — aindy-runtime, active since 2025"*). That spec's baseline table is unchanged; it gains a
  citable reason.
- **Score:** Works feed the **loop, not the score**, `WORLDVIEW` decision 3's rule. Nothing here
  moves a KPI. Saying so early prevents it being wired in by accident.

---

## 8. Rollout

| Phase | What | Fixes |
|---|---|---|
| **A** | `works`, `work_links`, `work_objectives`; container `work_id`; seed proposals (§4.1); the Work conversation in Collaborator (§4.2); the planner block (§6) | *"It has no idea who I am or how it fits."* Needs no fetching |
| **B** | Feed bodies kept going forward; the per-platform backfill (after its verifications); bounded storage; `published_work` memory | Recall returns the owner's writing |
| **C** | Proposals from content (§4.3), including the §1 question; RippleTrace engines on content; quote matching | Depth, and the two open RippleTrace defects |

**A before B**, because A answers the owner's actual complaint and costs no fetching, and because
B's memory nodes should be tagged with Works that already exist.

---

## 9. Open decisions — the owner's

1. **Which domain owns a Work?** Recommended: **masterplan** (the owner's own answer, and where
   `key_assets` lives). Alternative: **authorship**, the domain named for it, which today owns
   watermarking and a directory of other people. Either way RippleTrace keeps the container.
2. **Where does the conversation happen?** Recommended: a **Work** mode in Collaborator. The
   alternative, a structured page, is where cold structure has stayed empty before.
3. **Full text or bounded?** Recommended: full text **up to a cap**, measured before the cap is set.
4. **Does the agent get the block by default?** Recommended: **yes**, confirmed Works only, within
   a line budget.
5. **Is §1 right?** Did the Case Study Series produce the formulas the system scores with? Only the
   owner knows, and it is the first `informs` link if so.

---

## 10. What this spec does not claim

- It does not claim the owner should have entered this data. The system never asked in a way that
  could be answered; §4 is the correction.
- It does not replace RippleTrace's containers, Genesis, or identity. It connects them.
- It does not decide the worldview layer, YouTube transcripts, or the SEO draft pipeline
  (`SEO_EDITING_AID_SPEC` §4, which would make new drafts arrive with text already).
- The §5 platform notes marked *to verify* are unverified. Each is checked before its code is
  written.
