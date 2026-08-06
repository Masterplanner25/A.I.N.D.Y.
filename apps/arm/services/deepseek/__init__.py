"""ARM DeepSeek services package.

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
