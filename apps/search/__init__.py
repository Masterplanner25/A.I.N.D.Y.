"""Search domain app.

This file used to hold the third copy of the scoring helpers from
``services/search_scoring.py`` (``score_lead_result``, ``score_research_result``,
``score_seo_result``, ``_clamp01``). Nothing imported them from here.

Left intentionally empty: the app is consumed through its submodules
(``apps.search.bootstrap``, ``apps.search.syscalls``, ``apps.search.services.*``), which
resolve regardless of this file's contents.
"""
