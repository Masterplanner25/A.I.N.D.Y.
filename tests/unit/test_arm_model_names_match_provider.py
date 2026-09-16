"""ARM's model names must be ones its only provider accepts — ARM-MODEL-NAME-PROVIDER-MISMATCH-1.

ARM's client is DeepSeek (`_build_deepseek_client` → the runtime's `DeepSeekLLMClient`,
`base_url=api.deepseek.com`). Its config defaults said `gpt-4o` from the first commit, and the
provider answered every call with `400 The supported API model names are deepseek-flash,
deepseek-v4-pro, but you passed gpt-4o`. `analysis_results` had zero rows on the live stack before
2026-09-16 — ARM had never produced an analysis anywhere, and the 2026-07-22 walk log had read
the failure as a local key matter. Found by the first agent run that reached `arm.analyze` with a
valid `file_path` (after #375 fixed the argument contract).

Three things have to agree, and this pins all three: the config defaults, the `ArmConfig` column
defaults (a fresh row without a config manager), and the autotune "faster model" suggestion —
`arm.autotune` can APPLY that suggestion, so it must not write a name the provider rejects.

The fourth thing is the request shape: DeepSeek's current models are reasoning models and, with
the default shape, spend the whole `max_tokens` budget on `reasoning_tokens` and return empty
content (measured: 200/200 on both). ARM parses JSON out of `message.content`, so thinking is
turned off per call via `extra_body={"reasoning_effort": ...}`, default `"none"`.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.app_profile

_MODEL_KEYS = ("model", "analysis_model", "generation_model")


def _is_provider_name(name: object) -> bool:
    return isinstance(name, str) and name.startswith("deepseek-")


def test_default_config_names_deepseek_models():
    from apps.arm.services.deepseek.config_manager_deepseek import DEFAULT_CONFIG

    bad = {k: DEFAULT_CONFIG[k] for k in _MODEL_KEYS if not _is_provider_name(DEFAULT_CONFIG[k])}
    assert not bad, f"ARM's client is DeepSeek; these defaults name another provider's model: {bad}"


def test_arm_config_column_defaults_match_the_config_defaults():
    from apps.arm.models import ArmConfig
    from apps.arm.services.deepseek.config_manager_deepseek import DEFAULT_CONFIG

    for key in _MODEL_KEYS:
        column_default = ArmConfig.__table__.columns[key].default
        assert column_default is not None and column_default.arg == DEFAULT_CONFIG[key], (
            f"ArmConfig.{key} default {getattr(column_default, 'arg', None)!r} != "
            f"DEFAULT_CONFIG[{key!r}] {DEFAULT_CONFIG[key]!r} — a row created without the config "
            "manager would carry a model the provider rejects"
        )


def test_autotune_faster_model_suggestion_is_a_provider_name():
    """The learning-efficiency suggestion is applied by `arm.autotune`, not just displayed."""
    import inspect

    from apps.arm.services import arm_metrics_service

    source = inspect.getsource(arm_metrics_service)
    assert '"analysis_model": "deepseek-' in source
    assert "gpt-4o" not in source, "autotune would apply an OpenAI model name to the DeepSeek client"


def test_call_passes_reasoning_effort_off_by_default(monkeypatch):
    """Every ARM chat call carries `extra_body.reasoning_effort`, and the default is `none`."""
    from types import SimpleNamespace

    from apps.arm.services.deepseek import deepseek_code_analyzer as mod

    assert mod.ARM_REASONING_EFFORT == "none"

    captured: dict = {}

    def _fake_chat(client, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    monkeypatch.setattr(mod, "chat_completion_deepseek", _fake_chat)
    # `perform_external_call` wraps the operation in telemetry that needs a DB; bypass it.
    monkeypatch.setattr(mod, "perform_external_call", lambda **kw: kw["operation"]())

    analyzer = mod.DeepSeekCodeAnalyzer.__new__(mod.DeepSeekCodeAnalyzer)
    analyzer.config = dict(mod.DEFAULT_CONFIG)
    analyzer.client = object()

    text, _, _ = analyzer._call_openai("sys", "user", db=None, user_id="u")
    assert text == '{"ok": true}'
    assert captured["model"] == mod.DEFAULT_CONFIG["model"]
    assert captured["extra_body"] == {"reasoning_effort": "none"}
