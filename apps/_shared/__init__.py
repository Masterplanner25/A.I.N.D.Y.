"""Cross-domain helpers that belong to no single app.

Modules here are imported by domain apps directly. That is deliberate and is NOT a
cross-app import: `scripts/check_app_imports.py` resolves an import target by matching
`parts[1]` against the known app names, and `_shared` is not one, so it returns `None`
and the import is never flagged. Sibling precedent: `apps/_adapters.py` and
`apps/_bootstrap_validator.py`.

Keep this package free of domain logic. Anything here must be true for every app.
"""
