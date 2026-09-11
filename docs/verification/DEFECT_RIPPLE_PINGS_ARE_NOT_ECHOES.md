---
title: "Defect — RippleTrace pings are topical citations, not echoes of your work"
last_verified: "2026-09-07"
api_version: "1.0"
status: current
owner: "app-team"
---

# Defect — RippleTrace pings are topical citations, not echoes of your work

**Found 2026-09-07**, immediately after the container work landed, by the owner asking one
question about a number I had just quoted at them:

> *"What are we actually measuring here?"*

I had reported that the Case Study Series "travels five times better per piece" than the Duality
series. **That claim is not supported by anything in this system.** Tracing what the numbers are
made of produced this document.

**Severity: high, and it is a measurement defect rather than a crash.** Nothing errors. 256 ping
rows, 18 drop points over the success threshold, five strategies and a ranked "top strategy" are
all produced from an input that does not measure what the domain is named for.

**Observed against the running stack**, not read from source. Every figure below is a query
against the live database on 2026-09-07.

---

## 1. What a ping is supposed to be

RippleTrace's whole premise (`content_source.py`, `content_ingest.py` module docstring):

> *"A drop point is a thing you published somewhere else."*
> *"A ping means an echo somewhere else."*

`spread_score` counts distinct platforms that echoed you. `narrative_score` is the headline
number. `SUCCESS_NARRATIVE_THRESHOLD = 15.0` is the gate `build_strategies` uses to decide which
of your pieces "worked".

---

## 2. What a ping actually is

`ripple_detection` searches for the drop point's URL, plus its title as an exact phrase when the
title is distinctive (`_is_distinctive`, ≥25 chars and ≥4 words). **That method is correct.**

The provider is **Perplexity** — an *answer engine*. Asked `"2025 ChatGPT Case Study Series:
Chain of Thought"`, it does not return pages containing that phrase. It answers the question and
returns **the sources it used**. Those are topically related by construction and are almost never
the piece being searched for.

Sampled from the live table:

| your piece | "echoed" at |
|---|---|
| *…Chain of Thought* | `arxiv.org/html/2603.05706v1` |
| *…Educational Psychology* | `blogs.sussex.ac.uk/learning-matters/…integrating-generative-ai` |
| *…Prompt Engineering* | someone else's Medium post on prompt engineering |
| *The Google Gemini Experience…* | a Business Insider article about Gemini |

The host distribution says the same thing without needing to read a single result:

```
openai.com 36 · arxiv.org 10 · LinkedIn 10 · Medium 9 · support.google.com 8
sciencedirect.com 4 · cdn.openai.com 4 · tandfonline.com 4
128 distinct hosts, 81 of which appear exactly once
```

That is an answer-engine citation profile. Real echoes of a personal Substack series would look
like small blogs, social posts and newsletters — not `openai.com` thirty-six times.

### ★ The decisive number

```sql
select count(*) filter (where external_url ilike '%masterplanner%'
                           or external_url ilike '%the-master-plan%'),
       count(*)
from pings where ping_type = 'mention';
```

```
1 of 256
```

**One ping out of 256 points at a page plausibly connected to the author.** The other 255 are
pages about the same subject, written by other people.

---

## 3. What that makes every number downstream

```
narrative_score = (pings + 2·semantic + inferred) × ln(pings + 1)      threadweaver.py:134
```

Every live ping is `connection_type = 'direct'`, so both bonuses are zero and it reduces to
`pings × ln(pings+1)`. The threshold of 15 is therefore **about 8 pings**.

So, precisely:

| the system says | it actually means |
|---|---|
| this piece "travelled" | a topical search returned ≳8 results |
| `narrative_score` 24.5 | the search returned about 9 topically-related pages |
| `spread_score` | how many distinct domains that answer cited |
| `velocity_score` | how fast those citations were *detected*, which is a property of the poll schedule |
| "Case Study Series travels 5× better" | **searches derived from those titles return more pages** |

That last row is the claim I made and it is a statement about how densely the internet writes
about a subject, not about whether the owner's work reached anyone.

---

## 4. ★ Why nothing downstream could tell

**A ping row is byte-identical whether it is a real echo or a topical citation.** `PingDB` holds
`ping_type='mention'`, `connection_type='direct'`, a source platform and a URL. There is no field
that distinguishes *"this page cites you"* from *"this page is about the same thing"*, and no
consumer checks.

So 256 rows of no signal produced:

- 18 drop points over `SUCCESS_NARRATIVE_THRESHOLD`
- `build_strategies` selecting those 18 as "what worked"
- 5 strategies, ranked, with a top entry at `success_rate` 0.722
- `influence_graph` edges, `causal_engine` reasons, `prediction_engine` inputs,
  `learning_engine` outcome labels

This is `SOAK_AUDIT_2026-08-15` §3 exactly — *a system with no real signal producing confident
output* — except it is now in a surface someone reads, and it survived because the confident
output is plausible. Substack genuinely is the owner's highest-volume platform; 25 days genuinely
is the cadence. The structure was right, which is what made the content unexamined.

---

## 5. What is NOT wrong

Worth stating, because the instinct is to distrust everything nearby:

- **Ingestion is sound.** 215 drop points from 4 feeds, deduped by
  `sha256(user_id|normalized_url)`. What you published is recorded correctly.
- **The container work is sound and unaffected.** Detection reads *titles*, confirmation is a
  human decision, and `tagged_entities` is now populated on 95 of 214 drops. `Influence Spike`
  firing for the first time is a real fix to a real gap — the classification is right; the
  *scores it is ranked by* are not.
- **The detection method is right.** URL plus distinctive exact-phrase title is the correct
  query. The provider is the wrong instrument for it.
- **The filters work.** Same-host, self-reference and prior-publication exclusions all fire.
  They are why the one plausible self-reference is one and not more.

---

## 6. ★ Fixed 2026-09-07 — remedies 1 and 2, together

Remedy 1 alone would have deleted evidence; remedy 2 alone would have labelled the problem
without solving it. Built as one change:

**Detection now looks.** Each surviving candidate is fetched and checked for the drop point's
URL (in any of the forms a citing page plausibly writes it) or its title (when the title is long
enough that a match means something). Either is sufficient — a link is the strongest evidence,
but plenty of genuine echoes name a piece without linking it.

**Three states, and the middle one is the design:**

| state | meaning | scores? | written? |
|---|---|---|---|
| `verified` | fetched, and it contains the URL or title | yes | yes |
| `unverified` | could not be fetched, or predates the check | **no** | yes |
| rejected | fetched, demonstrably does not cite you | — | **never** |

*"We looked and it does not cite you"* and *"we could not look"* are different answers, and only
the first is evidence. Publishers who refuse scripted requests produce the second constantly
(`_BLOCKED_STATUSES`), so treating a 403 as a negative would silently convert a bot policy into a
statement about the author's reach. A rejected candidate is not written at all: a page that does
not cite you is not a ripple, and recording it labelled would double the table with rows nothing
consumes and leave the same ambiguity one column further down.

**A per-batch verification budget**, not per drop point. A run can produce 200 candidates (10
drop points × 20 results); an unbudgeted verifier would turn a background job into an outbound
crawl. Overflow is recorded `unverified` rather than skipped, so the next run revisits it.

### ★ 6b. The first clean reading, and what it showed about the budget (2026-09-10)

The 09-07 numbers (59 drops checked, 0 verified) were taken while PostgreSQL was reinitialising
under host memory pressure, so they were set aside. Re-run after a reboot with 0 reinits and
1.2 GB available:

```
checked=10 drops   found=200   kept=135   verified=0
written unverified=102   rejected (fetched, does not cite)=33
```

**Still zero verified**, and the 33 rejections are the fix working: fetched, read, and they do
not cite the piece. The host was not the reason for the 09-07 zero.

But the 102 written `unverified` were mostly not checked at all. Across the whole table:

| `verification_note` | rows |
|---|---|
| pre-fix rows (never checked, by design) | 265 |
| **verification budget exhausted for this run** | **158** |
| HTTP 403 | 63 |
| 2 MB cap / 404 / 401 / connection | 16 |

135 kept candidates against `MAX_VERIFICATIONS_PER_RUN = 60` makes the budget, not the web,
the dominant reason a ping lands `unverified`. And the sentence *"the next run revisits it"*
— written in this doc, in two code comments and in a test docstring — was never true:
`_record_ping` returned early on any existing id, so a ping written past the budget was
permanently unverified after one unlucky run and indistinguishable from a 403 without reading
its note.

**Fixed the same day.** `BUDGET_EXHAUSTED_NOTE` is now a constant and the only note that means
*"not looked at yet"*. On each run, a candidate whose ping carries it is fetched if budget
remains and then upgraded to `verified`, left `unverified` with the publisher's real reason, or
deleted — it never scored, so nothing the engines computed depended on it. Every other existing
ping is skipped for free: a 403 re-fetched every run is the same refusal at the price of a
fetch, and until this change every already-known ping *was* re-fetched before the early return
noticed it. The batch now charges its budget by fetches made, not by candidates kept.

The cap itself stays at 60. It is doing its job; it just needed to be a queue rather than a
verdict.

### ★ 6c. It was not a queue either (2026-09-11)

The morning after: **233 stranded rows, up from 158**, with detection running twice overnight
(a 6-hourly job; each run ~60 fetches in ~2 minutes, ~2 s each). Still 0 verified of 602.

Two things §6b got wrong, both measured rather than reasoned:

1. **Capacity was below production.** A run keeps ~135 candidates and had 60 fetches. No
   queue discipline drains a queue that fills faster than it empties.
2. **§6b's revisit depended on the search.** A debt was paid only when a later search returned
   the same URL for the same drop point — which an answer engine, by construction, mostly
   does not. Most debts were never *eligible* to be paid.

Fixed: `settle_verification_debts` reads stranded pings **off the table**, oldest first, and
fetches them directly — same three outcomes as at detection — taking up to half of each run's
budget so new drop points are still checked. The budget is 200 (~7 minutes per run; ~65 to
spare over production). `MAX_RESULTS_PER_DROP_POINT` stays at 20: search cost is per request,
and with 0 verified of 602 nobody yet knows whether the tail of the results is where a real
citation would sit. At 233 owed and ~100 settled per run, the backlog clears in about a day of
runs — and then the number this whole document is waiting for is finally a number.

### ★ The intended, visible consequence

`threadweaver` counts `verified` pings only, and the migration labels all 256 existing rows
`unverified`. **So every score in the domain falls to zero until detection re-runs.** That is the
correct state: a 0 meaning *"nothing confirmed"* is better than a 24.5 meaning *"a search
returned nine topically-related pages"*.

The five strategies built from those scores will empty out with them. §7's reasoning stands —
the rows are labelled, not deleted.

---

## 6a. Remedies as originally written

Ordered by how much they actually fix, not by effort.

1. **Verify the mention.** Fetch each candidate URL and confirm it contains the drop point's URL
   or title before writing a ping. `content_fetch.fetch_url` already exists and is already used
   for page ingestion. This turns a citation into an echo or discards it, and it is the only
   option that makes `narrative_score` mean what its name says.
   *Cost:* one fetch per candidate, and the 403 problem (`_BLOCKED_STATUSES`) applies — some
   hosts cannot be verified and would have to be recorded as unverified rather than dropped.

2. **Record the distinction instead of resolving it.** Add `verified` to `PingDB` and let
   scoring count only verified pings. Cheaper than (1) only if verification is deferred, and it
   has the virtue that the existing 256 rows become *honestly labelled* rather than deleted.

3. **Change provider.** A search index that returns pages containing a phrase is a different
   instrument from an answer engine. This is the fix that requires no per-ping work, and the
   largest external change.

4. **Do nothing and relabel.** If "topically adjacent pages" is a signal worth having — it is
   arguably a *competition* or *context* signal — then the domain should say so, and
   `narrative_score` should not be gating `build_strategies` as though it measured reach.

**Not a remedy: tuning.** `MIN_DISTINCTIVE_TITLE_CHARS`, `MAX_RESULTS_PER_DROP_POINT` and
`SUCCESS_NARRATIVE_THRESHOLD` are all downstream of a wrong instrument. Moving any of them
changes how many topical citations are counted, not whether they are echoes.

---

## 7. What to do about the existing 256 rows

They are not junk — they are correctly-recorded results of a search that answers a different
question. **They should be labelled, not deleted**, for the same reason the container dismissal
does not un-tag drops: silently rewriting history that engines have already reasoned over is its
own defect. Until they are labelled, the scores computed from them should not be read as reach.

The five strategies currently in the table were built from those scores and should be treated as
unfounded — the `Influence Spike` names are right (they name real bodies of work); the ranking
between them is not.

---

## 8. The one-line version

`RIPPLE-PINGS-NOT-ECHOES-1` — RippleTrace's mention detection uses an answer engine, so a ping
records a page *about the same subject* rather than a page that *cites you*: 1 of 256 live pings
points at the author. Every score in the domain, the 18 "successful" drop points, and all five
strategies are computed from it, and no field distinguishes the two kinds of result.
