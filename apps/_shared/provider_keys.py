"""Whose key pays for a model or search call (FR-59 phase 3; runtime 2.32.0, DEC-121).

Every paid call in `apps/` goes through here, so one place decides whose key pays:

- `llm_client(user_id, provider)` for a provider the runtime has a client for (openai, deepseek,
  anthropic, azure_openai). It is the runtime's `get_llm_client_for_user`.
- `provider_key(user_id, provider)` for a raw HTTP call (Perplexity, and the Resolution Check's
  engines). It is the runtime's `resolve_provider_key`; after a refusal call `refused(...)`.

**The paying user is required.** The runtime treats a call with no user as the server's (its
D5), so a call site that forgot to pass the user would quietly spend the operator's key once
`AINDY_PROVIDER_KEYS=per_user` is on. Here a missing user is a `ValueError`, in every mode, so
the tests find it. The operator's own calls (owner notices, the startup probe) say
`system=True`.

**A key problem is a 402 with a sentence the person can act on** (`ProviderKeyProblem`):
"add your key in Settings" or "your key was refused". Never a 401, which the client reads as
"signed out". Many call sites catch every model error and fall back to a default; each of those
calls `raise_key_problem(exc)` first, or a missing key would turn into a quietly worse result.

With `AINDY_PROVIDER_KEYS` unset (`server`), every function here returns exactly what the call
site used before: the same cached client, the same environment key.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

KEY_PROBLEM_STATUS = 402
REQUIRED = "provider_key_required"
REJECTED = "provider_key_rejected"

_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "azure_openai": "Azure OpenAI",
    "perplexity": "Perplexity",
}


def provider_label(provider: str) -> str:
    return _LABELS.get(str(provider or "").lower(), str(provider))


class ProviderKeyProblem(HTTPException):
    """The caller has no key for this provider, or the provider refused theirs. A 402.

    `str()` carries the `HTTP_402:` prefix, so a flow node that raises it surfaces as a 402
    through `run_flow_or_raise` too, not as a 500.
    """

    def __init__(self, provider: str, kind: str, key_hint: str = "") -> None:
        label = provider_label(provider)
        if kind == REJECTED:
            ending = f" (ending {key_hint})" if key_hint else ""
            message = f"{label} refused your API key{ending}. Replace it in Settings."
        else:
            message = f"This needs your own {label} API key. Add it in Settings."
        super().__init__(status_code=KEY_PROBLEM_STATUS, detail=message)
        self.provider = provider
        self.kind = kind
        self.key_hint = key_hint

    def __str__(self) -> str:
        return f"HTTP_{KEY_PROBLEM_STATUS}:{self.detail}"


def _paying_user(user_id: Any, system: bool) -> str | None:
    if system:
        return None
    text = "" if user_id is None else str(user_id).strip()
    if not text:
        raise ValueError(
            "A paid call needs the user whose key pays for it; pass system=True only for the "
            "operator's own calls."
        )
    return text


def as_problem(exc: BaseException) -> ProviderKeyProblem:
    """The 402 for a runtime `ProviderKeyRequired` / `ProviderKeyRejected`."""
    if isinstance(exc, ProviderKeyProblem):
        return exc
    from AINDY.platform_layer.provider_keys import ProviderKeyRejected

    provider = getattr(exc, "provider", "") or ""
    if isinstance(exc, ProviderKeyRejected):
        return ProviderKeyProblem(provider, REJECTED, getattr(exc, "key_hint", "") or "")
    return ProviderKeyProblem(provider, REQUIRED)


def key_problem(exc: BaseException | None) -> ProviderKeyProblem | None:
    """The key problem anywhere in `exc`'s cause chain, as a 402; else None.

    The runtime's `chat_completion` re-wraps a refused user key as a plain `LLMCallError` whose
    cause is the `ProviderKeyRejected`, and the two point at each other, so the walk is bounded.
    """
    from AINDY.platform_layer.provider_keys import ProviderKeyRequired, ProviderKeyRejected

    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen and len(seen) < 16:
        seen.add(id(current))
        if isinstance(current, ProviderKeyProblem):
            return current
        if isinstance(current, (ProviderKeyRequired, ProviderKeyRejected)):
            return as_problem(current)
        current = current.__cause__ or current.__context__
    return None


def raise_key_problem(exc: BaseException) -> None:
    """In a catch-all `except`: re-raise a key problem as its 402, before any fallback."""
    problem = key_problem(exc)
    if problem is not None:
        if problem is exc:
            raise problem
        raise problem from exc


def llm_client(user_id: Any, provider: str = "openai", *, db=None, system: bool = False):
    """The client whose key pays for this call (the runtime's `get_llm_client_for_user`)."""
    from AINDY.platform_layer.llm_client import get_llm_client, get_llm_client_for_user
    from AINDY.platform_layer.provider_keys import ProviderKeyError

    uid = _paying_user(user_id, system)
    if uid is None:
        return get_llm_client(provider)
    try:
        return get_llm_client_for_user(provider, uid, db=db)
    except ProviderKeyError as exc:
        raise as_problem(exc) from exc


def provider_key(user_id: Any, provider: str, *, db=None, system: bool = False):
    """The resolved key for a raw HTTP call: `.value` (may be None or empty when unset),
    `.source` (`user` or `server`), `.key_hint`. Counted in `aindy_llm_key_source_total`."""
    from AINDY.platform_layer.llm_client import count_key_source  # public since 2.34.0
    from AINDY.platform_layer.provider_keys import ProviderKeyError, resolve_provider_key

    uid = _paying_user(user_id, system)
    try:
        resolved = resolve_provider_key(provider, uid, db=db)
    except ProviderKeyError as exc:
        raise as_problem(exc) from exc
    count_key_source(resolved.provider, resolved.source)
    return resolved


def refused(resolved: Any, status_code: int | None) -> None:
    """After a raw HTTP call: a user's own key refused (401/403) is the person's to fix, so it
    raises the 402. The server's key refused stays the call site's ordinary failure."""
    if getattr(resolved, "source", "server") == "user" and status_code in (401, 403):
        raise ProviderKeyProblem(resolved.provider, REJECTED, getattr(resolved, "key_hint", "") or "")


def can_pay(user_id: Any, provider: str = "openai", *, db=None) -> bool:
    """Whether this user's calls to `provider` have a key to pay with: their own, or the server's
    for an operator or in `server` mode. A scheduled job asks before starting a user's work, so a
    person without a key is skipped quietly (their pieces stay due) instead of failing every tick
    and counting toward the owner's failure notices. Not counted as a call."""
    from AINDY.platform_layer.provider_keys import ProviderKeyError, resolve_provider_key

    if user_id is None or not str(user_id).strip():
        return False
    try:
        resolve_provider_key(provider, str(user_id), db=db)
    except ProviderKeyError:
        return False
    return True


def client_for_resolved(resolved: Any, server_client: Any):
    """For a call site that keeps its own server client (ARM's DeepSeek client): the user's own
    key's client when `resolved` is theirs, else that server client, unchanged."""
    if getattr(resolved, "source", "server") != "user":
        return server_client
    from AINDY.platform_layer.llm_client import user_key_client

    return user_key_client(resolved.provider, resolved)


_IN_TEXT = None


def raise_problem_in(text: Any) -> None:
    """A key problem that crossed a flow or syscall boundary arrives as text (`HTTP_402:<sentence>`,
    possibly wrapped in other messages). Where a route turns that text into a status, call this
    first, so it is the 402 and the sentence, not a generic 500."""
    global _IN_TEXT
    import re

    if _IN_TEXT is None:
        _IN_TEXT = re.compile(rf"HTTP_{KEY_PROBLEM_STATUS}:(.*?Settings\.)", re.DOTALL)
    match = _IN_TEXT.search(str(text or ""))
    if match:
        raise HTTPException(status_code=KEY_PROBLEM_STATUS, detail=match.group(1).strip())


def require_key(user_id: Any, provider: str = "openai", *, db=None) -> None:
    """The 402, before a flow starts, for a route whose paid call runs inside a flow or syscall.

    A key problem raised inside a syscall that a flow node dispatched rolls back the flow's own
    session, and the route then sees "FlowRun ... disappeared", not the sentence. Asking first is
    also cheaper: nothing starts for a person who cannot pay."""
    if not can_pay(user_id, provider, db=db):
        raise ProviderKeyProblem(provider, REQUIRED)


def is_key_problem_text(text: Any) -> bool:
    """A key problem that crossed a syscall boundary as text. A flow node that sees one returns FAILURE, never
    RETRY: a refused key retried is the same refusal, three paid attempts (runtime 2.34.0 handoff §4)."""
    return f"HTTP_{KEY_PROBLEM_STATUS}:" in str(text or "")
