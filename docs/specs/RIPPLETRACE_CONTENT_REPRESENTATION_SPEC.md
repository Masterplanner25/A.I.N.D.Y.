---
title: "RippleTrace Content Representation"
last_verified: "2026-09-07"
api_version: "1.0"
status: draft
owner: "app-team"
---

# RippleTrace holds references to your work, not a representation of it

**Status:** DRAFT. Nothing built. Written 2026-09-07, the day RippleTrace produced its first
three strategies and they all said the same thing.

**Owner's framing, which is the whole spec:**

> *"How is RippleTrace supposed to do all that it's supposed to do without an actual
> representation of what's actually been written/published?"*

Context: `STRATEGY_LAYER_SPEC.md` (the same "Genesis captured it, the schema dropped it"
shape), `SEO_EDITING_AID_SPEC.md` §4 (drafts, and the before/after split).

---

## 1. What happened, and why it is not a theme-extraction bug

The pipeline switched on 2026-09-06 worked. Unattended, in one night:

```
4 feeds -> 214 drop points -> 205 pings -> 3 strategies
```

The first strategies ever produced:

```
Chatgpt Momentum Play  | Combine chatgpt focus with platform Substack within 25.2 day(s)
Case Momentum Play     | Combine case focus with platform Substack within 25.2 day(s)
Series Momentum Play   | Combine series focus with platform Substack within 25.2 day(s)
```

The **structure** is sound and was earned from real data: Substack genuinely is the
highest-echo platform, and 25.2 days is the measured interval between successful drops.

The **themes** are not themes. `chatgpt`, `case`, `series` are the words shared by
*"2025 ChatGPT Case Study Series: …"*, which prefixes most of the catalogue. Three strategies
say one thing, and that thing is a naming convention.

The obvious read is "fix theme extraction". That read is wrong, and the owner's correction is
what makes it wrong:

> *"Those were keywords — something the writer is choosing to emphasize due to optimization
> purposes. This is less what do you want them themed around and more so what are they
> actually themed around without you saying it."*

SEO keywords are **declared intent**. RippleTrace themes are supposed to be **discovered**.
Same word, opposite direction — and the second cannot be computed from what the first
provides.

---

## 2. ★ What the system actually has — audited, not assumed

| platform | drops | stored themes | where they came from |
|---|---|---|---|
| DEV | 143 | `productivity, chatgpt, ai, usecases` | **the author's dev.to tags** |
| Medium | 10 | `creativity, artificial-intelligence, storytelling` | **feed categories** |
| YouTube | 15 | `artificialintelligence, chatgpt, productivity` | **hashtags in the title** |
| Substack | 46 | `case, experiment, search, study, chatgpt, live` | word frequency over title + summary |

`derive_themes` opens with:

```python
if cleaned_tags:
    return _unique(cleaned_tags)[:MAX_THEMES]
```

**Publisher tags win.** So for **168 of 214** drop points the "themes" are labels the author
wrote — declared intent, exactly what the owner is distinguishing this from. Only Substack,
whose feed carries no tags, falls through to derivation, and derivation is title-word
frequency, which returns the title template.

So the system answers *"what did you say it was about"* for 79% of the corpus and *"what
words are in your titles"* for the rest. **The question "what is this actually about" is not
answered anywhere in it**, and no tuning of `derive_themes` will change that, because the
inputs are a title and a truncated summary.

### And the summary is not even kept

`drop_points` has `title`, `url`, `date_dropped`, `core_themes`, `tagged_entities`, three
scores, `mentions_checked_at`. **There is no content column.** The feed summary is passed to
`derive_themes` at ingest, used once, and discarded (`content_ingest.py:173`).

So there was exactly one moment when the system could have looked at what was written, it
looked at 600 truncated characters, and it kept only the word counts.

---

## 3. Why this is not cosmetic: five engines read those themes

Themes are not a display field. Grepped 2026-09-07:

| engine | use |
|---|---|
| `influence_graph` | `overlap_count = len(themes_a & themes_b)` — **links drop points by shared themes** |
| `causal_engine` | `theme_overlap` → emits `"shared_themes"` as a **causal reason** |
| `strategy_engine` | counts themes to name and describe a strategy |
| `playbook_engine` | `"Create content focused on {themes}"` |
| `content_generator` | drafts new posts from themes |

With `chatgpt` on nearly every piece, the consequences compound:

- the **influence graph** links everything to everything, because everything shares a theme
- the **causal engine** reports `shared_themes` as the reason one piece caused another, when
  the shared theme is a title word
- the **playbook** advises writing about "chatgpt"
- the **content generator** drafts posts about "case"

**Noise in `core_themes` does not stay in `core_themes`.** It becomes graph edges, causal
claims and recommendations — each of which reads as a finding rather than an artifact. This
is the `SOAK_AUDIT` §3 shape again: a system with no real signal producing confident output.

---

## 4. The actual question: is a drop point a reference or a representation?

Today a drop point is a **reference** — a URL, a title, some scores. That is coherent, and it
is enough for what RippleTrace was first built to do: search for the URL, count who echoed
it, score the spread. **Echo detection needs no content and is unaffected by any of this.**

But everything built *on top* of drops — themes, the influence graph, causality, playbooks,
generation — needs to know what the work *says*, and none of it can, because nothing kept the
words.

That is the owner's point, and it is a question about what the domain is:

| | reference (today) | representation (proposed) |
|---|---|---|
| stores | title, url, scores | + the text, or a durable summary of it |
| can answer | "did this travel?" | "what is this about, and what else is like it?" |
| themes | your tags, or your title words | derived from the work |
| influence graph | tag overlap | actual similarity |
| cost | ~nothing | storage, and a decision about full text vs summary |

---

## 5. What a representation could be — three options, increasing cost

1. **Keep the feed summary.** One `TEXT` column, populated at ingest from data already
   fetched and currently thrown away. Cheapest by far; changes nothing about fetching.
   Limitation: a feed summary is often the first paragraph or an author blurb, so it is
   better than a title and still not the article.

2. **Fetch and store the article text.** The fetcher exists (`content_fetch.fetch_url`, used
   for page ingestion). Limitation: **this is the 403 path** — publishers block automated
   page fetches, which is why feed subscription exists at all. Feasible for some platforms,
   not Medium.

3. **Store an embedding.** `text-embedding-ada-002` is already in use for memory, and
   similarity is what the influence graph actually wants — `overlap_count` on tag strings is
   a crude proxy for it. Limitation: an embedding answers "what is this near" without
   answering "what is this about" in words a human can read, so it complements themes rather
   than replacing them.

**These compose rather than compete.** (1) is a prerequisite for a better (2) or (3) and is
worth doing on its own.

---

## 6. Open questions

1. **Full text, or a summary?** Full text is the honest input for theme discovery and the
   expensive one — storage, and `HEALTH-EVENT-VOLUME-1` is a live memory of what unbounded
   text in Postgres costs (3.6 GB of one table). A stored summary is bounded and lossy.

2. **What technique discovers a theme?** Frequency is out — it returns the title template.
   TF-IDF across the corpus would correctly discount `chatgpt` for being everywhere, and is
   cheap. An LLM extraction is better and costs a call per drop. An embedding gives
   similarity without labels. This is undecided and should not be decided before (1).

3. **What happens to the 168 drops themed from tags?** Re-deriving would overwrite labels the
   author chose with labels the system inferred. Keeping both — `declared_themes` and
   `derived_themes` as separate fields — is more honest than either replacing or ignoring,
   and lets the influence graph choose which it means.

4. **Does this converge with the SEO draft question?** `SEO_EDITING_AID_SPEC` §4 wants a
   draft as a saved unit, and a draft *has the text*. If a draft becomes a drop point at
   publication, the representation problem solves itself for everything published from then
   on — and only the back catalogue needs fetching. That is the same before/after boundary
   the owner already drew, seen from the data side.

5. **Does anything downstream need re-running?** The 3 existing strategies were built from
   template-derived themes. They are not wrong exactly — the platform and cadence findings
   are real — but their names and descriptions are artifacts.

---

## 7. What this spec does not claim

It does not claim RippleTrace is broken. **Echo detection — the thing it was built for —
works and is unaffected**: 205 pings from 214 drops in one night, filtered against same-host,
self-reference and prior-publication. That half needs no content and is producing real data.

It claims the layer *above* detection — themes, influence, causality, playbooks, generation —
is built on an input that cannot support it, and that this is a modelling gap rather than a
tuning problem. Five engines currently reason about what your work is about, using either the
labels you typed or the words in your titles.
