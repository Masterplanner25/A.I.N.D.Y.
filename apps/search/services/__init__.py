"""Search services package.

This file used to hold a byte-identical copy of the scoring helpers in
``search_scoring.py`` — ``score_lead_result``, ``score_research_result``,
``score_seo_result`` and ``_clamp01`` — 45 lines in all. The same block was *also* copied
into ``apps/search/__init__.py``, so three copies of the same scoring logic existed and only
``search_scoring.py`` was ever imported.

Left intentionally empty: every consumer imports the module directly
(``from apps.search.services.search_scoring import ...``), and submodule imports such as
``from apps.search.services import search_service`` work regardless of what lives here.
"""
