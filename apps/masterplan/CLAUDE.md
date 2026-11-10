# Masterplan: content drafts

<!-- Moved from the root CLAUDE.md on 2026-11-09 so it loads only when working here. -->

## `content.draft` — what the drafter is given, and the model

A draft about a Work (`work=` set) gets four things from `draft_service.write_draft`: the owner's
facts (`work_facts`: summary, connections, presence, confirmed claims), a **NEVER SAY** list (claims the
owner denied), and **what AI search engines said when asked by name**
(`resolution_review.engine_answers`). It must also write a *Not to be confused with* section that
describes each look-alike **only as the engines did** (#461 → #463). If a draft gets the Work wrong, check
the owner's Work data before the code: "part of Aindy-runtime" in a draft came from the owner's own link,
and that link is true (owner, 2026-10-14).

**The model is `gpt-5.5`** (`AINDY_DRAFT_MODEL`; `gpt-4o` rolls back). gpt-4o skipped the instructions
it was given. **gpt-5.x refuses `max_tokens` and any temperature but 1**, so `_sampling(model)` gives a
reasoning model `max_completion_tokens` (16,000) and `reasoning_effort` (`low`,
`AINDY_DRAFT_REASONING_EFFORT`). A draft takes about 25–50 s, inside the 120 s step budget. Probe a model
with a two-token call before switching to it; `models.list()` says what the key can use.
