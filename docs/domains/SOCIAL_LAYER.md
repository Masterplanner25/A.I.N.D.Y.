---
title: "Social Layer"
last_verified: "2026-07-05"
api_version: "1.0"
status: current
owner: "apps-team"
---
# Social Layer — Canonical Definition & Evolution Plan

---

## 1. System Definition (Canonical)

The Social Layer is a **public-facing identity and interaction system** that captures profiles, posts, and social signals, then routes them into A.I.N.D.Y. for visibility scoring and continuity.

It is not a memory system.

It is a **social execution layer** designed to:

* represent identity
* surface content
* track interactions
* feed signals into analytics and memory

---

## 2. Core Lifecycle (Canonical Pipeline)

```
Profile → Post → Feed → Signal → Insight
```

### Profile

Identity surface:

* name
* tagline
* trust tier
* metrics snapshot

---

### Post

Content surface:

* user content
* timestamp
* visibility tier
* tags

---

### Feed

Distribution layer:

* posts surfaced by relevance
* trust-tier filtering

---

### Signal

Interaction and reaction capture:

* engagement counts
* ripple or visibility metrics

---

### Insight

Analytics + feedback:

* visibility scoring
* influence tracking
* memory capture

---

## 3. Core Components

---

### 3.1 Profiles

**Implementation:**

* `apps/social/routes/social_router.py`
* `apps/social/models/social_models.py`
* MongoDB storage

**Current Capabilities:**

* create/update profiles
* fetch profile by username

---

### 3.2 Posts + Feed

**Implementation:**

* `apps/social/routes/social_router.py`
* MongoDB storage

**Current Capabilities:**

* create posts
* fetch feed with trust-tier weighted relevance scoring
* track impressions and interaction signals
* record explicit interactions (`view`, `click`, `like`, `boost`, `comment`) via
  `POST /social/posts/{post_id}/interact`
* comment/reply **content** model with threading via
  `POST` / `GET /social/posts/{post_id}/comments`
  (`apps/social/services/comment_service.py`)
* durable per-day metrics history feeding real trend analysis
  (`apps/social/services/social_metrics_history_service.py`)
* expose social analytics summaries

**Missing:**

* none at the Posts + Feed component level — the remaining work is cross-component
  (social/system identity unification)

---

### 3.3 Bridge Integration

**Implementation:**

* `apps/bridge/routes/bridge_router.py` (`/bridge/user_event`)
* `AINDY/server.js` forwards events

**Current Capabilities:**

* Node → FastAPI bridge exists
* `/bridge/user_event` persists to SQL audit table (`bridge_user_events`)
* system/public-origin bridge events are surfaced in the social feed's `events`
  channel (`apps/social/services/bridge_feed_service.py`), origin-gated via
  `SOCIAL_FEED_BRIDGE_ORIGINS`

---

### 3.4 Memory Logging

**Implementation:**

* `apps/social/routes/social_router.py` calls into the Memory Bridge via execution hints

**Current Capabilities:**

* posts are logged to Memory Bridge with DB session
* high/low engagement signals are captured as memory hints

---

### 3.5 Frontend

**Implementation:**

* `client/src/components/app/ProfileView.jsx`
* `client/src/components/app/Feed.jsx`
* `client/src/components/app/PostComposer.jsx`

**Current Capabilities:**

* UI surfaces for profiles + feed
* analytics panel and top-performing content summaries

---

## 4. Architectural Layers

### Storage Layer

* MongoDB (profiles, posts)

### Orchestration Layer

* FastAPI routes
* Node bridge (Express)

### Analytics Layer

* visibility scoring
* trust-tier influence
* engagement and conversion summaries

---

## 5. Current Implementation (Reality)

**Implemented:**

* profile upsert + fetch
* post creation
* feed listing + visibility scoring
* explicit interaction capture (view/click/like/boost/comment counters)
* comment/reply content model with threading
* durable per-day metrics history (real trend analysis, not creation-day buckets)
* Node → FastAPI bridge
* analytics summaries and trend output
* memory-backed performance feedback
* Infinity-facing social performance signals

**Missing:**

* deferred identity-unification follow-ups: metrics projection (`metrics_snapshot`
  ↔ analytics `UserScore`), auto-creating a profile at signup, and the cross-repo
  canonical profile (the username-binding slice is done)

---

## 6. Doc → Code Parity Table

| Documented Capability | Evidence in Docs | Implementation Reality | Status | Primary Files |
| --- | --- | --- | --- | --- |
| Profile CRUD | Social layer notes | Profile upsert + public fetch via MongoDB | Partial | `apps/social/routes/social_router.py`, `apps/social/models/social_models.py` |
| Post creation | Social layer notes | Post insert + list | Implemented | `apps/social/routes/social_router.py` |
| Feed ranking | Roadmap intent | Trust-tier weighted ranking + Infinity score weighting | Implemented | `apps/social/routes/social_router.py` |
| Trust-tier weighting | Roadmap intent | Trust tier weighted relevance scoring in feed | Implemented | `apps/social/routes/social_router.py` |
| Interaction capture (view/click/like/boost/comment counts) | Social layer intent | `POST /social/posts/{post_id}/interact` persists `$inc` counters and refreshes engagement signals | Implemented | `apps/social/routes/social_router.py` |
| Bridge event persistence | Bridge integration notes | `/bridge/user_event` persists to `bridge_user_events` | Implemented | `apps/bridge/routes/bridge_router.py`, `apps/automation/bridge_user_event.py` |
| Bridge events surfaced in feed | Roadmap intent | System/public-origin events read via automation's public API and exposed in the feed's `events` channel; origin-gated by `SOCIAL_FEED_BRIDGE_ORIGINS` | Implemented | `apps/social/services/bridge_feed_service.py`, `apps/social/routes/social_router.py`, `apps/automation/public.py` |
| Canonical username binding | Roadmap intent | Profile + post `author_username` sourced from canonical `users.username` (lazy reconcile on write); null → social-only `username_verified=false` | Implemented | `apps/social/services/identity_binding_service.py`, `apps/social/routes/social_router.py` |
| Memory logging | Social layer notes | Posts logged via Memory Bridge with DB session | Implemented | `apps/social/routes/social_router.py` |
| Comment / reply threads | Social layer intent | `POST`/`GET /social/posts/{post_id}/comments` persist comment text with `parent_comment_id` threading; bump `comments_count` | Implemented | `apps/social/services/comment_service.py`, `apps/social/routes/social_router.py`, `apps/social/models/social_models.py` |
| Durable metrics history | Roadmap intent | Per-(post, day) delta snapshots in `social_metrics_history`; trend rebuilt from history (legacy creation-day bucketing kept as fallback) | Implemented | `apps/social/services/social_metrics_history_service.py`, `apps/social/services/social_performance_service.py` |
| Analytics dashboard | Roadmap intent | Analytics summaries, trends, and top content are exposed in API/UI | Implemented | `apps/social/routes/social_router.py`, `client/src/components/app/Feed.jsx` |

---

## 7. Gap → File Mapping

| Gap | Impact | Files to Update |
| --- | --- | --- |
| Metrics duplication | `metrics_snapshot` (Mongo, written by `task_service`) duplicates analytics `UserScore` | `apps/social/routes/social_router.py`, `apps/tasks/services/task_service.py`, `apps/analytics/public.py` |
| No profile at signup | A user has a system identity (`users`, `UserIdentity`) but no `SocialProfile` until manual upsert | `apps/identity/services/signup_initialization_service.py` (runtime-coordinated), `apps/social/*` |
| Full canonical profile | A single canonical profile both social and identity project from (cross-repo) | `aindy-runtime` |

_Closed: comment/reply content model, durable analytics history, bridge-event surfacing, and canonical username binding are implemented (see Parity Table). Username drift between the Mongo social profile and the SQL `users.username` is resolved; remaining identity work is metrics/lifecycle/cross-repo (see `TECH_DEBT.md` SOCIAL-IDENTITY-1)._

---

## 8. Risk Register

| Risk | Type | Failure Mode | Impact | Likely? |
| --- | --- | --- | --- | --- |
| Heuristic scoring noise | Product | Visibility scores may not reflect true relevance | Medium engagement | Medium |
| Divergent schemas | Technical | Social profile fields drift across code/docs | Inconsistent UI + data | Medium |
| Cross-system mismatch | Integration | Social signals are linked to Memory Bridge, but identity/profile state can still drift across systems | Inconsistent behavior and analytics context | Medium |

---

## 9. System Classification

The Social Layer is currently:

> A social interaction and analytics layer backed by MongoDB with visibility scoring,
> performance feedback, bridge persistence, and threaded comment/reply discussion.
> Identity is bound to the canonical `users.username`; full cross-repo profile
> unification is the remaining scope (see §13 / `TECH_DEBT.md` SOCIAL-IDENTITY-1).

It is NOT:

* an influence graph (that is RippleTrace's domain)
* a fully unified identity system yet — the social profile and system identity still
  project from separate stores pending the runtime-owned canonical profile

---

## 10. Evolution Plan (System Roadmap)

---

### Phase v1 — Stabilize Social CRUD

**Goal:** Stable identity and content flow

**Actions:**

* normalize profile schema
* harden post creation + feed response

**Status:** Complete

---

### Phase v2 — Bridge Persistence

**Goal:** Make bridge events real

**Actions:**

* persist `/bridge/user_event` ✅

**Status:** Complete

---

### Phase v3 — Visibility Scoring

**Goal:** Ranking logic

**Actions:**

* trust-tier weighting ✅
* engagement-based ordering ✅

**Status:** Complete

---

### Phase v4 — Analytics Layer

**Goal:** Social intelligence surface

**Actions:**

* dashboards ✅
* visibility metrics ✅

**Status:** Complete

---

### Phase v5 — Feedback Loop

**Goal:** Continuous improvement

**Actions:**

* feed analytics into scoring ✅
* log visibility outcomes to Memory Bridge ✅

**Status:** Complete

---

## 11. Technical Debt

### Structural

* _Resolved:_ analytics now writes per-(post, day) deltas to `social_metrics_history`;
  trend analysis reads durable history (legacy creation-day bucketing kept only as a
  fallback when no history exists yet).

### Functional

* _Resolved:_ comment/reply content is implemented (`comment_service`); the
  `comments_count` field is now a denormalized count alongside stored comment text.

### Conceptual

* social profile and system identity remain separate layers

---

## 12. Phase Mapping

| Phase | Component           | Status      | Required Action |
| ----- | ------------------- | ----------- | --------------- |
| v1    | CRUD + Feed         | Complete    | Maintenance only |
| v2    | Bridge Persistence  | Complete    | Maintenance only |
| v3    | Visibility Scoring  | Complete    | Maintenance only |
| v4    | Analytics Layer     | Complete    | Maintenance only |
| v5    | Feedback Loop       | Complete    | Maintenance only |

---

## 13. Next Steps

The core phases (v1–v5) are complete. The following are enhancements beyond v5.

### Completed

* **Interaction endpoints** — likes, boosts, and comment counts are persisted
  interactions via `POST /social/posts/{post_id}/interact` rather than dormant
  fields on posts. _(See `apps/social/routes/social_router.py`.)_
* **Comment & reply content model** — stored comment text with `parent_comment_id`
  threading via `POST`/`GET /social/posts/{post_id}/comments`.
  _(See `apps/social/services/comment_service.py`.)_
* **Durable analytics history** — per-(post, day) metric deltas in
  `social_metrics_history`; trends are rebuilt from real history rather than
  collapsing lifetime totals onto a post's creation day.
  _(See `apps/social/services/social_metrics_history_service.py`.)_
* **Bridge-event surfacing** — system/public-origin bridge events read via
  automation's public contract and exposed in the feed's `events` channel,
  origin-gated by `SOCIAL_FEED_BRIDGE_ORIGINS`. The data is automation-owned, so
  the dependency is `APP_DEPENDS_ON: ['automation']` (not `bridge`).
  _(See `apps/social/services/bridge_feed_service.py`.)_ Frontend rendering of the
  `events` channel remains a follow-up.
* **Canonical username binding** — `SocialProfile.username` and post
  `author_username` are sourced from the canonical `users.username` (source of
  truth) at write time, with lazy reconcile; when `users.username` is null the
  social username is kept and flagged `username_verified=false`. The runtime
  `users` table is never written from the social app.
  _(See `apps/social/services/identity_binding_service.py`.)_

### Remaining (identity follow-ups — see `TECH_DEBT.md` SOCIAL-IDENTITY-1)

#### Metrics projection
Make `SocialProfile.metrics_snapshot` a read-through projection of analytics
`UserScore` and retire `task_service`'s direct Mongo metric write.

#### Profile lifecycle at signup
Ensure a `SocialProfile` exists for every user (coordinate with the runtime
signup path), rather than creating it lazily on first upsert.

#### Full canonical profile (cross-repo)
A runtime-owned canonical profile that both social and identity project from —
requires changes in `aindy-runtime`.

#### Per-user bridge-event scoping
Now unblocked by username binding: scope feed bridge events to the viewer when
desired, beyond the current system/public-origin gate.

---

## 14. Governance Notes

* This document is the **canonical reference** for the Social Layer.
* Any deviations must be recorded in:

  * `TECH_DEBT.md`
  * `docs/architecture/EVOLUTION_PLAN.md`

---

## 15. Summary (Operational Truth)

The Social Layer is not complete when posts are stored.

It is complete when:

> Social activity produces visibility signals, those signals affect ranking, and outcomes are captured as memory and analytics.
