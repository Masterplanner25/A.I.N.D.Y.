# ARM

<!-- Moved from the root CLAUDE.md on 2026-11-09 so it loads only when working here. -->

## ARM config — per-user scoping

`arm_config.id` is a `String(36)` primary key. All rows are keyed by user UUID. All `arm_config_dao` calls must pass `user_id=str(current_user["sub"])`. A missing `user_id` falls back to the key `"default"` — the system default singleton, not per-user storage. The `String(36)` length is required to hold a UUID; `String(32)` is too short.

**ARM's only LLM client is DeepSeek, so every model name in ARM must be one DeepSeek accepts**
(`deepseek-v4-pro`, `deepseek-flash` as of 2026-09-16 — `models.list()` is the source of truth).
The defaults said `gpt-4o` from the first commit and ARM had **never produced an analysis** on any
stack until #376 (`ARM-MODEL-NAME-PROVIDER-MISMATCH-1`). Both DeepSeek models are reasoning
models: with ARM's request shape they spend the whole `max_tokens` budget thinking and return
**empty content**, so every ARM call passes `extra_body={"reasoning_effort": "none"}`
(`AINDY_ARM_REASONING_EFFORT` to change it). `test_arm_model_names_match_provider.py` pins both.
