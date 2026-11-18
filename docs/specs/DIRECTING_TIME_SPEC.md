---
title: "Directing time"
last_verified: "2026-11-16"
api_version: "1.0"
status: draft
owner: "app-team"
---

# Directing time: the person's attention while an agent does the work

**Status:** scoped 2026-11-16; §8 decided the same day (all seven as recommended; 6 resolved to FR-70). Phase A built
2026-11-16. FR-70 shipped in runtime 2.37.0 (2026-11-18): the route takes the watcher key, so phase B is unblocked.

**Origin.** On 2026-11-16 the watcher's signal volume fell from 100–270 a day to 10–35. The watcher was working
correctly: the owner's time at the laptop had become prompting Claude Code and watching it work. The watcher counts
keyboard and mouse input. One keystroke followed by more than 5 minutes without input ends a session at `input_idle`,
backdated to the last input, so these read as 0-second sessions (11-15: four sessions, 0 minutes). **Supervising an
agent reads as idle.**

The owner asked whether A.I.N.D.Y. should measure when they are using it, or when the agent is working. The answer
recorded with this spec: **`focus_quality` stays a measure of the person's own attention.** Agent work is measured by
its outputs, credited to the agent (`TERMINAL_AGENT_SCOPE.md`). The person's prompts to an agent are timestamped acts
of direction, and they are visible. The owner chose an **app-side** build with a **live hook plus a transcript
backfill** (2026-11-16).

---

## 1. What exists (read 2026-11-16)

- **The watcher** (`aindy-sdk` `aindy-watcher` 1.2.1) posts six signal types to the runtime's `POST /watcher/signals`.
  The type list is fixed (`AINDY.watcher.constants.VALID_SIGNAL_TYPES`), with no extension hook. Rows land in
  `watcher_signals`, the `automation` domain's model. `calculate_focus_quality`
  (`apps/analytics/services/scoring/infinity_service.py`) scores `session_ended`, `distraction_detected` and
  `focus_achieved` over the scoring window.
- **Claude Code transcripts:** `~/.claude/projects/<repo>/<session>.jsonl`, one JSON object per line. A prompt the
  person typed is `type: "user"` with string `message.content`, plus a `uuid`, a `sessionId` and an ISO `timestamp`.
  Claude Code keeps about 30 days of them.
  - On this laptop (read 2026-11-16): 21 transcripts across 17 repos, back to 2026-10-10. **749 lines are typed
    prompts** (746 text, 3 with an image). The other ~9,700 `user` lines are tool results (9,393), task
    notifications (217), local commands, compaction summaries and skill loads. A first count of 1,004 included the
    task notifications and similar lines, so §2's exclusions matter.
- **Claude Code hooks:** `UserPromptSubmit` runs a command on every prompt. It receives JSON on stdin with
  `session_id`, `transcript_path` and `cwd`. A hook that fails or times out must not block the prompt.
- **What is not covered:** claude.ai and ChatGPT keep no local transcript. The Collaborator's messages are already in
  A.I.N.D.Y.'s own tables (phase C covers them).

## 2. What a directing event and a directing session are

- **A directing event** is one prompt the person sent an agent. It stores:
  - `user_id`, `source` (`claude_code` for now), and `project`, the transcript's folder name (e.g.
    `C--dev-aindy-apps-monolith`);
  - `agent_session_id` and `occurred_at`;
  - `agent_until`: the last transcript timestamp before the next typed prompt, the end of the agent's work on this one
    (decision 2), counting only the agent's own lines: assistant messages and tool results. Claude Code's bookkeeping
    lines (`api-request` written as the person submits, `system` `away_summary` while they are away, `turn_duration`,
    `pr-link`, `attachment`) would stretch it to the next prompt, which was measured on 11-16 before the rule. It is
    unknown while the agent works, and a later ingest moves it on, never back;
  - `source_event_id`, the transcript line's `uuid`. This is unique per user, and it is what makes ingestion
    idempotent.
  - **The prompt's text is never stored or sent** (decision 3).
- **A directing session** is a run of directing events in which no gap between consecutive prompts exceeds **T**
  (decision 1). It is derived when read, and never stored as truth.
  - It runs from the first prompt to the end of the agent's work after the last prompt: the last assistant line before
    the next gap, capped at T (decision 2).
  - Within one agent session, consecutive prompts chain. Two agent sessions chain if they overlap or touch within T.
- **Not counted as a prompt:** lines that are not the person typing:
  - tool results, `isMeta` lines;
  - `isSidechain` (a subagent's prompt, written by the main agent) and `isCompactSummary` lines;
  - text starting `<command-name>`, `<command-message>`, `<command-args>`, `<local-command-…>`,
    `<task-notification>`, `<system-reminder>`, `[Cross-session delivery notice]` or `[Request interrupted`.
  - A prompt with an image is a list holding a `text` block and no `tool_result`, and counts.
  - The parser has a fixed exclusion list with a test per case.

## 3. Capture: one ingester, two triggers

Both triggers call the **same ingester**: read a transcript, extract the prompt lines, and post the new ones. Keyed on
the line `uuid`, the hook and the backfill can overlap, and a run after an outage fills the gap.

1. **The live hook.** A `UserPromptSubmit` entry in the user-level `~/.claude/settings.json` (all repos) runs
   `scripts/directing_hook.py`. It reads `transcript_path` from stdin and ingests that file's tail.
   - It **always exits 0**, with a short timeout (≤ 3 s) and no output on stdout.
   - If the api is down, it does nothing: the next run, or the backfill, picks the prompts up.
   - The hook fires before the prompt it reports is written to the transcript. So each prompt is ingested by the next
     prompt's hook, and the session's last prompt by the backfill. Phase B checks this ordering live, and if the
     prompt is in the file, it is ingested at once. **Seen 2026-11-16:** a prompt was in the transcript by the time
     the agent's first tool call ran, which suggests it is written before the hook fires; phase B confirms it in the
     hook itself.
2. **The backfill.** `scripts/directing_backfill.py [--since DATE] [--dry-run]` walks every transcript under
   `~/.claude/projects/`. It runs once at build (back to 10-10), then from the watcher's sign-in task daily. The dry
   run is the default, as with `memory backfill-paths`.

**Transport:** `POST /apps/directing/events`, a batch of up to 500 events, owned by the `automation` domain (it owns
`watcher_signals`). It answers `{accepted, duplicates}`. The caller is the authenticated user. A payload `user_id` is
ignored (DEC-103).

## 4. How it is read

- **`GET /apps/directing/sessions?from&to`:** the derived sessions (start, end, minutes, prompts, projects).
- **`GET /apps/directing/summary?days=N`:** directing minutes per day beside the watcher's tracked minutes per day.
  This is the comparison phase D needs.
- **Shadow measure only.** `analytics` computes `directing_minutes` (per day, over the scoring window) and records it
  next to `focus_quality` in the score's KPI snapshot, **read by nothing** (decision 5). `focus_quality` does not
  change.

## 5. What the person sees

- On the KPI page, under Focus quality, a line: *"Directing agents: 3 h 10 m over 6 sessions this week (not in the
  score)."* It is shown only when there are events.
- No new page. The sessions route is for the phase D read.

## 6. Privacy and safety

- **Text never leaves the laptop.** The ingester sends timestamps, ids and the folder name only. A test asserts that the
  payload carries no `content`.
- **The hook cannot break Claude Code:** it always exits 0, has a timeout, prints nothing, and makes no network call
  except to `127.0.0.1`.
- **Project names are folder names.** A repo the person would rather not see is filtered with an ignore list in the
  ingester's config (decision 7), and the ignored events are never sent.

## 7. What it does not do

- It does not change `focus_quality`, the watcher, or `idle_timeout`.
- It does not measure the agent's work. That is `TERMINAL_AGENT_SCOPE.md`: outputs, credited to the agent.
- It does not read claude.ai or ChatGPT.
- It does not infer attention between prompts beyond T. A long silence ends the session.

## 8. Decisions: the owner's, **all seven taken 2026-11-16, as recommended**

1. **The gap T that ends a directing session.** Recommended: **20 minutes.** On 11-16, prompts after 02:16Z came 1–11
   minutes apart while work ran. One gap was 25 minutes (01:51 → 02:16Z), a 15-minute dependency-merge loop the
   owner was not needed for. 20 minutes counts the first stretch as one session and splits at the second, which is
   the honest reading.
   - Alternatives: 10 minutes (stricter); 30 minutes (would bridge that wait).
2. **The session's end.** Recommended: **the agent's last line after the last prompt, capped at T.** The person is on
   call while the agent works on their last instruction.
   - Alternative: end at the last prompt (undercounts every session by its final stretch).
3. **What an event carries.** Recommended: **no text, no length.** Timestamp, ids and project only.
   - Alternative: the prompt's length, as a rough effort signal. It is not needed for the measure.
4. **Sources.** Recommended: **Claude Code now; the Collaborator's messages in phase C**, since they are already in
   A.I.N.D.Y.
   - Alternative: Claude Code only.
5. **Score effect.** Recommended: **none yet.** Record `directing_minutes` as a shadow beside `focus_quality` for at
   least two normal weeks. Then the owner decides whether it joins focus quality, gets its own KPI, or feeds
   `ai_productivity_boost` (as Goals decision 6).
   - Alternative: blend now.
6. **The hook's key.** The runtime's watcher keys are scoped to `watcher.signals`, and phase A checks whether an app
   route can require that scope. Recommended: **reuse the watcher key** (`~/.aindy/watcher_key`) if the scope check is
   available to app routes; **otherwise mint a dedicated key** with the narrowest scope that reaches
   `/apps/directing/events`. If neither exists, file a runtime FR for an app-registrable key scope.
   - Never a full-access key.
   - **Resolved in phase A: neither exists.** The runtime admits a watcher-only key only on its own `/watcher` routes
     (`_resolve_platform_key_as_user(..., allow_watcher_only=True)` is private). A dedicated key is not narrow: any
     non-watcher-only key passes `get_current_user`, and only 7 of 147 routes check a scope. **FR-70 filed.** The
     route takes a session or a non-watcher key until then, through one seam (`_directing_caller`), and phase B's hook
     waits on FR-70.
   - **FR-70 shipped in runtime 2.37.0** (DEC-133, the runtime chose our option 1): `_directing_caller` now depends on
     `get_activity_caller`, which admits a session or a key holding `watcher.signals`. The hook uses the person's
     watcher key.
7. **Which repos count.** Recommended: **all**, with an ignore list (empty by default). Research repos are still the
   person directing work.
   - Alternative: an allow list.

## 9. Phases

| Phase | What | Schema |
|---|---|---|
| **A** ✅ **built 2026-11-16** | The table, the ingest route, the transcript parser and its exclusion tests; the key question (decision 6) answered. As built:
  - `apps/automation/directing.py` (`DirectingEvent`), migration `dt1directing0001`;
  - `services/directing_transcript.py`: the parser, stdlib only, so the hook and backfill run it on the laptop;
  - `services/directing_service.py`: `ingest_events`, idempotent, moves `agent_until` on;
  - `POST /apps/directing/events` (`routes/directing_router.py`): closed body, ≤ 500 events, route name `automation.directing.ingest`;
  - `tests/unit/test_directing_events.py`;
  - decision 6 → FR-70 | `directing_events` (automation) |
| **B** (unblocked by runtime 2.37.0) | The hook script and its `settings.json` entry; the backfill (dry run, then once to 10-10); the sign-in task runs it daily; hook ordering checked live (§3) | none |
| **C** | Derived sessions, the summary route, the `directing_minutes` shadow in the KPI snapshot, the KPI page line; the Collaborator's messages as a second source (decision 4) | none |
| **D** | Two normal weeks of shadow; then the score question (decision 5) | none |

Each phase is one PR. A and B change nothing the score reads.
