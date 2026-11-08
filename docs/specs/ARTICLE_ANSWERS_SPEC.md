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

## 4. Source validation: "What does this claim?" (decided 2026-11-08, §8 decisions 5–8)

**Where:** the SEO tool, on draft text only, on a button, **What does this claim?** It is information for the writer
before publication, like "What does this answer?" (§6). Nothing blocks and nothing runs on published pieces.

**What a claim is (decision 6): a checkable fact.** A statement presented as fact that could be checked:
- numbers and statistics;
- dates and events;
- attributions ("X found", "Y said");
- statements about named products, people or organisations, the owner's own Works included;
- causes or comparisons stated as fact.

Not claims: opinions marked as opinion, questions, hypotheticals, advice, and the writer's own experience framed as
experience ("I found…").

**What each claim is checked against:**
- **About one of the owner's Works:**
  - A claim that **contradicts a denied claim** (the NEVER SAY list) is a warning. This is the check that would have
    caught "part of A.I.N.D.Y." in the Nodus draft.
  - A claim that **is in its confirmed facts** is shown as confirmed.
  - A claim that **is in neither** is information, not an error. It may be new, and it may become a confirmed claim.
- **About anything else (decision 7): sourced or not.** Each claim is listed with the link in the draft that backs
  it, or marked *no source in the draft*. It says what a claim leans on, not whether it is true. No web check.
- **Cited sources:** every link out to another site, listed with the claims that lean on it.

**A warning is information only (decision 8).** It is shown; it never blocks or changes the draft.

**The reader:** one gpt-5.5 call per press, as §8 decision 1 (about 25–50 s, low reasoning effort), paid with the
writer's own key (FR-59). Its output is checked like §2's answers: every claim must be found in the text.

---

## 5. Structure: "What's the structure?" (decided 2026-11-08, §8 decisions 9–11)

**The goal (owner, 2026-11-08): reveal that there is a structure in the first place.** It does not judge a structure
deliberate or accidental, and it never grades the draft. The repetition panel counts repeats; this shows the patterns
they belong to. Like §4, it is information for the writer before publication, in the SEO tool, on a draft.

**What is shown, free, on every analysis (no model, decision 10):**
- **The skeleton:** the sections in order with their relative lengths, how the piece opens and how it closes.
- **Repeated sentence openings:** sentences that start the same way ("It could …", "Phase 1 — … Phase 2 — …"), with
  every instance quoted.
- **The repeats from the old repetition panel** (repeated 2–4-word phrases, overused words), folded in (decision 11):
  a repeat that belongs to a pattern is shown as part of it, and the rest stand on their own.

**On a button, What's the structure? (one gpt-5.5 call, about 20–50 s, the writer's key):** the model names the
patterns, such as contrast ("It wasn't X. It was Y."), lists, naming sequences and refrains. It quotes every instance,
including ones whose words differ, which the free pass cannot see. As in §2 and §4, every quoted instance is checked
against the text.

**Against the draft's series (decision 9):** beside the draft, the shape its series' published pieces share: the
skeleton they have in common, and openings and closings that recur across them, such as the article list and *What's
Next?* footer. Shown side by side, never as a score.
- **Which series:** one of the owner's confirmed series in RippleTrace. It is taken from the draft's title when the
  title starts with the series name ("2026 Agents Case Study Series: …"); otherwise the writer picks one, or none.
- **Its pieces:** the series' published pieces with stored text (phase B), read from the database at no model cost.

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
| **B** | Per published piece, once per content hash: answers and links stored. Ingestion keeps link targets. Inbound links and series navigation. **B1 built 2026-11-08:** ingestion keeps link targets (`drop_points.content_links`, migration `rt2links0001`; `services/links.py`), and `content_archive.backfill_links` recovers them for stored pieces (DEV from its markdown text, Substack and Medium by one re-fetch). **B2 built 2026-11-08:** `piece_answers` (one reading per piece and `content_hash`) and `drop_points.answers` (migration `rt3answers0001`, every stored piece `skipped`: decision 3), written by `piece_answers_v1.nd` behind `AINDY_PIECE_ANSWERS_NODUS` with a recorded Python fallback; queue or read one at `/apps/rippletrace/drop_points/{id}/answers`. **B3 built 2026-11-08:** `GET /apps/rippletrace/drop_points/{id}/links` (`services/piece_links.py`): links to, linked from, series neighbours and whether each pair links; RippleTrace's "Answers & links" panel shows it with the stored answers. B1's backfill now re-fetches DEV pieces whose text came from the feed (19 had lost their links) | a links column on `drop_points`, and a table for answers |
| **C** ✅ **built 2026-11-08** | The tie to resolution: answers matched against the Resolution Check's questions per Work. Shown on the Work card, and offered to the planner as one line. As built (`masterplan/services/resolution_writing.py`): for each question the engines did not fully resolve, the owner's pieces that answer questions **about** its subject (the subject named in the answered question, kind fitting). Name matching cannot tell an answer to "What is A.I.N.D.Y.?" from one about A.I.N.D.Y.'s history (found live), so it never claims a piece answers the engines' exact question. In the Resolution section and as a clause on the Work's planner line | none beyond B |
| **D1** ✅ **built 2026-11-08** | **What does this claim?** (§4, decided 2026-11-08): claims in a draft, checked against the owner's facts and denied claims, and the rest marked sourced or not. As built: `POST /apps/seo/claims` (`apps/search/services/article_claims.py`), the owner's Works read through `sys.v1.work.get_claim_truth` (masterplan, `work.read`); the model points at numbered facts, denials and links and only real pointers are kept; the SEO tool's button and panel | none |
| **D2** | **What's the structure?** (§5, decided 2026-11-08): the draft's skeleton and repeated openings (free), its patterns named on a button (one model call), beside its series' shared shape; the repetition panel folded in | none expected |

---

## 8. Decisions: the owner's, **1–4 taken 2026-11-08 as recommended; 5–8 (phase D1) and 9–11 (phase D2) the same day**

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

**Phase D, decided 2026-11-08 (owner):**

5. **Where does source validation run? DECIDED: only in the SEO tool, on a draft**, as information for the writer
   before publishing. Not on published pieces. The button is **What does this claim?**
6. **What is a claim? DECIDED: a checkable fact** (§4): numbers, dates and events, attributions, statements about named
   products, people or organisations (the owner's included), causes or comparisons stated as fact. Not opinions marked
   as opinion, questions, hypotheticals, advice, or experience framed as experience.
   - Not chosen: also opinions stated as fact (more results, noisier); only numbers and attributions (misses causal and
     comparative claims).
   - The owner widened the scope from claims about their own work to claims overall.
7. **How far is a claim about anything else checked? DECIDED: sourced or not**, from the draft's own links. No web check.
   - Not chosen: asking Perplexity whether each claim holds up (paid per claim, slower, only as good as the search).
8. **What does a warning do? DECIDED: information only.** It never blocks.

**Phase D2, decided 2026-11-08 (owner).** The goal was reframed first: D2 reveals that a structure exists. It does
not tell a deliberate structure from an accidental one, which is what §5 said before.

9. **What is the draft's structure shown against? DECIDED: the draft and its series**, side by side: the shape the
   series' published pieces share, from their stored text, at no model cost. Never as a grade.
   - Not chosen: the draft alone (says nothing about how it sits among the owner's pieces); the whole catalogue
     (broadest, but noisier, since different series have different shapes).
10. **How is the structure found? DECIDED: free, plus a naming button.**
    - Always shown, with no model: the skeleton and repeated sentence openings.
    - A button makes one gpt-5.5 call to name the patterns, quoting every instance.
    - Not chosen: free only (cannot see a pattern whose words differ); model only (shows nothing until pressed).
11. **What happens to the repetition panel? DECIDED: folded in.** Its repeated phrases and overused words become part of
    the structure view: as instances of a pattern where they belong to one, on their own where they don't.
    - Not chosen: keeping it separate; retiring it.

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
