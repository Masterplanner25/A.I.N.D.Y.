"""Social services package.

This file used to hold a byte-identical copy of ``social_service.py`` (22 lines, including
``get_user_scores``). Callers import the module — ``apps.social.services.social_service`` —
so the copy was dead, but it stayed importable as ``apps.social.services.get_user_scores``
and would have drifted silently from the real implementation.

Left intentionally empty: every consumer imports a submodule, so nothing needs re-exporting
here. See the "dead-twin surfaces" note in ``docs/handoffs/FRONTEND_WALK_LOG.md`` — a working
implementation shadowed by a stale duplicate is this repo's most repeated defect shape.
"""
