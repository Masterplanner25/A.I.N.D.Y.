# A.I.N.D.Y.

**AI Native Development & Yield** — a persistent execution partner.

A.I.N.D.Y. is not a chatbot. A chatbot answers and forgets; A.I.N.D.Y. acts, records what
happened, and lets the record change what it does next. It is built around the **Infinity
Algorithm** — a scored model of how you actually execute — and everything else in this repository
exists either to feed that algorithm or to act on what it says.

**This repository is A.I.N.D.Y. itself:** sixteen domain applications and the client. It is *not*
the runtime it executes on, and that difference matters more than it looks — see
[Three layers, three names](#three-layers-three-names).

---

## Where this sits: the Masterplan Infinite Weave

The **Masterplan Infinite Weave** is the ecosystem-level architecture — the canonical root.
It is not a product, not a framework, and not a theory. It is the system that integrates
execution, memory, intelligence and scale into a continuous feedback loop, with one purpose:

> to compress the time between **idea → execution → validation → compounding insight**.

Everything else exists inside it, A.I.N.D.Y. included. A.I.N.D.Y. is the Weave's execution
partner — the layer where intent becomes action and action becomes a record worth learning from.
Read the Infinity Algorithm as that compression made measurable: the score is what
*validation → compounding insight* looks like when you can actually see the number move.

The Weave is ecosystem canon and is deliberately **not** described further here. This README
documents what is verifiable in this repository, and canon that cannot be checked against code is
exactly the kind of framing that goes stale in a README.

> **Second naming trap.** `apps/masterplan` in this repo is a *domain* — plans, goals, and the
> `masterplan_progress` KPI. It is not the Masterplan Infinite Weave. One is a module inside
> A.I.N.D.Y.; the other is the ecosystem A.I.N.D.Y. sits inside. This repo contains the first.

---

## What it is for

The point is the Infinity Algorithm. The owner's framing: *"the main thing I wanted was to be able
to use the Infinity algorithm — that's the product. The question is how is everything else feeding
it."* That is the sorting rule for work in this repo — **does it feed the algorithm?**

The partner loop, and where each step actually lives:

| The claim | What performs it |
|---|---|
| Converts intent into action | `apps/tasks`, plus the planner and agent runs in `apps/agent` |
| Converts action into memory | `system_events`, `apps/memory`, and the append-only `score_history` |
| Converts memory into leverage | the score in `apps/analytics/services/scoring/infinity_service.py` and the support loop in `infinity_loop.py` |
| Converts leverage into repeatable velocity | scheduled jobs, `apps/automation`, `apps/arm` |

The master score is a weighted average of five KPIs. The weights live in code, at the top of
`infinity_service.py` — this table is a pointer, not the source of truth:

| KPI | Weight | Fed by |
|---|---|---|
| `execution_speed` | 0.25 | tasks (14-day rolling velocity) |
| `decision_efficiency` | 0.25 | tasks + ARM |
| `ai_productivity_boost` | 0.20 | ARM |
| `focus_quality` | 0.15 | watcher (runtime-owned) |
| `masterplan_progress` | 0.15 | masterplan + tasks |

### The rule that keeps this honest

Product framing goes stale; the question does not. For any domain in this repo, ask which of three
things is true:

1. **It feeds the score** — it moves one of the five KPIs above.
2. **It feeds the loop** — it is visible to `gather_support_state`
   (`apps/analytics/services/orchestration/support_state.py`), so it can shape what you are *told*
   to do without moving your number.
3. **It feeds neither** — it exists, it may be substantial, and it is not yet wired to the point.

All three are real categories here, and the third is not hypothetical. *Carried* is also not the
same as *acted on*: a signal can ride in `loop_context` while nothing reads it. The current map is
maintained in [`docs/infinity/INFINITY_ALGORITHM_SUPPORT_SYSTEM.md`](docs/infinity/INFINITY_ALGORITHM_SUPPORT_SYSTEM.md)
and [`docs/infinity/INFINITY_SCORE_MODEL.md`](docs/infinity/INFINITY_SCORE_MODEL.md) —
check those rather than trusting a list in a README.

---

## Three layers, three names

Inside the Weave, execution nests three deep:

```
Masterplan Infinite Weave        the ecosystem — canonical root
└── A.I.N.D.Y.                   the persistent execution partner   <- this repository
    └── aindy-runtime            the substrate that makes it function
        └── Nodus (nodus-lang)   the programmable execution layer
```

The most common error in describing this system is collapsing the inner three into one:

| Layer | Name | What it is | Where it lives |
|---|---|---|---|
| The partner | **A.I.N.D.Y.** | The product. Sixteen domains, the client, the Infinity Algorithm. What a person actually works with. | **this repository** |
| The substrate | **`aindy-runtime`** | Execution pipelines, scheduling, the event bus, syscalls, memory infrastructure, the registration surface. What makes A.I.N.D.Y. able to function. | published package, separate repo |
| The execution layer | **Nodus** (`nodus-lang`) | A programmable execution runtime — modular, versioned, traceable units with real state transitions. | a dependency **of the runtime**, not of this repo |

Two consequences worth stating plainly, because both get written down wrong:

**A.I.N.D.Y. is not the execution engine.** It is the partner. The runtime is the engine, and Nodus
is what the engine executes. Calling A.I.N.D.Y. the execution engine skips the layer that does the
work.

**Nodus does not sit directly underneath A.I.N.D.Y.** There is a layer in between. This repository
declares exactly one runtime dependency and never names `nodus-lang`; the runtime is what depends
on it. Verify both halves rather than believing this paragraph:

```bash
grep -n "aindy-runtime\|nodus" pyproject.toml     # this repo: aindy-runtime only
pip show aindy-runtime | grep -i requires         # the runtime: nodus-lang is in here
```

**The naming trap.** The runtime's importable Python package is literally `AINDY/`. So `AINDY/` in
an import statement means *the runtime*, while "A.I.N.D.Y." in a sentence means *the product*. That
collision is why the two get conflated, and it is worth reading twice before writing a sentence
about either.

---

## The surface

Sixteen domains, registered as plugins at boot:

`tasks` · `analytics` · `arm` · `authorship` · `automation` · `autonomy` · `dashboard` ·
`freelance` · `identity` · `masterplan` · `memory` · `network_bridge` · `rippletrace` ·
`search` · `social` · `agent`

**Three are core** (`IS_CORE_DOMAIN = True`): `tasks`, `identity`, `analytics`. If one of them
fails to register, startup fails. Every other domain is a degradable peripheral — startup continues
with a warning, which is deliberate: losing the social feed should not cost you the system.

The client serves the partner surface — `/genesis`, `/tasks`, `/kpi`, `/masterplan`, `/memory`,
`/arm/*`, `/search/*`, `/identity`, `/freelance`, `/social`, `/rippletrace`, `/dashboard` — plus a
separate operator SPA under `/platform/*` for the control plane. The two are **separate builds**:
`build:app` does not compile `platform.html`.

---

## Architecture

### Plugin registry

The runtime exposes a registration surface and apps call it at startup. **The runtime never imports
`apps.*`.** Each domain's `bootstrap.py` declares `BOOTSTRAP_DEPENDS_ON` (boot order),
`APP_DEPENDS_ON` (cross-domain imports, AST-validated), and `IS_CORE_DOMAIN`, then calls
runtime-owned `register_*` functions. `apps/bootstrap.py` topologically sorts the graph.

Full pattern: [`docs/architecture/PLUGIN_REGISTRY_PATTERN.md`](docs/architecture/PLUGIN_REGISTRY_PATTERN.md).

### Boot profiles

| Profile | Manifest | Plugins loaded |
|---|---|---|
| `platform-only` | `AINDY/runtime_plugins.json` | none |
| `default-apps` | `./aindy_plugins.json` | `apps.bootstrap` → 16 apps |

Running from this repo root selects `aindy_plugins.json` automatically.

### Import boundaries (CI-enforced)

- `AINDY/` must never import `apps.*`
- apps reach the runtime only through declared public contracts
- cross-app imports must be declared in the importing app's `APP_DEPENDS_ON`

```bash
python scripts/check_app_imports.py    # currently: 37 declared, 0 undeclared
```

---

## Install

```bash
python -m pip install -e . --no-build-isolation   # resolves aindy-runtime from PyPI
```

The runtime dependency is declared in `pyproject.toml` as a **bounded** range
(`aindy-runtime>=2.4.1,<3.0`). Never widen it to an unbounded range. Note that the floor is only a
floor: a build resolves to the newest minor in range, which is not necessarily the version this
repo has formally adopted — see `RUNTIME-PIN-FLOAT-1` in [`TECH_DEBT.md`](TECH_DEBT.md).

For local development against a sibling runtime checkout:

```bash
python -m pip install -e ../aindy-runtime --no-deps --no-build-isolation
python -m pip install -e . --no-build-isolation
```

`--no-deps` stops pip from overwriting the editable runtime with the published one.

## Boot

```bash
aindy-runtime serve      # run from the repo root so aindy_plugins.json is discovered
```

`aindy-runtime serve` **self-migrates the runtime schema at boot**, which is why moving to a new
runtime version is not a free experiment. App-owned migrations are run separately
(`alembic upgrade head`); see [`docs/operations/MIGRATION_POLICY.md`](docs/operations/MIGRATION_POLICY.md).

Full local stack (api plus datastores) — both compose files and both profiles:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.mongo.yml \
  --profile full --profile mail up -d
```

Both compose files are required on every `up`: the overlay is what sets `MONGO_URL`. `redis` sits
behind the `full` profile and `mailpit` behind `mail`, so omitting them produces a stack that
reports healthy while the api cannot reach redis.

## Verify

```bash
# app-profile subset, no live server required
pytest tests/unit/test_app_manifest_bootstrap_contract.py \
       tests/unit/test_import_boundaries.py \
       tests/unit/test_runtime_agent_api_ownership.py \
       tests/unit/test_tasks_public_contract.py \
       tests/unit/test_analytics_public_contract.py \
       tests/unit/test_app_model_registration.py \
       tests/test_bootstrap_completeness.py -m app_profile -q

python scripts/check_app_imports.py     # cross-app import boundaries
python scripts/check_api_reference.py   # API reference drift
```

A healthy app-profile boot reports `boot_profile=default-apps`, `app_plugins_loaded=True`, and
`app_plugin_count=16` on `GET /api/version`.

---

## Ownership

This repo owns `apps/`, `client/`, `aindy_plugins.json`, `alembic/`, and app-profile tests and
docs. It does **not** own `AINDY/` — runtime code, runtime entrypoints, and runtime-only docs live
in `aindy-runtime` and arrive as a published dependency.

The practical consequence: **when an app needs something the runtime does not expose, the answer is
a runtime feature request, not an edit to `AINDY/`.** Open requests live in
[`docs/runtime/RUNTIME_FEATURE_REQUESTS.md`](docs/runtime/RUNTIME_FEATURE_REQUESTS.md).

## CI

`.github/workflows/app-ci.yml` installs the runtime from PyPI as a normal pinned dependency and
verifies the installed version at boot — no runtime-repo checkout. It runs ruff, docs frontmatter
and API-contract drift checks, the app-profile suite, cross-app import boundaries, bootstrap
dependency validation, the route execution-pipeline contract, the frontend unit suite, and a client
Docker build smoke.

Ownership guidance: [`docs/operations/CI_OWNERSHIP.md`](docs/operations/CI_OWNERSHIP.md).

## Contributing

- protected branch `main`; PRs target `main`; branch from current `main`
- `python scripts/check_app_imports.py` must pass before any PR
- known debt and open defects: [`TECH_DEBT.md`](TECH_DEBT.md)
- forward roadmap: [`docs/architecture/BUILD_PLAN.md`](docs/architecture/BUILD_PLAN.md)
