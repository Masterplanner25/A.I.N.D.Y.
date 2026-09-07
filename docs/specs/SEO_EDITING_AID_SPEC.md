---
title: "The SEO Tool as an Editing Aid"
last_verified: "2026-09-07"
api_version: "1.0"
status: draft
owner: "app-team"
---

# The SEO tool is an editing aid — three things it needs to be one

**Status:** DRAFT. Nothing built. The two defects that prompted it are fixed separately; this
covers what the tool should *become*.

**Origin:** the owner used the tool on a real ~4,000-word draft on 2026-09-06 and reported three
gaps. The framing correction underneath them is the important part:

> *"It's still an SEO tool feature — the entire tool is an editing aid. It doesn't rewrite the
> article for you, and while I did think of that, it would kinda defeat the purpose of what the
> tool is for."*

That settles a question this spec would otherwise have to open. **The tool advises; the human
edits.** Every feature below is judged against that: does it help the writer decide what to
change, without changing it for them.

---

## 0. Status, 2026-09-07

| section | state |
|---|---|
| §2 Target keywords | ✅ built (#312) |
| §3 Repetition | ✅ built (#312) |
| §4 Saving — the analysis persists | ✅ fixed and **verified live** (see below) |
| §4 Saving — **the draft as a unit** | ❌ **the only unbuilt piece** |
| §4 Phase labels in the UI | ✅ shipped |
| §4 Feeds registered so the handoff happens | ✅ 4 sources, 215 drop points |

**Not complete.** Three of §5's four open questions are still open, and all three are questions
about the draft unit rather than about anything already built — which is the honest reading of
where this spec stands: the measurements are done, the loop is not.

---

## 1. What just got fixed, and why it matters to this spec

Two defects, fixed outside this spec, because they needed no design decision:

| defect | effect |
|---|---|
| `seo_analysis` called `prepare_input_text(text)`, whose `limit` defaults to **500 words** | every metric described the opening ~500 words while being reported as the article's. The owner's `Word Count: 507` **was the truncation point** |
| `extract_keywords` had **no stopword filter** | `the, it, a, not, that, to, and, was, of, i` — a stopword frequency table, not keywords |

They matter here because **everything below was unusable while they stood.** A density target is
meaningless if densities are computed on 12% of the text; a repetition report is noise if the
repeated words are "the" and "of". The fixes are the precondition, not the feature.

They also explain why the tool felt thin rather than wrong: it produced confident numbers, and
confident numbers about text it never read are harder to distrust than an obvious error.

---

## 2. Target keywords — the tool asks the wrong question today ✅ BUILT 2026-09-07

Today the tool answers *"what words appear most often in this text?"* — a question with a known,
useless answer for English prose, and only slightly less useless once stopwords are removed.
"relationships, process, conversation, runtime, frameworks" describes the draft; it does not tell
the writer whether the draft will be found.

The owner's proposal:

> *"We either need to put a field in for what we want the keywords to be…"*

That changes the question to **"am I actually covering what I am trying to rank for?"**, which is
the question an SEO editing aid exists to answer.

### Shape

An optional list of target terms or phrases, supplied with the text. When absent the tool behaves
as it does now (discovered keywords); when present it reports **coverage against intent**:

| per target term | reported |
|---|---|
| occurrences | count in the body |
| density | % of total words |
| verdict | absent · thin · healthy · overused |
| placement | present in the first ~100 words? in any heading? |

Placement is deliberately included. A term at 1.5% spread evenly through the body is a different
article from the same term appearing only in paragraph 40, and the writer can act on the
difference.

### The judgement it must not make

Thresholds ("healthy" vs "overused") are a claim about search engines that this tool cannot
verify. Existing constants — `_KEYWORD_STUFFING_PCT = 4.0`, `_WEAK_FOCUS_PCT = 0.5` — are already
stated as thresholds and should stay visible as such: **shown with the number, not instead of
it.** A verdict that hides the density is the tool deciding for the writer.

### ★ What building it settled

Three decisions the shape above did not name, each of which had a wrong answer that would have
looked fine:

- **A phrase is matched as a token sequence, not as loose words.** `"runtime framework"` is a
  different target from `"runtime"` and `"framework"` counted separately, and substring matching
  would find `"run time"` inside `"runtime"`. Counting the component words would report coverage
  for a phrase the article never uses.
- **Density counts the words a phrase occupies.** Three uses of a three-word phrase is nine
  words of the article, not three. Reporting it any other way makes a phrase look three times
  thinner than a single word used equally often — and the writer would read that as needing
  *more* of it.
- **`in_heading` is `None`, not `False`, when no headings were found.** The parser reads
  markdown headings and deliberately nothing cleverer: a short line with no full stop is
  usually a heading and sometimes a list item or a signature. A confident "not in any heading"
  for an article whose headings the parser cannot see is worse than saying nothing, so the
  response carries `headings_found` and the client renders *"no headings found"*.

---

## 3. Repetition — an editing aid feature, not a separate tool ✅ BUILT 2026-09-07

The owner's second half:

> *"…and a count of word density / repeated words — as that seems to be the bigger issue there
> (as far as a human needing assistance with AI-generated writing)."*

An earlier draft of this spec tried to split this off as "an editing aid, not an SEO metric". The
owner rejected the split, correctly: **the whole tool is an editing aid**, so a repetition report
belongs in it.

It is also the feature with the clearest use. AI-assisted prose has a characteristic repetition
signature — the same connective phrasing, the same sentence openers, a favourite noun recurring
every few paragraphs — and it is nearly invisible to the person who just wrote it. Surfacing it is
the tool doing something a writer genuinely cannot do for themselves by re-reading.

### What it reports

- **Overused content words** — beyond the top-N list, terms whose frequency is high *relative to
  the article's own distribution* rather than to an absolute threshold.
- **Repeated multi-word phrases** — 2–4 word n-grams occurring more than once. This is where the
  AI-writing signature actually lives; single-word repetition is often legitimate topical focus.
- **Sentence-opener repetition** — how many sentences begin with the same word or construction.
  The article that prompted this opens many consecutive sentences with "It" and "That".
- **Position, not just count** — three uses spread across 4,000 words is fine; three in one
  paragraph is a thing to fix. A count alone cannot distinguish them.

### What it must not do

**No rewriting, and no "suggested replacement" text.** The owner considered rewriting and rejected
it as defeating the purpose. Slippage here is easy and would be gradual — a "suggested phrasing"
field is a rewrite with extra steps. The tool points; the writer decides.

### ★ What building it settled

- **One tic must be reported once.** "It is a framework for runtimes" yields `it is a framework`,
  `is a framework for` and `a framework for runtimes` as three distinct 4-grams, **none of which
  contains another** — so a naive n-gram count reports one habit as six findings and buries the
  real signal. Phrases claim their token spans widest-first, and an overlapping fragment of an
  already-reported repetition is dropped.
- **Overuse is measured against the article's own median**, not a fixed count. "Appears 8 times"
  is meaningless without the length: 8 in 400 words is a tic, 8 in 8,000 is nothing.
  `OVERUSE_RATIO` was **measured rather than guessed** — at 2.5 a flat distribution hides its own
  outlier (five words at 4 and one at 8 gives a median of 4 and a cutoff of 10, so the word that
  is plainly twice as common as everything else goes unreported). 2.0 catches it, and the long
  article stays quiet because its median rises with it.
- **Pure-stopword phrases are grammar, not habits.** `"of the"` repeating is English.
- **Repetition is computed on every analysis**, because unlike target keywords it needs no new
  input from the writer — and it is the half the owner called the bigger issue.

---

## 4. ★ Saving — everything the tool produces is currently thrown away

> *"There's no save button for any of it — the analysis, the meta generation or the suggestions."*

All three surfaces compute a result, render it, and lose it on navigation. Consequences:

- **No before/after.** The entire point of an editing aid is that you act on it and re-check. With
  nothing retained, the writer cannot see whether an edit improved anything — the tool can tell
  you the score is 55 but never that it was 41 yesterday.
- **Re-analysis is the only way back**, which for the meta description and suggestions means
  re-running an LLM call to recover output that already existed.
- **Nothing accumulates.** Contrast the rest of this repo, where `search_history` and
  `research_results` persist — the SEO surface is the outlier, not the norm.

### ★ Correction 2026-09-06 — saving was not missing, it was broken

This section originally said the surfaces "compute a result, render it, and lose it on
navigation". **That was wrong about the cause.** Full persistence was wired the whole time and
losing every write:

`analyze_seo_content` → `execute_durable_search` → `persist_search_result` → `search_history`.
The route passes `db` and `user_id`; nothing is missing from the path.

What failed is that `search_memory` returned `context.items` as **`MemoryItem` objects**, and
that dict is embedded in the result written to `search_history.result` — a **JSON column**.
`json.dumps` cannot serialise a MemoryItem, so the INSERT raised, `persist_search_result` caught
it, logged a warning, and returned the unpersisted result. The caller still got its answer.
`search_history` held **0 rows**, and the "Recent SEO Analyses" panel was permanently empty.

**It was conditional on recall finding something**, which is why it survived: with an empty
memory `items` is `[]`, which serialises fine. The feature worked when the system was new and
broke as memory filled up — and every test that recalls nothing still passes.

Fixed by converting through the runtime's own `memory_items_to_dicts`, already used this way in
`automation/flows/flow_definitions.py:361`.

### ★ Verified live 2026-09-07 — the fix works, in the condition that used to break it

Asserting in tests that a MemoryItem serialises is not the same as proving the write lands, so
the path was exercised against the running stack:

```
search_history before   0 rows
analyze_seo_content(... db, user_id) → memory count 2
search_history after    1 row
```

**`memory count 2` is the part that matters.** The bug was conditional on recall finding
something — with an empty memory `items` is `[]`, which serialises fine, which is exactly why it
survived so long. A run that recalled two items and still persisted is the case that used to
fail. (The test row was deleted afterwards; the panel is a real surface, not a scratch pad.)

**What this changes for §4.** The analysis now persists. What is still genuinely absent is
narrower than "saving":

- the **meta description** and **suggestions** are separate calls whose output is not stored
- there is no **draft** as a unit, so analyses cannot be compared over time — the before/after
  question this section is really about

★ **This is the only unbuilt part of the spec** as of 2026-09-07, and it is the part that turns
a set of readings into a loop. Everything else the tool now does is a measurement taken once:
you can learn that a phrase repeats and that a target is thin, act on both, re-run, and the tool
has no memory that the first reading ever happened.

`seo_routes.py` also persists three metrics via `save_calculation` (`seo_readability`,
`seo_word_count`, `seo_avg_keyword_density`) into the analytics calculation store, which remains
a second, partial copy of the same information.

### What saving needs to mean

Not a "save" button that stores a blob. The unit worth keeping is **a draft and its analyses over
time**:

| | |
|---|---|
| identity | the draft — named by the writer, not by a timestamp |
| each analysis | scorecard + generated meta + suggestions + the target keywords used |
| the point | comparison across analyses of the same draft |

Without the draft as the unit, saving produces a pile of unrelated scorecards and the before/after
question stays unanswerable — which is most of why saving is wanted.

### ★ Resolved 2026-09-06 — both, split by publication

> *"Honestly it has a possibility to be both — but the difference would be, the SEO tool is the
> before work; RippleTrace comes after the work is published publicly. That may be a point we
> should make clear in the UI though."*

They are not competing homes. They are **two stages of one lifecycle**, and publication is the
boundary:

```
SEO tool          ──── publish ────>     RippleTrace
the draft                                the published thing
before                                   after
you can still change it                  you can only measure it
```

RippleTrace's own model already says this. `content_source.py`:

> *"A drop point is a thing you published somewhere else."*

So the distinction is not new — it was already the design, just never stated anywhere the user
could see it.

**This makes the handoff nearly free rather than a migration.** A `ContentSourceDB` row is an
RSS/Atom feed that ingests every future post automatically. The owner publishes to a Medium
publication, which has a feed. Register it once and a published article arrives in RippleTrace as
a drop point on the poll job, with no action at publication time.

Current state (2026-09-06): **0 content sources**, 1 drop point, 8 pings — so the automatic path
exists and is unused. Registering the Medium feed is a smaller and more valuable piece of work
than anything else in this section.

**✅ Done, and it worked.** Measured 2026-09-07: **4 content sources**, **215 drop points**, **264
pings**. The owner registered the Substack and dev.to feeds, detection was switched on, and the
automatic path produced a corpus overnight without further action. What it has not yet produced
is the *match* — no saved draft exists to link to a drop point, because the draft unit above is
still unbuilt.

**And it closes a loop nothing else can.** If a saved draft can be matched to the drop point it
became — by URL, or by title — then the SEO tool's advice becomes checkable against what the
article actually did after publication. That is the only path in this repo from "the tool said
your density was thin" to "and here is whether that mattered." It does not need to be built now,
but the draft record should carry whatever makes the match possible later (the published URL, at
minimum).

**UI consequence, which the owner raised and which is the actionable part today.** Nothing on
either surface says which phase it is for. A writer with a draft has no way to know RippleTrace is
not for them yet, and a writer with a published article has no reason to think the SEO tool is
done with it. One line on each surface, naming the phase and pointing at the other, is most of the
fix — and it is worth doing *before* the save feature, because saving is what makes the two
surfaces start to look alike.

---

## 5. Open questions

1. **Where do target keywords come from?** Typed per analysis, remembered per draft, or suggested
   from the text and confirmed by the writer? The third is the most useful and the most dangerous
   — a suggested keyword the writer accepts unread is the tool deciding what the article is about.

2. ~~**Is a draft an SEO artefact or a RippleTrace content item?**~~ **RESOLVED 2026-09-06 (owner):
   both, split by publication** — the SEO tool is the before-work, RippleTrace is after. See §4.
   Both near-term pieces are now done: the phase line ships on each surface, and 4 feeds are
   registered (215 drop points ingested).

3. **Should the scorecard's overall score survive at all?** `search_score` blends readability,
   average density and word count into one number (`search_scoring.py:291`). With targets and a
   repetition report, a single number is the least informative thing on the page — and averaging
   keyword densities was already a questionable summary before targets existed.

4. **How much history?** Every analysis, or the latest per draft plus a marked baseline? Every
   analysis is more useful and grows without bound; this repo has already been bitten once by
   unbounded telemetry (`HEALTH-EVENT-VOLUME-1`, 3.6 GB of health events).

---

## 6. What this spec does not claim

It does not claim the three features are equally urgent. **Saving is the one the owner hit
first**, and it is the one that makes the other two compound — a repetition report you cannot
compare against last week's is a snapshot, not an aid.

It also does not claim the tool should become a content platform. The line the owner drew — it
advises, it does not rewrite — is the same line that keeps this from growing into a writing
assistant. Every feature here should be checkable against it, and any that cannot be is out of
scope by definition.
