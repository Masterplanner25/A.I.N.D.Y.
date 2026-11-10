---
name: api-hang-triage
description: The A.I.N.D.Y. api hangs, /health fails or the scheduler logs 'skipped a run (max_instances)': what to check, cheapest first, before reading code.
---

<!-- Moved from the root CLAUDE.md on 2026-11-09 so it loads only when working here. -->

## When the API hangs: the scheduler saturation trap

A wedged API logs this, once a second, loudly:

```
[Scheduler] job 'scheduler_wait_tick' skipped a run (max_instances) — the scheduler is saturated
```

**It is almost always a consequence, not the cause, and it is the wrong place to start.** Dispatch
is serialised through one scheduler slot by design until `AINDY_ASYNC_HEAVY_EXECUTION` is on
(runtime `APP_HANDOFF_v2.4.0` §7), so *anything* that occupies that slot produces this line. The
message names the victim, never the culprit.

The full fingerprint — dead `/health`, **zero container restarts**, no log output at all, high CPU,
starved 1-second heartbeat — has now been produced by at least two unrelated causes: a slow Genesis
request, and pure host memory starvation with no app traffic whatsoever. Seeing the fingerprint
tells you the slot is full. It does not tell you what filled it.

**Two fingerprints that look like this and are not, cheaper than all of the below:**

- `/health` **500** with `/api/version` **200**, from the first request after boot, plus
  `RedisWaitRegistry.get_all_specs failed` tracebacks every second — the rate limiter's Redis
  storage cannot resolve `redis`. The stack was brought up without `--profile full`. Not the
  release, not the code.
- Since #380 the api carries `mem_limit: 1536m` with swap off, so a runaway now ends in an
  **OOM kill and a restart** — `docker ps` shows a restart count, the log restarts from
  `[entrypoint]`. "Zero container restarts" is no longer part of the saturation fingerprint; a
  non-zero count is the cap doing its job, and `cgroup memory.peak` says what grew.

**Then check in this order, cheapest first:**

1. `docker logs <postgres> | grep "terminating any other active server processes"` — a non-zero
   count means PostgreSQL has been reinitialising its whole cluster and every app symptom is
   downstream. This was 155 occurrences on 2026-08-19.
2. Host paging. On Windows use `Get-Counter '\Memory\Available MBytes'` and `'\Memory\Pages/sec'`
   — **not** `Win32_OperatingSystem.FreePhysicalMemory`, which excludes standby and reads
   catastrophically low when things are fine. Tens of thousands of hard faults/sec means the
   container is starved, not broken.
3. Whether the last log line is `[entrypoint] starting: aindy-runtime serve` — boot imports the
   16-app graph **twice** and takes minutes on a loaded host. `unhealthy` during that window is
   the healthcheck being impatient, not a crash.

Only after those three should you look at application code. Full write-ups:
`docs/verification/DEFECT_GENESIS_MESSAGE_LATENCY.md` §8.1 and
`docs/verification/DEFECT_INFINITY_RECALC_DEBOUNCE.md`.
