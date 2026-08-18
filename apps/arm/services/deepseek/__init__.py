"""ARM DeepSeek services package.

Origin and attribution:
    This package descends from the **DeepSeek Analyzer** by **Jonathan Rapsiarda**,
    shared directly and used with permission. The module names retained from that
    tool — ``deepseek_code_analyzer``, ``security_deepseek``, ``file_processor_deepseek``,
    ``config_manager_deepseek`` — mark the original structure.

    Adapted here for A.I.N.D.Y.: the analyzer was rebuilt as ARM's core engine with
    Infinity Algorithm priority scoring, PostgreSQL result persistence, memory capture
    via ``MemoryCaptureEngine``, and syscall-mediated invocation. Degree of adaptation
    varies by module; the analyzer is substantially rewritten, the support modules
    less so.

This file used to hold a **byte-identical copy** of ``SecurityValidator`` (181 lines,
duplicating ``security_deepseek.py``). Callers import the module path, so the copy here was
dead — but ``from apps.arm.services.deepseek import SecurityValidator`` still resolved, and
returned a *different* class object.

That made it a live footgun rather than merely dead code: a security fix applied to the real
validator would leave this one untouched and still importable, so the fix could be silently
bypassed by importing the package instead of the module. It is now a re-export, so the
package path keeps working and there is exactly one implementation to fix.
"""

from apps.arm.services.deepseek.security_deepseek import SecurityValidator, resolve_project_root

__all__ = ["SecurityValidator", "resolve_project_root"]
