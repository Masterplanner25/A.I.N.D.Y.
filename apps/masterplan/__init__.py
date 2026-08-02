"""MasterPlan domain package.

This file previously held a byte-identical copy of
``apps/masterplan/services/projection_service.py`` — ``project_completion``,
``evaluate_phase`` and a numpy import — as did ``services/__init__.py``. Nothing
imported either copy; only ``projection_service``'s is used (by ``wcu_service``).
Three copies meant a fix to the live one silently left two stale twins behind, and it
made merely importing ``apps.masterplan`` pull in numpy.
"""
