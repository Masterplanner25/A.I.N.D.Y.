---
title: "What an article answers: AI-search readiness for the owner's writing"
last_verified: "2026-11-08"
api_version: "1.0"
status: draft
owner: "app-team"
---

# What an article answers: AI-search readiness for the owner's writing

**Status:** DRAFT, 2026-10-25. **§8 decided by the owner on 2026-11-08**, all four as recommended. **Phase A built the same day** (§7). The fixes that came first (the meta description,
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
| **RippleTrace** (post-publication) | 233 pieces (re-measured 2026-11-08). Stored text for 217: DEV 152, Substack 46, Medium 19, which is **178 distinct pieces** once cross-posts are merged. None for YouTube (15) or LinkedIn (1) |
| **Link targets in stored text** | **DEV: 131 of 152** keep markdown links (`[text](url)`). **Substack and Medium: none.** `content_archive.to_text` strips HTML tags and their `href` with them, so **65** pieces (46 Substack, 19 Medium) have lost their link targets (59 on 10-25) |
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
  point. These can be automated, and since 2026-10-25 they are: `share_drafts_v1.nd`
  (`apps/rippletrace/services/share_drafts.py`) writes the LinkedIn post, short post, meta description
  and previous piece's footer for each new piece into the Drafts section. §2's answers and §3's links
  can feed it once they exist.

---

## 7. Phases

| Phase | What | Schema |
|---|---|---|
| **A** ✅ **built 2026-11-08** | In the SEO tool, on draft text: **What does this answer?** (§2, without the Resolution tie), outbound links to own pieces, and missing own pieces (§3). `POST /apps/seo/answers` (`apps/search/services/article_answers.py`), `POST /apps/seo/own_links` (`apps/rippletrace/services/own_links.py`) | none |
| **B** | Per published piece, once per content hash: answers and links stored. Ingestion keeps link targets. Inbound links and series navigation. **B1 built 2026-11-08:** ingestion keeps link targets (`drop_points.content_links`, migration `rt2links0001`; `services/links.py`), and `content_archive.backfill_links` recovers them for stored pieces (DEV from its markdown text, Substack and Medium by one re-fetch). **B2 built 2026-11-08:** `piece_answers` (one reading per piece and `content_hash`) and `drop_points.answers` (migration `rt3answers0001`, every stored piece `skipped`: decision 3), written by `piece_answers_v1.nd` behind `AINDY_PIECE_ANSWERS_NODUS` with a recorded Python fallback; queue or read one at `/apps/rippletrace/drop_points/{id}/answers`. B3 (inbound links, series navigation) follows | a links column on `drop_points`, and a table for answers |
| **C** | The tie to resolution: answers matched against the Resolution Check's questions per Work. Shown on the Work card, and offered to the planner as one line | none beyond B |
| **D** | Source validation (§4), then style (§5) | none expected |

---

## 8. Decisions: the owner's, **all four taken 2026-11-08, as recommended**

1. **Which model reads for answers? DECIDED: gpt-5.5**, the drafter's model, at low reasoning effort.
   - It follows instructions where gpt-4o did not.
   - It takes about 25–50 s a call, so in the SEO tool it runs on a button, never on typing.
   - Not chosen: gpt-4o-mini, the SEO tool's model, which is faster and weaker.
2. **Keep link targets for Substack and Medium? DECIDED: yes.**
   - Store the links separately when a piece is fetched.
   - Re-fetch the **65** pieces (46 Substack, 19 Medium) once, through the platform APIs ingestion already
     uses.
   - Without it, inbound authority would cover DEV only.
   - Phase B's links column carries it.
3. **Answers for the back catalogue? DECIDED: new pieces automatically**, older ones only when the owner asks
   for a piece.
   - Not chosen: the whole catalogue once, about 178 model calls (178 distinct pieces on 2026-11-08).
4. **Does any of this feed the Infinity score? DECIDED: no, not yet**, until it has been measured for a while,
   as with Resolution Check decision 5.
   - It is shown on the Work card and to the planner only.

**Context the owner gave the same day.** Disambiguation comes from many signals across the body of work, never
from one or two articles. That is why §2 and §3 measure each piece *in relation to the rest of the catalogue*
(which of your pieces it answers beside, links to, and is linked from), not as a standalone score.

---

## 9. What this spec does not claim

- That any of it improves a ranking. It measures what the text offers an engine and how the owner's
  pieces connect, not where they rank.
- Anything about page speed, accessibility or markup. Those are the platforms' (DEV, Substack, Medium),
  not the owner's.
- That a question the article answers will be asked. The Resolution Check measures what is asked.
