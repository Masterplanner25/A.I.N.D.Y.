---
title: "The SEO Tool as an Editing Aid"
last_verified: "2026-09-06"
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

## 2. Target keywords — the tool asks the wrong question today

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

---

## 3. Repetition — an editing aid feature, not a separate tool

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

### What already exists

`seo_routes.py` **already persists three metrics** via `save_calculation` — `seo_readability`,
`seo_word_count`, `seo_avg_keyword_density`. So a fragment of the analysis is stored, into the
analytics calculation store, while the thing the user actually wants back (the meta description,
the suggestions, the keyword table) is not. That is the same shape as elsewhere in this repo: the
mechanism exists, wired to the wrong half.

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

**Open question:** does a draft belong to the SEO tool, or is it a `rippletrace` content item?
RippleTrace already tracks the owner's external publications, and an article that gets published
becomes one. Deciding this later means migrating drafts; deciding it now costs one conversation.

---

## 5. Open questions

1. **Where do target keywords come from?** Typed per analysis, remembered per draft, or suggested
   from the text and confirmed by the writer? The third is the most useful and the most dangerous
   — a suggested keyword the writer accepts unread is the tool deciding what the article is about.

2. **Is a draft an SEO artefact or a RippleTrace content item?** §4. Cheap now, a migration later.

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
