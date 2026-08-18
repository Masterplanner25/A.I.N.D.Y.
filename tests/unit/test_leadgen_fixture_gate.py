"""Leadgen must not fabricate leads when retrieval fails.

`run_ai_search` used to substitute three hardcoded companies whenever retrieval produced
nothing — on an exception *or* on an empty result set, the second silently. Everything
downstream then ran for real: a genuine GPT scoring call, a persisted `leadgen_results`
row, and a memory node recalled as prior context on later runs. The action gate would
have drafted outreach naming a company that does not exist.

The distinction these tests pin is the whole fix:

    retrieval raised      -> LeadSearchUnavailable   (a failure is not a result)
    retrieval returned [] -> []                      (genuinely nothing is a true answer)
    fixtures enabled      -> the demo leads          (development only, explicit opt-in)

Collapsing the first two is the same null-vs-zero error this codebase already met in
`realized_revenue = 0.00` — reporting "the backend is down" as "there is nothing here".
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-required-length-1234567890")

pytestmark = pytest.mark.app_profile

leadgen = pytest.importorskip("apps.search.services.leadgen_service")

FIXTURE_COMPANIES = {"Acme AI Solutions", "Finovate Labs", "HealthEdge Analytics"}
FIXTURE_HOSTS = {"acmeai.com", "finovatelabs.io", "healthedge.ai"}


@pytest.fixture(autouse=True)
def _fixtures_off(monkeypatch):
    """Default every test to production behaviour; opt in explicitly where needed."""
    monkeypatch.delenv("AINDY_LEADGEN_ALLOW_FIXTURES", raising=False)


def _patch_search(monkeypatch, *, raises=None, results=None):
    def fake_search_leads(query, db=None, user_id=None, max_results=3):
        if raises is not None:
            raise raises
        return {"results": results or []}

    monkeypatch.setattr(leadgen, "search_leads", fake_search_leads)


def test_retrieval_failure_raises_rather_than_fabricating(monkeypatch):
    _patch_search(monkeypatch, raises=RuntimeError("upstream 503"))

    with pytest.raises(leadgen.LeadSearchUnavailable) as excinfo:
        leadgen.run_ai_search("ai automation startups")

    # The cause must survive: "retrieval failed" is only actionable with the reason.
    assert "upstream 503" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_retrieval_failure_does_not_return_fixtures(monkeypatch):
    _patch_search(monkeypatch, raises=RuntimeError("boom"))
    try:
        result = leadgen.run_ai_search("q")
    except leadgen.LeadSearchUnavailable:
        return  # correct path
    pytest.fail(f"expected LeadSearchUnavailable, got {result!r}")


def test_empty_result_set_is_an_empty_list_not_fixtures(monkeypatch):
    """The silent branch: retrieval worked and matched nothing. That is a real answer."""
    _patch_search(monkeypatch, results=[])

    assert leadgen.run_ai_search("nothing matches this") == []


def test_real_results_pass_through_untouched(monkeypatch):
    real = [{"company": "Northwind Ltd", "url": "https://northwind.example", "context": "ctx"}]
    _patch_search(monkeypatch, results=real)

    assert leadgen.run_ai_search("q") == real


@pytest.mark.parametrize("flag", ["1", "true", "yes", "on", "TRUE", "On"])
def test_fixtures_returned_only_when_explicitly_enabled(monkeypatch, flag):
    monkeypatch.setenv("AINDY_LEADGEN_ALLOW_FIXTURES", flag)
    _patch_search(monkeypatch, raises=RuntimeError("offline"))

    leads = leadgen.run_ai_search("q")

    assert {lead["company"] for lead in leads} == FIXTURE_COMPANIES


@pytest.mark.parametrize("flag", ["", "0", "false", "no", "off", "banana"])
def test_unrecognised_flag_values_do_not_enable_fixtures(monkeypatch, flag):
    """Anything that is not clearly 'on' must fail closed."""
    monkeypatch.setenv("AINDY_LEADGEN_ALLOW_FIXTURES", flag)
    _patch_search(monkeypatch, raises=RuntimeError("offline"))

    with pytest.raises(leadgen.LeadSearchUnavailable):
        leadgen.run_ai_search("q")


def test_fixtures_are_returned_as_a_copy(monkeypatch):
    """A caller mutating its results must not poison the module-level constant."""
    monkeypatch.setenv("AINDY_LEADGEN_ALLOW_FIXTURES", "1")
    _patch_search(monkeypatch, results=[])

    first = leadgen.run_ai_search("q")
    first.append({"company": "Injected", "url": "x", "context": "y"})
    second = leadgen.run_ai_search("q")

    assert {lead["company"] for lead in second} == FIXTURE_COMPANIES


def test_fixture_hosts_are_the_known_set():
    """Pins the hosts a backfill query must search for in leadgen_results."""
    hosts = {lead["url"].split("//", 1)[1].split("/", 1)[0] for lead in leadgen._DEV_FIXTURE_LEADS}
    assert hosts == FIXTURE_HOSTS


def test_empty_result_path_is_logged(monkeypatch, caplog):
    """Previously only the exception branch logged; an empty set was completely silent."""
    _patch_search(monkeypatch, results=[])

    with caplog.at_level("INFO", logger=leadgen.logger.name):
        leadgen.run_ai_search("silent query")

    assert any("no leads" in r.message.lower() for r in caplog.records), caplog.text


def test_fixture_use_is_logged_as_a_warning(monkeypatch, caplog):
    """If fabricated data is in play, the log must say so — that is what was missing."""
    monkeypatch.setenv("AINDY_LEADGEN_ALLOW_FIXTURES", "1")
    _patch_search(monkeypatch, results=[])

    with caplog.at_level("WARNING", logger=leadgen.logger.name):
        leadgen.run_ai_search("q")

    warnings = " ".join(r.message.lower() for r in caplog.records)
    assert "fixture" in warnings and "fabricated" in warnings


# ── Boot-time posture warning (monitoring check 1) ───────────────────────────
# The flag being set in a real deployment is the condition that matters, and a
# per-call warning only reaches whoever happens to be reading logs at that moment.


def test_bootstrap_warns_when_fixtures_are_enabled(monkeypatch, caplog):
    from apps.search import bootstrap

    monkeypatch.setenv("AINDY_LEADGEN_ALLOW_FIXTURES", "1")
    with caplog.at_level("WARNING", logger=bootstrap.logger.name):
        bootstrap._warn_if_leadgen_fixtures_enabled()

    # getMessage() applies the lazy %-args; `record.message` is the unformatted template.
    text = " ".join(r.getMessage().lower() for r in caplog.records)
    assert "fabricated" in text
    assert "aindy_leadgen_allow_fixtures" in text


def test_bootstrap_is_silent_when_fixtures_are_disabled(monkeypatch, caplog):
    from apps.search import bootstrap

    monkeypatch.delenv("AINDY_LEADGEN_ALLOW_FIXTURES", raising=False)
    with caplog.at_level("WARNING", logger=bootstrap.logger.name):
        bootstrap._warn_if_leadgen_fixtures_enabled()

    assert not caplog.records, "must not warn when the flag is unset"
