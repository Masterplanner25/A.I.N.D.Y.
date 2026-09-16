"""The FR register's headings must tell the truth on their own.

`docs/runtime/RUNTIME_FEATURE_REQUESTS.md` is read by heading scan — ours when we re-derive the
backlog, the runtime's when it takes intake. Two drifts were found on 2026-09-16 and reconciled:
eight headings still read as open filings while the runtime's ledger had shipped them, and four
FRs appeared twice at `##` level (the current state and a retained "original") with contradicting
markers. This pins the two invariants that make a heading scan trustworthy.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "runtime" / "RUNTIME_FEATURE_REQUESTS.md"

STATE_MARKERS = ("✅", "🟡", "🔴", "🟢")


def _fr_headings() -> list[str]:
    return [line for line in REGISTER.read_text(encoding="utf-8").splitlines() if line.startswith("## FR-")]


def test_each_fr_number_appears_once_at_heading_level():
    numbers = [re.match(r"## FR-(\d+)", h).group(1) for h in _fr_headings()]
    dupes = {n: c for n, c in Counter(numbers).items() if c > 1}
    assert not dupes, (
        f"FR numbers with more than one `## ` heading: {dupes} — demote retained originals to `###` "
        "so a heading scan sees one state per FR"
    )


def test_every_fr_heading_carries_a_state_marker():
    missing = [h for h in _fr_headings() if not any(m in h for m in STATE_MARKERS)]
    assert not missing, (
        "FR headings with no state marker (✅ shipped / 🟡 partial / 🔴 open / 🟢 hygiene):\n"
        + "\n".join(missing)
    )
