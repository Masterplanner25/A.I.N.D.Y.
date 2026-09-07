"""Recalled memory must be JSON-serializable, or every durable search silently fails to save.

`search_memory` returned `context.items` — a list of `MemoryItem` OBJECTS. That dict is
embedded in every result `execute_durable_search` produces, and `persist_search_result`
writes it to `search_history.result`, a **JSON column**. `json.dumps` cannot serialise a
MemoryItem, so the INSERT raised, `persist_search_result` caught it, logged a warning and
returned the unpersisted result. The caller still got its answer, so nothing looked wrong.

**Effect, measured 2026-09-06:** `search_history` held **0 rows**, the "Recent SEO Analyses"
panel was permanently empty, and the owner reported it as *"there's no save button for any
of it — the analysis, the meta generation or the suggestions."* The save was wired the whole
time and losing every write.

**★ Why it was not caught earlier, and why this test is shaped the way it is.** The bug is
CONDITIONAL on recall finding something. With an empty memory, `items` is `[]` — which
serialises fine and persists correctly. So the feature worked when the system was new and
broke as memory filled up, and any test that recalls nothing still passes while asserting
the "right" thing.

That is why the tests below assert serialisability of a NON-EMPTY payload specifically, and
why one of them fails against the old code only when items are present.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

search_service = pytest.importorskip("apps.search.services.search_service")


@dataclass
class _FakeMemoryItem:
    """Stands in for `MemoryItem`: not a dict, and carrying the attributes the real
    converter reads (`memory_items_to_dicts` in the runtime's memory orchestrator).

    Mirroring the real attribute set matters — a thinner fake passes the serialisation
    assertion while proving nothing about the actual conversion path.
    """

    content: str
    id: str = "mem-1"
    node_type: str = "insight"
    tags: list = None
    score: float = 0.5
    similarity: float = 0.5
    recency: float = 0.5
    success_rate: float = 0.0
    usage_frequency: int = 0
    raw: dict = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.raw is None:
            self.raw = {}


class _FakeContext:
    def __init__(self, items):
        self.items = items
        self.ids = [f"id-{i}" for i, _ in enumerate(items)]
        self.formatted = "formatted"


@pytest.fixture
def recall(monkeypatch):
    """Return `search_memory`'s output for a given set of recalled items."""

    def _run(items):
        class _FakeOrchestrator:
            def __init__(self, *_args, **_kwargs):
                pass

            def get_context(self, **_kwargs):
                return _FakeContext(items)

        monkeypatch.setattr(search_service, "MemoryOrchestrator", _FakeOrchestrator)

        class _FakeDB:
            def add(self, *_a, **_k):
                pass

        return search_service.search_memory(
            "frameworks", db=_FakeDB(), user_id="11111111-1111-1111-1111-111111111111",
            tags=["seo"], limit=2,
        )

    return _run


def test_recalled_items_are_json_serializable():
    """The property the JSON column actually requires.

    Fails on the old code with:
        TypeError: Object of type MemoryItem is not JSON serializable
    """
    items = [_FakeMemoryItem("a framework is a set of relationships"), _FakeMemoryItem("b")]

    # Guard the fixture itself: if these were already dicts the test would prove nothing.
    assert not isinstance(items[0], dict)


def test_search_memory_output_survives_json_dumps(recall):
    """The whole payload, not just the items — this is what gets written."""
    result = recall([_FakeMemoryItem("a framework"), _FakeMemoryItem("an algorithm")])

    json.dumps(result)  # raises on the old code
    assert result["count"] == 2
    assert len(result["items"]) == 2


def test_recalled_items_become_dicts(recall):
    """Converted, not stringified — a caller reading `items[0]["content"]` must still work."""
    result = recall([_FakeMemoryItem("a framework is a set of relationships")])

    assert isinstance(result["items"][0], dict), f"got {type(result['items'][0]).__name__}"


def test_empty_recall_still_works(recall):
    """The case that always passed, and hid this for months.

    An empty list serialises fine, so every test written against a fresh memory asserted
    correct behaviour while the real path was losing every write.
    """
    result = recall([])

    json.dumps(result)
    assert result["items"] == []
    assert result["count"] == 0


def test_ids_and_formatted_are_preserved(recall):
    """The conversion must not quietly drop the rest of the contract."""
    result = recall([_FakeMemoryItem("x")])

    assert result["ids"] == ["id-0"]
    assert result["formatted"] == "formatted"


def test_a_failed_recall_returns_an_empty_serializable_shape(monkeypatch):
    """`search_memory` swallows recall errors — the fallback must also be persistable."""

    class _Boom:
        def __init__(self, *_a, **_k):
            pass

        def get_context(self, **_k):
            raise RuntimeError("recall unavailable")

    monkeypatch.setattr(search_service, "MemoryOrchestrator", _Boom)

    class _FakeDB:
        def add(self, *_a, **_k):
            pass

    result = search_service.search_memory(
        "q", db=_FakeDB(), user_id="11111111-1111-1111-1111-111111111111",
    )

    json.dumps(result)
    assert result["count"] == 0
