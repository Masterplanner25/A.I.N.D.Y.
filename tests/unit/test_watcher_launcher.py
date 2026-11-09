"""`scripts/watcher.py`: the SDK watcher, made able to count for its owner (audit D1, FR-65 meanwhile)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.app_profile

_SPEC = importlib.util.spec_from_file_location("watcher_launcher", Path(__file__).resolve().parents[2] / "scripts" / "watcher.py")
launcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launcher)


def test_the_key_goes_out_as_x_platform_key():
    seen = {}

    def fake_request(url, data=None, headers=None, method=None):
        seen.update(url=url, headers=headers, method=method)
        return "req"

    build = launcher.per_user_request(fake_request)
    assert build("http://x/watcher/signals", data=b"{}", headers={"X-API-Key": "wk_abc",
                                                                    "Content-Type": "application/json"},
                 method="POST") == "req"
    assert seen["headers"] == {"X-Platform-Key": "wk_abc", "Content-Type": "application/json"}
    assert seen["method"] == "POST"


def test_input_idle_past_the_threshold_reads_as_idle():
    from aindy_sdk.watcher.classifier import ActivityType, ClassificationResult
    from aindy_sdk.watcher.window_detector import WindowInfo

    working = ClassificationResult(activity_type=ActivityType.WORK, confidence=0.9, matched_rule="work:code",
                                   app_name="Code.exe", window_title="repo")
    idle_for = {"s": 10.0}
    classify = launcher.idle_aware(lambda window: working, lambda: idle_for["s"], threshold_seconds=300.0)
    window = WindowInfo(app_name="Code.exe", window_title="repo")
    assert classify(window) is working
    idle_for["s"] = 301.0
    result = classify(window)
    assert result.activity_type == ActivityType.IDLE and result.matched_rule == "input_idle:301s"
    assert result.app_name == "Code.exe"
    unknown = launcher.idle_aware(lambda window: working, lambda: None, threshold_seconds=300.0)
    assert unknown(window) is working  # where idle time cannot be read, nothing changes


def test_the_key_comes_from_the_environment_or_the_file(monkeypatch, tmp_path):
    key_file = tmp_path / "watcher_key"
    monkeypatch.setattr(launcher, "KEY_FILE", key_file)
    monkeypatch.delenv("AINDY_WATCHER_KEY", raising=False)
    assert launcher.watcher_key() == ""
    key_file.write_text("wk_from_file\n", encoding="utf-8")
    assert launcher.watcher_key() == "wk_from_file"
    monkeypatch.setenv("AINDY_WATCHER_KEY", "wk_from_env")
    assert launcher.watcher_key() == "wk_from_env"
