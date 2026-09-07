---
title: "Declaring Worth in Genesis"
last_verified: "2026-09-07"
api_version: "1.0"
status: current
owner: "app-team"
---

# Declaring worth in Genesis — the number belongs where the meaning is

**Status:** BUILT 2026-09-07, in the shape §4 prescribes — defence 3 first, defence 2 not at
all. See §7 for exactly what shipped and what did not.

Originally: DRAFT, nothing built. The storage, scoring and API all existed and were correct as
of 2026-09-06 (#287, #289); what was missing was any way for a person to say the number.

**Owner's call, 2026-09-06:** *"Probably in Genesis, as that's where you could say how much each
means to you or the actual value worth."*

Context: `SOAK_AUDIT_2026-08-15.md` §2b and §7 · `TECH_DEBT.md` → `SOAK-THEN-FLIP-1` ·
`MASTERPLAN_GOAL_ATTAINMENT_SPEC.md` · `STRATEGY_LAYER_SPEC.md` (the same
Genesis-captures-it-then-the-schema-drops-it shape).

---

## 1. Why this is the last piece, and why it is not a form

The Worth axis is one of the three axes of the Infinity score. It has **0 declarations**, and
until 2026-09-06 that was correct: the maths summed incommensurable kinds, so declaring anything
would have produced a *confidently wrong* score. That is fixed. What remains:

| layer | state |
|---|---|
| `IntentValueDeclaration` model, ordinal + cardinal kinds | ✅ built (#289) |
| per-kind scoring, mean over declared kinds | ✅ built (#287) |
| `POST /apps/analytics/worth/declare`, routed | ✅ built |
| **any way for a human to reach it** | ❌ **nothing calls it** |

The obvious remedy — a "declare worth" panel — is the wrong one, for a reason the audit states
plainly:

> Declared worth in particular is a statement about intent, which is the one thing here that is
> only worth recording if it is true.

A blank form is homework. Homework gets filled in to make the form go away, and a Worth axis fed
by dutiful guesses is not uncalibrated — it is **confidently wrong**, which is the failure this
whole area keeps producing. The number has to be a by-product of meaning something, not a field.

**Genesis is where meaning is already being expressed.** The owner names domains, says what they
are for, and explains why they matter — in a conversation, unprompted. The plan's
`structure_json` already holds three `core_domains` with intents. The declaration is effectively
already made; only the magnitude is missing.

This is the third instance of one shape in this repo: **Genesis captures it, and the schema drops
it.** Phases became tasks and lost their identity; success criteria never became goals; worth is
never captured at all.

---

## 2. What exists to build on — audited, not assumed

| | |
|---|---|
| Conversation state | `GenesisSessionDB.summarized_state` (JSON) — `vision_summary`, `time_horizon`, `mechanism_summary`, `assets_summary`, `inferred_domains`, `inferred_phases`, `confidence` |
| Transcript | `GenesisSessionDB.transcript` (JSON) — full turn history |
| Draft | `GenesisSessionDB.draft_json` → `master_plans.structure_json` at lock |
| Synthesis output | `core_domains: [{name, intent}]`, `phases`, `success_criteria`, `risk_factors`, … |
| Lock | `create_masterplan_from_genesis(session_id, draft, db, user_id)` |
| Materialisation precedent | `masterplan_execution_service._extract_root_items` turns `structure_json["phases"]` into task rows |
| Declaration API | `record_value_declaration(db, user_id, target_type, declared_value, target_id, label, kind, note)` |

### ★ The rule this depends on already exists

`genesis_ai.py`, the conversation system prompt:

> **State extraction:**
> - Update only fields the conversation supports. Use null for anything not yet established;
>   **never invent a value to fill a field.**

That is precisely the discipline declared worth requires, already written down and already
applied to six other fields. This spec adds a seventh field to a contract that is designed for
exactly this problem — it does not introduce a new kind of risk, it extends an existing
guarantee to one more field.

---

## 3. The shape

```
conversation      you say a domain matters critically, or could be worth ~$50k
      ↓
state_update      a new `declared_worth` array — extracted from what you SAID, never assigned
      ↓
synthesis         core_domains carry their worth into structure_json
      ↓
lock              IntentValueDeclaration rows created, as phases → tasks are today
```

The two kinds map onto the owner's two phrasings without further design:

| the owner says | kind | value |
|---|---|---|
| *"how much each means to you"* | `intrinsic` / `strategic` | `low` \| `moderate` \| `high` \| `critical` |
| *"the actual value worth"* | `monetary_potential` | dollars |

Both can be declared against the same target — that is what #289's multi-kind upsert key
enables, and it is the case this feature will hit constantly. A domain that is *both*
strategically critical and worth real money is the normal case, not the exception.

### The state field

```jsonc
"declared_worth": [
  {
    "label": "Ethical AI Framework",   // matches a core_domain name where possible
    "kind": "strategic",               // strategic | intrinsic | monetary_potential
    "value": "critical",               // a level name, or a number for monetary_potential
    "quote": "…the whole thing is pointless without it"   // what the user actually said
  }
]
```

**`quote` is not decoration.** It is the audit trail that makes a declaration checkable: if a row
cannot be traced to something the owner said, it should not exist. It is also the cheapest
possible test of the say-don't-assign rule — an evaluation can assert that every extracted
declaration has a supporting quote *from the user's turns*, not the assistant's.

---

## 4. ★ The failure mode, and the only thing that really matters here

**An LLM asked to fill in a worth field will fill it in.** If Genesis decides that "Ethical AI
Framework" is `critical` because that reads plausibly, the system has fabricated the exact data
the audit says is worse than none — and the fabricated row is **indistinguishable** from a real
one. Nothing downstream can detect it. The Worth axis would move, the score would look healthier,
and it would mean nothing.

This is not a hypothetical about model behaviour. It is the same failure this repo has already
shipped twice in a different costume: `SOAK_AUDIT` §3 found a learned calibrator "winning" by
memorising a constant, reported as a 0.0000 MAE. Plausible-looking output from a system with no
real signal is the house speciality.

Three defences, in order of how much they actually protect:

1. **Null unless stated.** The existing rule, extended. No level is inferred from tone, emphasis,
   ordering, or how much the user talked about something.
2. **Ask, do not guess.** Where a domain has no worth and the conversation is otherwise complete,
   Genesis *raises the question* — the same way it already decides `synthesis_ready` and says so
   unprompted. An unanswered question leaves the field null and the plan still locks.
3. **Quote or it did not happen.** Every extracted declaration carries the user's words. A
   declaration without a supporting user quote is dropped at lock rather than stored.

Defence 3 is the one that survives prompt drift, because it is enforceable in code rather than in
instructions. **It should be built first, not last.**

---

## 5. Open questions

1. ~~**Does Genesis ask proactively, or only record what is volunteered?**~~ **RESOLVED
   2026-09-07 — ask once, accept silence.** Volunteered-only shipped first, deliberately: it is
   the safe half and a strict prerequisite, and asking before quote-or-drop existed would have
   meant soliciting answers with nothing in place to check them.

   The ask is anchored to the readiness turn — the moment `synthesis_ready` first flips, which
   the merge (`if llm_output.get("synthesis_ready") and not session.synthesis_ready`) makes a
   once-only event. So "ask once" is a property of the conversation, not a rule the model has
   to remember it already obeyed. An unanswered question leaves the field null and the plan
   still locks.

   **Asking opened a hole that volunteering had closed** (§4a).

2. ~~**What is a declaration attached to?**~~ **RESOLVED 2026-09-07.** `domain` added to
   `VALID_TARGET_TYPES`. A labelled declaration targets `domain` with the lowercased domain name
   as `target_id`; an unlabelled one targets `masterplan` with the plan id. `other` would have
   lost the fact that the target is a named part of a plan, making the row unjoinable to
   anything.

3. **Can worth be declared outside Genesis, later?** Worth changes as a plan proceeds — something
   turning out to matter more is a real and important signal. If Genesis is the only entry point,
   that signal is only capturable by starting a new session. This may argue for a small
   *re-declaration* affordance elsewhere, which is a different thing from a blank declaration
   form: it edits an existing statement rather than soliciting a new one.

4. **Does the plan's own goal count as a declaration?** `master_plans` already carries
   `goal_value = 1000000`, `goal_unit = "USD"`, `goal_description = "Financial Freedom"`, set
   deliberately through the anchor route. That is a monetary worth declaration in all but name,
   sitting in scalar columns while `intent_value_declarations` is empty. Reconciling the two is
   listed as open question 6 of `STRATEGY_LAYER_SPEC.md` and is the same problem seen from here.

5. **What happens on revise?** Under `MASTERPLAN_REFINE_VS_REVISE_SPEC`, a revise creates a new
   plan version. Do declarations carry forward, get re-asked, or expire? Worth stated against V1
   may not hold in V2 — but silently carrying it forward asserts that it does.

---

## 4a. ★ What asking broke, and the rule that closed it

While worth was only ever volunteered, a user turn *was* a statement, and quoting one was safe.
The moment Genesis asks, the likely reply is a short assent:

```
assistant  "Is the ethics framework critical to the plan?"
user       "yeah, that one"
```

`"yeah, that one"` is 14 characters, so it clears the length floor. It traces to a genuine user
turn, so excluding assistant turns does not catch it. And it would be recorded as
`strategic: critical` — a declaration whose entire meaning lives in the **assistant's** question,
which is the one thing this module exists to refuse. Asking reintroduced the failure mode
through a door that volunteering had kept shut.

The rule that closes it: **a quote made entirely of agreement and pointing words is agreement,
not a statement.** One content word is enough to pass, because `"that one is critical"` is a
real, brief declaration and must survive — the check rejects only the case where the user
contributed no content at all. A bare figure counts as content: `"worth 50000"` is a
declaration whose only content word is the number.

This is why defence 3 had to exist before defence 2 rather than alongside it. The ask is four
sentences of prompt; the thing that makes the ask safe is code, and it had to be there first.

---

## 6. What shipped, 2026-09-07

| piece | state |
|---|---|
| `declared_worth` in the conversation + import state schemas | ✅ |
| extraction rules — say-don't-assign, quote required, kinds and levels | ✅ (defence 1) |
| **quote-or-drop, enforced in code** (`genesis_worth.py`) | ✅ (defence 3) |
| verification against **user** turns only | ✅ |
| accumulation across turns rather than replacement | ✅ |
| `domain` target type | ✅ |
| materialisation at lock, non-fatal, counts reported in the lock response | ✅ |
| **Genesis raising the question when worth is missing** | ✅ (defence 2) — once, on the readiness turn |
| assent-only quotes rejected (the hole asking opened, §4a) | ✅ |
| a UI surface showing what was declared | ❌ — `GET /apps/analytics/worth/declarations` exists |

Three properties are worth stating plainly, because each is a failure that was one line away:

- **Verification happens on the turn the words arrive**, not only at lock. The stored transcript
  is trimmed to its most recent 200 entries, so a quote from early in a long session stops being
  findable — verifying only at lock would discard a real declaration for a reason unrelated to
  whether it was said.
- **`verified` cannot be self-awarded.** `normalize_entry` rebuilds each entry from
  `label`/`kind`/`value`/`quote` only, so a model emitting `"verified": true` has it discarded
  before anything reads it.
- **Worth accumulates; every other state field replaces.** Each turn's extraction reports only
  what that turn established, so a turn about anything else returns `[]`. Under the generic
  merge that would erase every prior declaration — and a single-turn test would still pass.

One structural note. Masterplan does not import `apps.analytics.*`: it reaches the declaration
through `sys.v1.analytics.declare_worth`, matching the syscall migration that already moved its
task and automation integrations, and pinned by
`test_masterplan_bootstrap_keeps_only_identity_as_direct_app_dependency`. The kinds and levels
are therefore restated in `genesis_worth`, with a test that fails if the two copies drift. The
duplication buys local validation: an invalid kind or level is dropped on the turn it was made,
not raised from a syscall at lock — by which point the words that would let anyone check it are
three screens up.

---

## 7. What this spec does not claim

It does not claim Genesis is the only workable place — only that it is where the statement is
already being made, which makes it the place where a number is a by-product rather than a chore.

It does not claim the feature is safe to build as described. §4 is the whole risk, and defence 3
(quote-or-drop) is the part that must exist before any of this is switched on. A version of this
built without it would produce a Worth axis full of confident, untraceable numbers — which is
strictly worse than the 0 declarations there are today, because today's zero is honest.
