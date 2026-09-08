"""Every outbound call names who it is talking to.

`service_name` is what the external-call ledger groups by. Six call sites passed the literal
`"http"` — Perplexity (twice), YouTube (three times) and page fetching — so a paid search
could not be counted against a page fetch, or against itself across two domains.

★ **The provider was already recorded, one field too deep.** `extra={"provider": "perplexity"}`
was right there, inside a JSON blob nothing groups by. The fix was promotion, not invention.

This mattered more from 2026-09-07 than before it: ping verification makes up to 60 outbound
fetches per detection run, triggered by the Perplexity search that produced the candidates —
so the two highest-volume calls in the system sat next to each other under the same label.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.app_profile

APPS = pathlib.Path(__file__).resolve().parents[2] / "apps"

# `http` says nothing a URL does not already say, and it is what every one of these six sites
# used. Named here rather than as "anything generic" so the guard fails loudly on the exact
# value that caused the problem.
BANNED = {"http", "https", "api", "external", "web"}


def _service_names() -> list[tuple[str, int, str]]:
    """Every literal `service_name=` passed to `perform_external_call`, with its location."""
    found: list[tuple[str, int, str]] = []
    for path in APPS.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "perform_external_call":
                continue
            for keyword in node.keywords:
                if keyword.arg == "service_name" and isinstance(keyword.value, ast.Constant):
                    # Posix-normalised so assertions read the same on either platform.
                    found.append(
                        (
                            path.relative_to(APPS).as_posix(),
                            node.lineno,
                            str(keyword.value.value),
                        )
                    )
    return found


def test_every_external_call_site_was_found():
    """Guard the guard: an AST walk that finds nothing would pass every assertion below."""
    assert len(_service_names()) >= 15


def test_no_call_site_is_labelled_generically():
    """★ The defect, as a rule.

    A ledger row saying `http` cannot answer "how much Perplexity did that detection run
    cost" — which is the question that exists now that verification fetches outnumber the
    searches that trigger them.
    """
    offenders = [
        f"{path}:{line} -> {name}"
        for path, line, name in _service_names()
        if name.lower() in BANNED
    ]
    assert not offenders, "generic service_name: " + ", ".join(offenders)


def test_the_two_perplexity_call_sites_share_a_name():
    """Both spend the same key against the same endpoint, in different domains.

    RippleTrace's mention detection and Search's research engine were labelled separately
    from each other and from everything else; neither was countable against the other.
    """
    perplexity = {path for path, _, name in _service_names() if name == "perplexity"}

    assert perplexity == {
        "rippletrace/services/mention_search.py",
        "search/services/research_engine.py",
    }


def test_page_fetching_is_named_as_a_class_of_call():
    """Not a provider — it fetches arbitrary publisher URLs — but still its own category,
    and now the busiest one in the system."""
    assert any(name == "web_fetch" for _, _, name in _service_names())


# ── the purpose a caller supplies ─────────────────────────────────────────────────────

def test_fetch_url_takes_a_purpose():
    """★ It was hardcoded to `rippletrace_content_ingest`.

    So the ping verification added 2026-09-07 filed its fetches as content ingest — the same
    function doing two different jobs at very different volumes, with the ledger unable to
    tell them apart.
    """
    import inspect

    from apps.rippletrace.services.content_fetch import fetch_url

    assert "purpose" in inspect.signature(fetch_url).parameters


def test_verification_declares_its_own_purpose():
    source = (
        APPS / "rippletrace" / "services" / "ping_verification.py"
    ).read_text(encoding="utf-8")

    assert 'purpose="rippletrace_ping_verification"' in source


def test_the_default_purpose_is_unchanged_for_existing_callers():
    """Feed polling and page ingestion keep the label they already had."""
    import inspect

    from apps.rippletrace.services.content_fetch import fetch_url

    assert (
        inspect.signature(fetch_url).parameters["purpose"].default
        == "rippletrace_content_ingest"
    )
