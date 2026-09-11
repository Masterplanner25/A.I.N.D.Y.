"""A ping must be a page that cites you, not a page about the same subject.

`RIPPLE-PINGS-NOT-ECHOES-1` / `docs/verification/DEFECT_RIPPLE_PINGS_ARE_NOT_ECHOES.md`.

Detection searches for a drop point's URL plus its distinctive title as an exact phrase — the
right query. The provider is an **answer engine**, which returns the sources it used to answer
rather than pages containing the phrase. Measured on the live corpus 2026-09-07: **1 of 256
pings pointed at a URL plausibly connected to the author**, and `openai.com` was the most common
"platform that echoed you" — 36 times. Every score in the domain, 18 "successful" drop points
and five ranked strategies were computed from that.

★ **The three states are the whole design**, and most of what follows defends the middle one:

- `verified`   — fetched, and it contains the drop point's URL or title
- `unverified` — could not be fetched, or predates the check
- rejected     — fetched, demonstrably does not cite you: **never written at all**

"We looked and it does not cite you" and "we could not look" are different answers. Only the
first is evidence, and publishers who refuse scripted requests produce the second constantly —
which is why unverified is carried rather than assumed-negative, and why it does not score.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from apps.rippletrace.drop import DropPointDB, PingDB
from apps.rippletrace.services import ping_verification as pv

pytestmark = pytest.mark.app_profile

USER = uuid.uuid4()
DROP_URL = "https://masterplanner25.substack.com/p/ethics-and-accountability"
DROP_TITLE = "2025 ChatGPT Case Study Series: Ethics and Accountability"


def _drop(db, *, url=DROP_URL, title=DROP_TITLE):
    row = DropPointDB(
        id=f"dp-{uuid.uuid4()}", title=title, platform="Substack", url=url,
        date_dropped=datetime(2026, 1, 1), core_themes="", tagged_entities="",
        intent="published", user_id=USER,
    )
    db.add(row)
    db.commit()
    return row


def _ping(db, drop, *, verification):
    row = PingDB(
        id=f"ping-{uuid.uuid4()}", drop_point_id=drop.id, ping_type="mention",
        source_platform="example.com", date_detected=datetime(2026, 1, 2),
        external_url="https://example.com/post", user_id=USER,
        strength=1.0, connection_type="direct", verification=verification,
    )
    db.add(row)
    db.commit()
    return row


# ── does this page cite you? ──────────────────────────────────────────────────────────

def test_a_page_linking_the_url_cites_you():
    assert pv.page_cites(
        f"Worth reading: {DROP_URL} — good piece.", drop_url=DROP_URL, drop_title=DROP_TITLE
    )


def test_a_bare_link_without_the_scheme_still_counts():
    """A page citing you might write the URL without https://, or without www.

    Matching only the exact normalized form would call a real echo unverified.
    """
    assert pv.page_cites(
        "cited masterplanner25.substack.com/p/ethics-and-accountability today",
        drop_url=DROP_URL, drop_title=DROP_TITLE,
    )


def test_naming_the_piece_without_linking_it_counts():
    """Plenty of genuine echoes name a piece without linking it.

    A link is the strongest evidence, but requiring one would discard the rest.
    """
    assert pv.page_cites(
        f"I read {DROP_TITLE} last week and it changed my mind.",
        drop_url=DROP_URL, drop_title=DROP_TITLE,
    )


def test_a_page_about_the_same_subject_does_not_cite_you():
    """★ The defect, in one assertion.

    This is what 255 of the 256 live pings actually are: an answer engine's citation for a
    question about the same topic.
    """
    arxiv = (
        "Chain-of-thought prompting elicits reasoning in large language models. "
        "We study 2025 ChatGPT behaviour across benchmarks."
    )
    assert not pv.page_cites(arxiv, drop_url=DROP_URL, drop_title=DROP_TITLE)


def test_a_short_title_is_not_matched():
    """"Ethics" appearing on a page is a coincidence, not a citation.

    Same reasoning as `MIN_DISTINCTIVE_TITLE_CHARS` in detection, applied at the other end.
    """
    assert not pv.page_cites(
        "A long essay about ethics in technology.", drop_url=DROP_URL, drop_title="Ethics"
    )


def test_an_empty_page_cites_nothing():
    assert not pv.page_cites("", drop_url=DROP_URL, drop_title=DROP_TITLE)


# ── ★ the three states ────────────────────────────────────────────────────────────────

def test_a_citing_page_verifies(monkeypatch):
    monkeypatch.setattr(
        pv, "fetch_url",
        lambda url, **kw: type("R", (), {"text": f"<p>see {DROP_URL}</p>"})(),
    )
    state, note = pv.verify_hit(hit_url="https://x.com/a", drop_url=DROP_URL, drop_title=DROP_TITLE)

    assert state == pv.VERIFIED
    assert note is None


def test_a_topical_page_is_rejected(monkeypatch):
    monkeypatch.setattr(
        pv, "fetch_url",
        lambda url, **kw: type("R", (), {"text": "<p>An unrelated essay on prompting.</p>"})(),
    )
    state, note = pv.verify_hit(hit_url="https://x.com/a", drop_url=DROP_URL, drop_title=DROP_TITLE)

    assert state == pv.REJECTED
    assert note


def test_a_page_that_cannot_be_fetched_is_unverified_not_rejected(monkeypatch):
    """★ The load-bearing distinction.

    Publishers refuse scripted requests constantly — 401/403/405/406/429/451 — which is why
    feed subscription exists at all. Treating a 403 as "does not cite you" would silently
    convert a publisher's bot policy into evidence about the author's reach.
    """
    from apps.rippletrace.services.content_fetch import ContentFetchError

    def _blocked(url, **kw):
        raise ContentFetchError("That site refuses scripted requests (HTTP 403).")

    monkeypatch.setattr(pv, "fetch_url", _blocked)
    state, note = pv.verify_hit(hit_url="https://x.com/a", drop_url=DROP_URL, drop_title=DROP_TITLE)

    assert state == pv.UNVERIFIED
    assert "403" in note


def test_a_page_with_no_readable_text_is_unverified(monkeypatch):
    """A body rendered in JavaScript returns nothing here.

    Saying "it does not cite you" from an empty fetch would be a confident wrong answer.
    """
    monkeypatch.setattr(pv, "fetch_url", lambda url, **kw: type("R", (), {"text": "<div></div>"})())
    state, _ = pv.verify_hit(hit_url="https://x.com/a", drop_url=DROP_URL, drop_title=DROP_TITLE)

    assert state == pv.UNVERIFIED


def test_verification_never_raises(monkeypatch):
    """It is an improvement to a detection run that already works.

    A fetch blowing up must downgrade the ping, not lose the detection that produced it.
    """
    def _boom(url, **kw):
        raise RuntimeError("socket exploded")

    monkeypatch.setattr(pv, "fetch_url", _boom)
    assert pv.verify_hit(
        hit_url="https://x.com/a", drop_url=DROP_URL, drop_title=DROP_TITLE
    )[0] == pv.UNVERIFIED


# ── ★ only verified pings score ───────────────────────────────────────────────────────

def test_unverified_pings_do_not_score(db_session):
    """★ The whole point.

    Scoring unverified pings is what produced 18 "successful" drop points and five ranked
    strategies from an input measuring topical density.
    """
    from apps.rippletrace.services.threadweaver import analyze_drop_point

    drop = _drop(db_session)
    for _ in range(10):
        _ping(db_session, drop, verification="unverified")

    analyze_drop_point(drop.id, db_session)
    db_session.refresh(drop)

    assert drop.narrative_score == 0.0
    assert drop.spread_score == 0


def test_verified_pings_do_score(db_session):
    from apps.rippletrace.services.threadweaver import analyze_drop_point

    drop = _drop(db_session)
    for _ in range(10):
        _ping(db_session, drop, verification="verified")

    analyze_drop_point(drop.id, db_session)
    db_session.refresh(drop)

    assert drop.narrative_score > 0


def test_a_mixed_set_scores_only_the_verified_half(db_session):
    from apps.rippletrace.services.threadweaver import analyze_drop_point

    drop = _drop(db_session)
    for _ in range(4):
        _ping(db_session, drop, verification="verified")
    for _ in range(20):
        _ping(db_session, drop, verification="unverified")

    analyze_drop_point(drop.id, db_session)
    db_session.refresh(drop)

    only_verified = _drop(db_session, url="https://example.org/other")
    for _ in range(4):
        _ping(db_session, only_verified, verification="verified")
    analyze_drop_point(only_verified.id, db_session)
    db_session.refresh(only_verified)

    # The 20 unverified rows contribute nothing at all — not a smaller weight, nothing.
    assert drop.narrative_score == only_verified.narrative_score


def test_an_existing_row_defaults_to_unverified(db_session):
    """★ The migration's honest default.

    Every ping recorded before this check existed was written without anyone looking at the
    page, so `unverified` is the true statement about it. Deleting the 256 live rows would
    silently rewrite history three engines have already reasoned over.
    """
    drop = _drop(db_session)
    row = PingDB(
        id=f"ping-{uuid.uuid4()}", drop_point_id=drop.id, ping_type="mention",
        source_platform="openai.com", date_detected=datetime(2026, 1, 2),
        external_url="https://openai.com/index/some-page", user_id=USER,
        strength=1.0, connection_type="direct",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    assert row.verification == "unverified"


# ── detection writes the state, and drops what it disproves ───────────────────────────

def test_a_rejected_candidate_is_never_written(db_session, monkeypatch):
    """★ A page that does not cite you is not a ripple.

    Recording it labelled would double the table with rows nothing consumes, and leave the
    same ambiguity one column further down.
    """
    from apps.rippletrace.services import ripple_detection as rd

    drop = _drop(db_session)
    hits = [rd.SearchHit(url="https://arxiv.org/paper", title="A paper", snippet="", published=None)]
    monkeypatch.setattr(rd, "search", lambda *a, **k: hits)
    monkeypatch.setattr(rd, "verify_hit", lambda **kw: (pv.REJECTED, "not a citation"))

    result = rd.detect_for_drop_point(db_session, drop)

    assert result["created"] == 0
    assert result["rejected"]["not_a_citation"] == 1
    assert db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).count() == 0


def test_a_verified_candidate_is_written_and_labelled(db_session, monkeypatch):
    from apps.rippletrace.services import ripple_detection as rd

    drop = _drop(db_session)
    hits = [rd.SearchHit(url="https://blog.example/post", title="Nice", snippet="", published=None)]
    monkeypatch.setattr(rd, "search", lambda *a, **k: hits)
    monkeypatch.setattr(rd, "verify_hit", lambda **kw: (pv.VERIFIED, None))

    result = rd.detect_for_drop_point(db_session, drop)
    row = db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).first()

    assert result["verified"] == 1
    assert row.verification == "verified"


def test_an_unverifiable_candidate_is_written_and_does_not_count_as_verified(
    db_session, monkeypatch
):
    from apps.rippletrace.services import ripple_detection as rd

    drop = _drop(db_session)
    hits = [rd.SearchHit(url="https://blocked.example/post", title="X", snippet="", published=None)]
    monkeypatch.setattr(rd, "search", lambda *a, **k: hits)
    monkeypatch.setattr(rd, "verify_hit", lambda **kw: (pv.UNVERIFIED, "HTTP 403"))

    result = rd.detect_for_drop_point(db_session, drop)
    row = db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).first()

    assert (result["created"], result["verified"], result["unverified"]) == (1, 0, 1)
    assert row.verification == "unverified"
    assert "403" in (row.verification_note or "")


def test_the_verification_budget_downgrades_rather_than_skips(db_session, monkeypatch):
    """★ Out of budget means "not checked yet", not "not a ping".

    Detection can produce 200 candidates in a run; verifying all of them would turn a
    background job into an outbound crawl. The overflow is still recorded, so the next run
    revisits it rather than the evidence being lost.
    """
    from apps.rippletrace.services import ripple_detection as rd

    drop = _drop(db_session)
    hits = [
        rd.SearchHit(url=f"https://blog.example/{n}", title="X", snippet="", published=None)
        for n in range(3)
    ]
    monkeypatch.setattr(rd, "search", lambda *a, **k: hits)
    monkeypatch.setattr(rd, "verify_hit", lambda **kw: (pv.VERIFIED, None))

    result = rd.detect_for_drop_point(db_session, drop, verification_budget=1)
    states = [
        row.verification
        for row in db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).all()
    ]

    assert result["created"] == 3
    assert result["fetched"] == 1
    assert sorted(states) == ["unverified", "unverified", "verified"]
    assert [
        row.verification_note
        for row in db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).all()
        if row.verification == "unverified"
    ] == [pv.BUDGET_EXHAUSTED_NOTE, pv.BUDGET_EXHAUSTED_NOTE]


# ── ★ and the next run actually revisits them ──────────────────────────────────────────────

def _budget_debt(db, drop, url="https://blog.example/owed"):
    """A ping a previous run wrote past its budget: exists, does not score, never looked at."""
    from apps.rippletrace.services import ripple_detection as rd

    hit = rd.SearchHit(url=url, title="X", snippet="", published=None)
    rd._record_ping(
        db, drop_point=drop, hit=hit,
        verification=pv.UNVERIFIED, verification_note=pv.BUDGET_EXHAUSTED_NOTE,
    )
    db.commit()
    return hit


def test_a_budget_debt_is_paid_on_the_next_run_with_budget(db_session, monkeypatch):
    """★ The sentence "the next run revisits them" was in two comments and one docstring
    before any code made it true.

    Measured 2026-09-10: 158 rows carried the budget note and `_record_ping` returned early
    on every one of them, forever. A ping written past the budget is a debt, and this is the
    run that pays it.
    """
    from apps.rippletrace.services import ripple_detection as rd

    drop = _drop(db_session)
    hit = _budget_debt(db_session, drop)
    monkeypatch.setattr(rd, "search", lambda *a, **k: [hit])
    monkeypatch.setattr(rd, "verify_hit", lambda **kw: (pv.VERIFIED, None))

    result = rd.detect_for_drop_point(db_session, drop)
    row = db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).one()

    assert result["created"] == 0
    assert result["revisited"] == {"verified": 1, "unverified": 0, "removed": 0}
    assert (row.verification, row.verification_note) == ("verified", None)


def test_a_budget_debt_that_turns_out_not_to_cite_you_is_removed(db_session, monkeypatch):
    """It never scored, so deleting it rewrites nothing the engines reasoned over."""
    from apps.rippletrace.services import ripple_detection as rd

    drop = _drop(db_session)
    hit = _budget_debt(db_session, drop)
    monkeypatch.setattr(rd, "search", lambda *a, **k: [hit])
    monkeypatch.setattr(rd, "verify_hit", lambda **kw: (pv.REJECTED, "not a citation"))

    result = rd.detect_for_drop_point(db_session, drop)

    assert result["revisited"]["removed"] == 1
    assert result["rejected"]["not_a_citation"] == 1
    assert db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).count() == 0


def test_a_budget_debt_that_cannot_be_fetched_keeps_the_real_reason(db_session, monkeypatch):
    """Still unverified — but now for the publisher's reason, so it is not revisited again."""
    from apps.rippletrace.services import ripple_detection as rd

    drop = _drop(db_session)
    hit = _budget_debt(db_session, drop)
    monkeypatch.setattr(rd, "search", lambda *a, **k: [hit])
    monkeypatch.setattr(rd, "verify_hit", lambda **kw: (pv.UNVERIFIED, "HTTP 403"))

    result = rd.detect_for_drop_point(db_session, drop)
    row = db_session.query(PingDB).filter(PingDB.drop_point_id == drop.id).one()

    assert result["revisited"]["unverified"] == 1
    assert (row.verification, row.verification_note) == ("unverified", "HTTP 403")


def test_a_decided_ping_costs_nothing_on_later_runs(db_session, monkeypatch):
    """★ Only the budget note means "not looked at yet".

    A 403 re-fetched every run is the same refusal at the price of a fetch, and a verified
    ping re-fetched every run spends the budget proving what is already known. Both used to
    be fetched before `_record_ping` noticed the row existed.
    """
    from apps.rippletrace.services import ripple_detection as rd

    drop = _drop(db_session)
    decided = [
        rd.SearchHit(url="https://blocked.example/post", title="X", snippet="", published=None),
        rd.SearchHit(url="https://blog.example/known", title="X", snippet="", published=None),
    ]
    rd._record_ping(
        db_session, drop_point=drop, hit=decided[0],
        verification=pv.UNVERIFIED, verification_note="HTTP 403",
    )
    rd._record_ping(db_session, drop_point=drop, hit=decided[1], verification=pv.VERIFIED)
    db_session.commit()
    calls = []
    monkeypatch.setattr(rd, "search", lambda *a, **k: decided)
    monkeypatch.setattr(
        rd, "verify_hit", lambda **kw: calls.append(kw["hit_url"]) or (pv.VERIFIED, None)
    )

    result = rd.detect_for_drop_point(db_session, drop, verification_budget=5)

    assert calls == []
    assert result["fetched"] == 0
    assert result["revisited"] == {"verified": 0, "unverified": 0, "removed": 0}


def test_the_batch_charges_for_fetches_not_for_candidates(db_session, monkeypatch):
    """Two drop points, one budget. The first's candidates are all already decided, so the
    second still has the whole budget to spend."""
    from apps.rippletrace.services import ripple_detection as rd

    first = _drop(db_session, url="https://masterplanner25.substack.com/p/one")
    second = _drop(db_session, url="https://masterplanner25.substack.com/p/two")
    known = rd.SearchHit(url="https://blog.example/known", title="X", snippet="", published=None)
    rd._record_ping(db_session, drop_point=first, hit=known, verification=pv.VERIFIED)
    db_session.commit()
    fresh = rd.SearchHit(url="https://blog.example/fresh", title="X", snippet="", published=None)

    monkeypatch.setattr(rd, "search", lambda *a, **k: [known, fresh])
    monkeypatch.setattr(rd, "verify_hit", lambda **kw: (pv.VERIFIED, None))
    monkeypatch.setattr(rd, "is_configured", lambda: True)
    monkeypatch.setattr(rd, "_due_drop_points", lambda *a, **k: [first, second])
    # Budget 3. Charged by `kept`, the first drop point's two candidates would leave one for
    # the second and its second candidate would land as a budget debt.
    monkeypatch.setattr(rd, "MAX_VERIFICATIONS_PER_RUN", 3)

    summary = rd.detect_batch(db_session, user_id=str(USER))
    per_drop = {r["drop_point_id"]: r for r in summary["results"]}

    assert per_drop[first.id]["fetched"] == 1
    assert per_drop[second.id]["fetched"] == 2
    assert summary["verified"] == 3
    assert all(
        row.verification_note != pv.BUDGET_EXHAUSTED_NOTE
        for row in db_session.query(PingDB).all()
    )
