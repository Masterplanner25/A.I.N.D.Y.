"""The links in a piece of writing: shared by the archive (kept per piece) and own_links (read per draft).

Two shapes of input:

* **HTML** (Substack's ``body_html``, Medium's feed body): ``<a href>`` targets, then bare URLs in the
  text between tags. Never a tag's attributes: image sources, scripts and embeds are not links the
  writer made.
* **Markdown or plain text** (DEV's ``body_markdown``, a draft): ``[text](url)`` links, not images
  (``![alt](url)``), then bare URLs.

Order of first appearance, no duplicates. URLs are kept as written; callers normalise for matching.
"""
from __future__ import annotations

import re

_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\((https?://[^)\s]+)\)")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")
_A_TAG = re.compile(r"""<a\b[^>]*\bhref\s*=\s*["'](https?://[^"']+)["'][^>]*>""", re.IGNORECASE)
_BARE = re.compile(r"https?://[^\s<>\"'()\[\]]+")
_TRAILING = ".,;:!?*_"
_HTML_HINT = re.compile(r"<(a|p|div|span|h[1-6]|li|blockquote)\b", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def _add(found: list[str], seen: set[str], url: str) -> None:
    url = url.rstrip(_TRAILING)
    if url and url not in seen:
        seen.add(url)
        found.append(url)


def extract_links(text: str) -> list[str]:
    """Every link the writer made in ``text``, in order of first appearance, without duplicates."""
    body = text or ""
    found: list[str] = []
    seen: set[str] = set()
    if _HTML_HINT.search(body):
        # Each <a href> opening tag becomes its URL, in place, so order of appearance holds. Every
        # other tag goes: its attributes (img src, script src, iframe src) are not links.
        body = _A_TAG.sub(lambda m: f" {m.group(1)} ", body)
        body = _TAG.sub(" ", body)
    images = {m.group(1) for m in _MD_IMAGE.finditer(body)}
    for match in _MD_LINK.finditer(body):
        _add(found, seen, match.group(1))
    for match in _BARE.finditer(body):
        url = match.group(0).rstrip(_TRAILING)
        if url in images or any(url != known and url in known for known in seen):
            continue
        _add(found, seen, url)
    return found
