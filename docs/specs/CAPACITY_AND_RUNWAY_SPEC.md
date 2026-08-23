---
title: "Capacity and runway — money as feasibility, not as score"
last_verified: "2026-08-16"
api_version: "1.0"
status: current
owner: "app-team"
---

# Capacity and runway — money as feasibility, not as score

**Status:** spec, not started. Written 2026-08-16.

---

## 1. The question, and why it kept feeling intractable

> *"It should be both — your economic reality matters to the plan and it can give value to the
> plan. But it depends on what happens as well: a paycheck this week, but you spend it by Monday,
> versus save it for a month… humans are hard to model when it comes to money."*

Two different questions were sharing one word. Separated, both become tractable:

| | Question it answers | Nature | Belongs to |
|---|---|---|---|
| **Attribution** | Did the plan *produce* value? | Flow — a discrete event | **Worth axis** (scoring) |
| **Capacity** | Can I *afford* to run the plan? | Stock — a balance over time | **Feasibility** — never the score |

**A paycheck does not make the plan more valuable. It makes it more affordable.** That is why
salary felt like it belonged and simultaneously didn't. Fold it into Worth and the score reports
"you're winning" every payday, which is precisely backwards — it would reward income the plan had
nothing to do with.

**The spent-Monday vs saved-a-month example is the proof.** Identical income, identical
attribution, completely different runway. The variable being pointed at is not the earning — it is
the *persistence*. Which means the thing worth modelling was never revenue.

---

## 2. Do not model the human

Modelling spending psychology — will they save it, what does a "big spend" mean to them — is both
very hard and unnecessary. **Model the observable outcome, not the behaviour that produced it:**

```
runway_months = liquid_balance / monthly_burn
```

The system never needs to know *why* money moved. It needs to notice that runway changed. That
sidesteps the intractable part entirely and leaves a two-number model a person can actually
maintain.

---

## 3. What exists today — audited 2026-08-16

**Nothing usable.** `capital` and `expenses` appear only as inputs to the manual what-if
calculators (`analytics/metrics_models.py`, `analytics_inputs.py`, feeding `income_efficiency` and
`business_growth`). `KPI_DASHBOARD_WIRING.md` classifies those 13 input tables as **dead schema**
— *"imported only for `Base` registration, never written"* — and the owner's 2026-07-30 decision
parked them behind a labeled drawer. Confirmed live: `efficiencies` 0 rows, `business_growths`
0 rows, `revenue_metrics` 0 rows.

There is **no balance, no burn rate, no runway, and no concept of money persisting** anywhere in
`apps/`.

Separately, `realized_revenue` is sourced only from the freelance syscall
(`three_axis_service.py:189`), so non-freelance income has no representation at all — the gap
recorded in `SOAK_AUDIT_2026-08-15.md` §8. **This spec does not close that gap**; it makes it less
urgent by routing economic reality somewhere more useful than Worth.

---

## 4. Where this actually pays off — an inert system, activated

The architecture map's standing finding (folded into `BUILD_PLAN.md`): **risk posture is "sensed,
not actuated."** `determine_posture()` computes a four-branch posture from `ambition_score`, it is
persisted and displayed, and *nothing consumes it to steer anything*.

Runway is plausibly the missing half:

> An aggressive posture with **two weeks** of runway and an aggressive posture with **twelve
> months** are entirely different propositions. The system currently cannot tell them apart —
> which may be exactly why the posture output has never been worth acting on.

So this is not a new pillar. It is the missing input to one that is already built and idle. That
framing should survive into implementation: **if runway does not change what posture means, this
feature has not landed.**

---

## 5. Design

### 5.1 Declared, not tracked

No bank integration, no transaction ingest, no spending inference. The user states two numbers and
refreshes them occasionally.

This fits the system's existing grain: it already separates **declared** from **observed**
everywhere, and `intent_value_declarations` is the precedent — a user-stated prior that feeds a
computation without pretending to be measured truth.

It also leaves room to grow correctly. If a real feed ever arrives, runway becomes *observed*, and
the gap between declared and observed is itself a signal — the same Breakout/Anomaly divergence
structure as `SELF_TRUST_CALIBRATION_SPEC.md` §2. Designing it as a declaration now keeps that
door open; designing it as an integration now closes it.

### 5.2 The model

New app-owned table, `capacity_declarations`, owned by `masterplan` (it serves plan feasibility,
not analytics scoring — and putting it in `analytics` would invite someone to score it):

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `user_id` | uuid, indexed |
| `liquid_balance` | float — what is actually available, not net worth |
| `monthly_burn` | float — committed outgoings per month |
| `currency` | `String(3)`, default from user locale; **do not assume USD** |
| `as_of` | date the user is asserting this was true |
| `source` | `declared` \| `observed` — `declared` for now; the growth path in §5.1 |
| `note` | free text ("post-payday", "after the laptop") |
| `created_at` / `updated_at` | append-only history — never update in place, see below |

**Append-only, deliberately.** Each entry is a dated observation, not a mutable current value.
That gives runway a *trend* for free, which is what makes it interesting: runway falling for three
months is a far stronger signal than a single number, and it is the only way `source` divergence
can ever be computed.

### 5.3 Derived

```
runway_months = liquid_balance / monthly_burn          # None when burn <= 0
staleness_days = today - as_of
```

Both computed on read. **Runway is never persisted** — a stored runway silently ages into a lie,
and the whole point of `as_of` is that the system knows how old the claim is.

### 5.4 What consumes it

- **Posture (advisory first).** Runway band annotates the existing posture rather than replacing
  it: *"aggressive posture, 1.4 months runway"*. Advisory only until it has been watched for a
  while — the same rollout discipline as three-axis and learned recursion, and with §7 of the soak
  audit in mind.
- **The plan surface.** Runway and its trend shown where the plan is, not on a finance page.
- **Explicitly NOT the Infinity score.** Not Worth, not master_score, not any axis. Capacity is
  not achievement. This is the load-bearing constraint of the whole spec.

---

## 6. Reminders — the feature does not work without them

Declared data decays. A runway number from six weeks ago is worse than no number, because it looks
current. **So the prompt to refresh is part of the feature, not a nicety.**

### 6.1 Staleness is computed, not pushed — start here

The cheapest correct version needs **no scheduler and no delivery channel**: `staleness_days` is
derived on read, so any surface that shows runway can also show *"last updated 34 days ago —
still right?"* with an inline update control.

This covers the common case (the user is in the app) at near-zero cost and cannot spam anyone.
**Phase 1 is exactly this and nothing more.**

### 6.2 Scheduled reminders — the hook exists and is unused

`register_scheduled_job(job_id, handler, *, trigger="interval", trigger_kwargs=...)` is a real,
exported runtime hook (`registry.py:744`, backed by APScheduler).

> **Corrected 2026-08-16.** An earlier draft of this section claimed no app in this repo calls it
> and that a reminder job would be the first scheduled job ever registered here. **That was
> wrong** — the error was grepping for `register_scheduler_job(s)`, the stale name in `CLAUDE.md`,
> rather than the real one. There are **21 call sites registering 9 jobs** across four domains:
>
> | Domain | Jobs |
> |---|---|
> | `analytics` | `daily_infinity_score_recalculation` |
> | `masterplan` | `daily_eta_recalculation` |
> | `rippletrace` | `rippletrace_poll_content_sources`, `rippletrace_detect_mentions` |
> | `tasks` | `task_reminder_check`, `task_recurrence_check`, `background_lease_heartbeat`, `wait_recovery_poll`, `resume_watchdog` |

**This changes the plan for the better.** `task_reminder_check` already exists and already runs on
a schedule, so §6.2 is not a new capability — it is **extending an existing reminder job with a
second check**. Phase 4 shrinks accordingly.

It also means scheduled work here is not free: `SYSMAX-5` (runtime, open) notes ~33 jobs sharing a
10-worker pool once these 21 sites are counted alongside the runtime's 12. Adding a job is cheap;
adding a *slow* one is not.

Delivery: transactional email works as of runtime 2.0.1 (`AINDY_SMTP_*`, verified end-to-end
against Mailpit). Reserve it for genuinely time-based prompts — payday, month-end — and keep
everything else in-app.

### 6.3 Guides — prompt at the moment, not in a manual

The request was for guidance attached to the action:

> *"add your payday so you can check on x, y, z"* · *"after a big spend, check your account and
> add it here"*

Two rules keep this from becoming clutter:

1. **A prompt must name what it unlocks.** Not *"keep your data current"* but *"update this and
   the plan can tell you whether the aggressive posture is still affordable."* A reminder that
   cannot say what it buys should not fire.
2. **Prompt on plan-relevant events, not on a calendar.** The user's own qualifier —
   *"especially if it's around the business or plan or will affect your business or plan"* — is
   the filter. A weekly nag is ignored within a fortnight; a prompt after locking a new MasterPlan
   phase is not.

Candidate triggers, all deriving from state the system already has:

| Trigger | Prompt |
|---|---|
| `as_of` older than N days | *"Runway is from 34 days ago. Still about right?"* |
| A MasterPlan phase locks | *"This phase assumes ~4 months. You last logged 1.4 months runway."* |
| Posture is aggressive **and** runway is short | *"Aggressive posture, under 2 months runway — is that deliberate?"* |
| A recurring date the user set (payday) | *"Payday — worth a 30-second update."* |

> **This is `COGNITIVE_OPERATIONS_SPEC.md` §3 applied to data entry: the system names the
> operation.** The user should never have to remember to maintain runway; the system knows when
> the number went stale and what decision it is currently blocking. Same anti-chatbot move — it
> can prompt specifically because it holds the state.

### 6.4 Do not

- No streaks, no badges, no "you haven't logged in for 3 days." This is a plan instrument, not a
  habit tracker, and gamifying an honesty-dependent input is actively harmful.
- No prompt that fires when nothing downstream would change.
- No push channel before §6.1 is shipped and has proven it isn't enough.

---

## 7. Rollout

1. **Phase 1 — model + entry + staleness.** Table, migration, service, `POST`/`GET` routes, a
   small entry surface, runway and staleness rendered on the plan. In-app staleness prompt only
   (§6.1). No scheduler, no email, no posture wiring.
2. **Phase 2 — posture annotation, advisory.** Runway band annotates posture, read-only, behind
   `AINDY_CAPACITY_ADVISORY` (default off).
3. **Phase 3 — contextual prompts.** The event triggers in §6.3, in-app.
4. **Phase 4 — scheduled reminders.** First use of `register_scheduled_job`; email only for
   genuinely time-based prompts.
5. **Phase 5 — non-freelance income** (`SOAK_AUDIT` §8), if still wanted. Deliberately last:
   runway may already answer what that gap was really about.

Phases 1–2 are the honest minimum. Phase 4 should not start until there is real data to remind
about — reminders about an empty table are the same category error as soaking an idle stack.

---

## 8. What this does not do

- **Does not unblock the soaks.** Worth still needs value declarations; Trajectory still needs
  estimated tasks run start→complete. This is a better product, not a faster gate — and it must
  not be sequenced as if it were one.
- Does not enter Worth, `master_score`, or any Infinity axis.
- Does not model spending behaviour, categorise transactions, or forecast cash flow.
- Does not touch bank accounts, ever, in any phase described here.
- Does not resolve whether non-freelance income belongs in Worth. §5 of the soak audit poses that
  fork; this spec routes economic reality to feasibility so the fork can be decided calmly rather
  than by default.

---

## 9. Open questions

- **What is "burn" for someone with irregular income?** A monthly figure assumes a rhythm that
  freelance and salary-plus-side-income do not have. A trailing average needs transaction data we
  are deliberately not collecting.
- **Does a stale runway degrade, or just get flagged?** A number from 90 days ago is nearly
  worthless, but silently decaying it toward zero would be inventing data — the exact failure mode
  §6 of the soak audit warns about.
- **Whose money is it?** Personal runway and business runway are different instruments and the
  distinction matters for anyone with a company. Modelled here as one number, which is probably
  wrong and is cheap to split later via `source`.
- **Currency.** One field is easy; multi-currency, conversion and historical rates are not. Single
  currency per user is assumed and should be stated in the UI rather than silently.
- **Does the reminder cadence need to be user-set?** §6.3 infers triggers from state. A payday
  date is the one genuinely user-known fact the system cannot derive, and is the only argument
  here for a settings surface.
