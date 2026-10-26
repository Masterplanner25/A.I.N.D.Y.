---
title: "What an article answers: AI-search readiness for the owner's writing"
last_verified: "2026-10-25"
api_version: "1.0"
status: draft
owner: "app-team"
---

# What an article answers: AI-search readiness for the owner's writing

**Status:** DRAFT, 2026-10-25. Nothing here is built. The fixes that came first (the meta description,
titles and suggestions now read the whole article) are #495.

**Origin:** the owner used the AI SEO tool on the *2026 Agents Case Study Series* and asked how it
arrives at what it shows. They then redefined two classic SEO dimensions:

> *"We can't really check usability in the SEO sense from this side, but what we can check is the
> text's usability in AI search, i.e. what range of questions it could answer."*

> *"Authority: instead of the classic SEO authority, we go with my way of authority: linking back to
> your own relevant pieces."*

Both definitions are the owner's and are settled. This spec says what each one measures, what it is
built from, and in what order.

It sits beside two others:
- **`SEO_EDITING_AID_SPEC`** says the tool advises and the writer edits. Nothing below rewrites a
  sentence or inserts a link.
- **`RESOLUTION_CHECK_SPEC`** says success is entity resolution, not rankings. This spec is the
  article-level half of the same goal.

---

## 1. What already exists (measured 2026-10-25)

| Piece | What it gives this spec |
|---|---|
| **AI SEO tool** (pre-publication) | Draft text, title, target keywords, saved drafts. Since #495 its model calls read the whole article |
| **RippleTrace** (post-publication) | 220 pieces. Stored text for 204: DEV 145, Substack 46, Medium 13. None for YouTube (15) or LinkedIn (1) |
| **Link targets in stored text** | **DEV: 130 of 145** keep markdown links (`[text](url)`). **Substack and Medium: none.** `content_archive.to_text` strips HTML tags and their `href` with them, so 59 pieces have lost their link targets |
| **`published_work` recall** | Every stored piece is chunked into memory and recallable, with cross-posts collapsed (#453). This is how "your relevant pieces" are found |
| **Work model** | The owner's Works, confirmed claims, and the denied claims (the NEVER SAY list) |
| **Resolution Check** | Per Work, the questions asked, each engine's answer, its `citations` and the verdict (`resolution_answers`) |

---

## 2. Usability, the owner's definition: what range of questions the text answers

Page speed, accessibility and navigation cannot be measured from here, and this spec does not pretend
to. What can be measured is what an AI engine could use the text for.

**Per article:**
- **Answers.** A model reads the whole article and lists the questions it answers. Each one comes
  with the short passage that answers it, so the writer can check it against the text rather than
  trusting a count.
- **Raised, not answered.** Questions the article brings up and leaves open. Some are deliberate,
  such as a series setting up its next part. The tool lists them; the writer decides.
- **Range.** The answers grouped by kind (*what is*, *how*, *why*, *compared with*, *who*). It is
  reported as a spread, not as a score.

**The tie to resolution (phase C).** For each Work the article is about, put the Resolution Check's
own questions and its latest verdict next to the article's answers. The finding worth surfacing is:
*this piece answers a question the engines got wrong, or could not answer.* That tells the owner
whether a piece fills a real gap. The Nodus reference draft exists for exactly this reason.

**What it must not do:** suggest wording that would make the article answer more. The editing-aid
rule applies here as it does to repetition.

---

## 3. Authority, the owner's definition: linking back to your own relevant pieces

**Not** backlinks from other sites. Paid backlink and echo data was retired on 2026-09-16 (about
$65 a month for about 3 citations in 18 months), and it is not re-proposed here.

| Measure | Built from | Available |
|---|---|---|
| **Outbound:** which of your pieces this article links to | links in the draft, matched against RippleTrace URLs, with cross-posts as one piece | now, for any draft |
| **Missing:** your relevant pieces it does not link to | recall over `published_work`, scored for relevance to this article | now |
| **Inbound:** which of your published pieces link to this one | a link graph over the stored pieces | DEV now; Substack and Medium only after their link targets are kept (decision 2) |
| **Series navigation:** the *What's Next?* footer links its neighbours | the series' pieces, in order | DEV now |

A missing link is shown as a candidate with the passage that makes it relevant. It is never inserted
for the writer. Engine citations (`resolution_answers.citations`) naming one of the owner's pieces are
the outside view of the same thing, and are shown beside it rather than mixed into it.

---

## 4. Source validation

An article's claims, checked against what the owner has already settled:
- A sentence that **contradicts a denied claim** (the NEVER SAY list) is a warning. This is the check
  that would have caught "part of A.I.N.D.Y." in the Nodus draft.
- A claim about a Work that **is not in its confirmed facts** is information, not an error. It may be
  new, and it may become a confirmed claim.
- **Cited sources:** links out to other sites, listed so the writer can see what each claim leans on.

---

## 5. Style (later)

The repetition panel counts, and it cannot tell a rhetorical device from an accident. The owner's
published pieces are the reference: a structure the owner repeats across a series is a device. This
is the least defined part of the spec and comes last.

---

## 6. Where the owner's workflows fit

The owner's chat on 2026-10-25 described two workflow families:
- **Before publication:** narrative audit, then an editorial pass, then author approval. These need
  the author's judgement, so this spec's outputs are **information for them**: answers, links,
  claims.
- **After publication:** series links, meta description, a LinkedIn post built on the piece's central
  point. These can be automated. Under the 10-22 rule they become a one-shot `.nd` workflow, started
  when RippleTrace ingests a new piece, that saves its outputs as drafts for the owner to send.
  §2's answers and §3's links feed it. It gets its own spec.

---

## 7. Phases

| Phase | What | Schema |
|---|---|---|
| **A** | In the SEO tool, on draft text: **What does this answer?** (§2, without the Resolution tie), outbound links to own pieces, and missing own pieces (§3) | none |
| **B** | Per published piece, once per content hash: answers and links stored. Ingestion keeps link targets. Inbound links and series navigation | a links column on `drop_points`, and a table for answers |
| **C** | The tie to resolution: answers matched against the Resolution Check's questions per Work. Shown on the Work card, and offered to the planner as one line | none beyond B |
| **D** | Source validation (§4), then style (§5) | none expected |

---

## 8. Open decisions: the owner's

1. **Which model reads for answers?**
   - Recommended: **gpt-5.5**, the drafter's model, at low reasoning effort, which follows
     instructions where gpt-4o did not. It takes about 25–50 s a call, so in the SEO tool it runs on
     a button, never on typing.
   - Alternative: gpt-4o-mini, the SEO tool's model, faster and weaker.
2. **Keep link targets for Substack and Medium?**
   - Recommended: **yes**. Store the links separately when a piece is fetched, and re-fetch the 59
     pieces once through the platform APIs ingestion already uses.
   - Without it, inbound authority covers DEV only.
3. **Answers for the back catalogue?**
   - Recommended: **new pieces automatically**, older ones only when the owner asks.
   - The alternative is about 204 model calls, once.
4. **Does any of this feed the Infinity score?**
   - Recommended: **no**, until it has been measured for a while, as with Resolution Check decision 5.

---

## 9. What this spec does not claim

- That any of it improves a ranking. It measures what the text offers an engine and how the owner's
  pieces connect, not where they rank.
- Anything about page speed, accessibility or markup. Those are the platforms' (DEV, Substack, Medium),
  not the owner's.
- That a question the article answers will be asked. The Resolution Check measures what is asked.
