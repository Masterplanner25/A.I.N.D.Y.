# Contributors

Maintainer: **Shawn Knight** — Masterplan Infinite Weave.

This file records contributions from other people that are present in this
repository. It exists because a public thank-you and an in-source attribution are
different things, and only the second survives a `grep` by someone reading the code.

If your work is here and you are not listed, that is an omission, not a position —
please say so and it will be corrected.

---

## Code

### Drew Brown — `apps/authorship`

Author of the **Epistemic Reclaimer**, originally Step 6 of his Scribalicious
Pipeline. Drew shared the project directly and gave permission for its use.

Retained from the original: the `epistemic_reclaim` concept and name, the
`INVISIBLE_WATERMARK` zero-width sequence, the entropy-disruption approach, the
Unicode fingerprint embedding, and the visible signature block. His original guide is
kept in the repository at
`apps/authorship/docs/Collaborative Use Guide - Epistemic Reclaimer.md`.

Adapted for A.I.N.D.Y.: service wrapping, Memory Bridge integration, SHA-256 signing,
and per-originator parameterisation.

### Jonathan Rapsiarda — `apps/arm/services/deepseek`

Author of the **DeepSeek Analyzer**, shared directly and used with permission. It is
the origin of ARM's analysis package; the retained module names —
`deepseek_code_analyzer`, `security_deepseek`, `file_processor_deepseek`,
`config_manager_deepseek` — mark the original structure.

Adapted for A.I.N.D.Y.: rebuilt as ARM's core engine with Infinity Algorithm priority
scoring, PostgreSQL result persistence, memory capture, and syscall-mediated
invocation. Degree of adaptation varies by module — the analyzer is substantially
rewritten, the support modules less so.

---

## Architecture

### Cherokee Schill — the Memory Bridge

The Memory Bridge exists because of a conversation with Cherokee, and the contribution
is larger than the impetus an earlier version of this file recorded. The decision to
treat memory as **continuity and authorship** rather than as storage came from her
framing, and the module has carried the line
`Architected with Solon Protocol Logic | Continuity > Content` in its header since v0.1.

Cherokee's own work is the **Ethical AI Framework**
(<https://github.com/Ocherokee/ethical-ai-framework>) — "a transparent,
non-weaponizable, consent-based ethical AI framework designed to enforce autonomy and
accountability". Consent is her subject, and it is the idea this project took from her.

The module itself lives in the `aindy-runtime` package (`AINDY/memory/bridge.py`),
which this repository depends on; the full entry is in that repository's
`CONTRIBUTORS.md`. No code of Cherokee's is present in either repository, and her work
is not the ancestor of the runtime's capability system.

---

## Adding to this file

Record what was contributed, what was retained, and what was changed. Vague credit is
worse than none: it names a person without letting anyone verify what they did.

Attribution in this repository lives in three places, and all three should agree:

1. this file,
2. the module docstring of the code in question,
3. any original documentation retained alongside it.
