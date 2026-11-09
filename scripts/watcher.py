"""Run the A.I.N.D.Y. watcher on this laptop, so `focus_quality` (15% of the score) has real data.

Audit 2026-11-01 D1 (owner, 2026-11-08): the runtime already ships the watcher. It has `/watcher` routes with per-user
keys (DEC-117), and `aindy-sdk` 1.0.0 has a Windows client, installed in this repo's venv. It had never been used, and
as shipped its signals cannot count for anyone (FR-65). This launcher runs the SDK's watcher with three fixes, until
FR-65 ships:

1. **The header.** The SDK sends its key as `X-API-Key`, which the route rejects for a per-user key. Here it goes out
   as `X-Platform-Key`, and the server attributes every signal to the key's owner.
2. **Idle detection.** The SDK ends a focus session only when the screen is locked. Here, keyboard and mouse idle for
   `AINDY_WATCHER_IDLE_MINUTES` (default 5) counts as idle too (Windows `GetLastInputInfo`). That is what ends a
   session, and only an ended session moves `focus_quality`.
3. **The key's name.** The SDK reads its key from `AINDY_API_KEY`, the server's shared secret, which must never live on
   a laptop. Here the key is your own watcher key: `AINDY_WATCHER_KEY`, or the file `~/.aindy/watcher_key`.

Get a key: A.I.N.D.Y. Settings, then "Watcher key". It is shown once.

Run it (from the repo root, in PowerShell):

    $env:AINDY_WATCHER_KEY = "<your key>"      # or save it in ~/.aindy/watcher_key
    venv\\Scripts\\python scripts\\watcher.py --dry-run     # see what it would send
    venv\\Scripts\\python scripts\\watcher.py               # send it

Other settings are the SDK's: `AINDY_WATCHER_API_URL` (default here http://127.0.0.1:8000), `AINDY_WATCHER_POLL_INTERVAL`,
`AINDY_WATCHER_CONFIRMATION_DELAY` and so on (`aindy_sdk/watcher/config.py`).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_IDLE_MINUTES = 5.0
KEY_FILE = Path.home() / ".aindy" / "watcher_key"


def watcher_key() -> str:
    key = (os.environ.get("AINDY_WATCHER_KEY") or "").strip()
    if not key and KEY_FILE.is_file():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    return key


def per_user_request(original):
    """`urllib.request.Request`, with the SDK's `X-API-Key` header sent as `X-Platform-Key`."""

    def build(url, data=None, headers=None, **kwargs):
        headers = dict(headers or {})
        key = headers.pop("X-API-Key", None)
        if key:
            headers["X-Platform-Key"] = key
        return original(url, data=data, headers=headers, **kwargs)

    return build


def input_idle_seconds() -> float | None:
    """Seconds since the last keyboard or mouse input, on Windows; None where it cannot be read."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    millis = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return millis / 1000.0


def idle_aware(classify, idle_seconds_fn, threshold_seconds: float):
    """The SDK's `classify`, reporting IDLE once input has been idle for `threshold_seconds`."""
    from aindy_sdk.watcher.classifier import ActivityType, ClassificationResult

    def wrapped(window):
        idle = idle_seconds_fn()
        if idle is not None and idle >= threshold_seconds:
            return ClassificationResult(activity_type=ActivityType.IDLE, confidence=1.0,
                                        matched_rule=f"input_idle:{int(idle)}s",
                                        app_name=getattr(window, "app_name", "") or "",
                                        window_title=getattr(window, "window_title", "") or "")
        return classify(window)

    return wrapped


def install(threshold_seconds: float) -> None:
    """Patch the SDK in this process only: the header and idle detection."""
    from aindy_sdk.watcher import classifier, signal_emitter

    signal_emitter.Request = per_user_request(signal_emitter.Request)
    classifier.classify = idle_aware(classifier.classify, input_idle_seconds, threshold_seconds)


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    key = watcher_key()
    if not key and not dry_run:
        sys.exit("No watcher key. Create one in A.I.N.D.Y. Settings (Watcher key), then set AINDY_WATCHER_KEY "
                 f"or save it in {KEY_FILE}.")
    # The SDK's config reads AINDY_API_KEY. Set it to YOUR watcher key, in this process only.
    os.environ["AINDY_API_KEY"] = key
    os.environ.setdefault("AINDY_WATCHER_API_URL", DEFAULT_API_URL)
    minutes = float(os.environ.get("AINDY_WATCHER_IDLE_MINUTES") or DEFAULT_IDLE_MINUTES)
    install(minutes * 60.0)
    from aindy_sdk.watcher import watcher

    watcher.main()


if __name__ == "__main__":
    main()
