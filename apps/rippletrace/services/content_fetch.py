"""Fetching and parsing published content for rippletrace ingestion.

Everything here handles a URL the *user* supplied, which the server then requests.
That makes it an SSRF surface: without a guard, "ingest this URL" is a request
forgery primitive pointed at the container's own network — cloud metadata endpoints,
internal admin ports, the database. ``assert_public_url`` is therefore not optional
decoration; it is the reason this module can exist.

Split from ``content_ingest`` deliberately: this half is pure I/O + parsing with no
database and no domain concepts, so the parsers are testable against fixture strings
without a session, a network, or a user.

No new dependencies. ``defusedxml`` (already installed, and the safe choice for
parsing XML from arbitrary publishers) handles feeds; feed/HTML metadata extraction
uses the stdlib ``html.parser`` rather than pulling in bs4/feedparser.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from defusedxml import ElementTree as DefusedET

logger = logging.getLogger(__name__)

USER_AGENT = "AINDY-RippleTrace/1.0 (+content-ingestion)"

MAX_REDIRECTS = 5
FETCH_TIMEOUT_SECONDS = 10
# Feeds and articles are text. Anything past this is not content we can use, and an
# unbounded read on a user-supplied URL is a memory-exhaustion lever.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

ATOM_NS = "http://www.w3.org/2005/Atom"

# Query parameters that identify a *campaign*, not a document. Left in place they
# produce several drop points for one article, which then look like spread.
_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "msclkid",
    "ref",
    "ref_src",
    "s",
    "twclid",
    "yclid",
}

_PLATFORM_BY_DOMAIN = {
    "linkedin.com": "LinkedIn",
    "x.com": "X",
    "twitter.com": "X",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "substack.com": "Substack",
    "medium.com": "Medium",
    "github.com": "GitHub",
    "reddit.com": "Reddit",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "tiktok.com": "TikTok",
    "threads.net": "Threads",
    "bsky.app": "Bluesky",
    "mastodon.social": "Mastodon",
    "dev.to": "DEV",
    "hashnode.dev": "Hashnode",
    "ghost.io": "Ghost",
    "wordpress.com": "WordPress",
    "tumblr.com": "Tumblr",
    "vimeo.com": "Vimeo",
    "spotify.com": "Spotify",
}

_FEED_CONTENT_TYPES = ("xml", "rss", "atom")


class ContentFetchError(Exception):
    """A URL could not be fetched or is not permitted. Carries a user-safe message."""


# ── URL handling ──────────────────────────────────────────────────────────────


def normalize_url(url: str) -> str:
    """Fold a URL onto a stable identity for deduplication.

    Drops the fragment and tracking parameters, lowercases scheme and host, removes a
    redundant default port and a single trailing slash. Deliberately conservative:
    query parameters that are not known trackers are preserved, because for plenty of
    sites (``?p=123``, ``?v=abc``) the query *is* the document.
    """
    parsed = urlparse((url or "").strip())
    scheme = (parsed.scheme or "").lower()
    netloc = (parsed.hostname or "").lower()
    if not netloc:
        return (url or "").strip()
    if parsed.port and not (
        (scheme == "http" and parsed.port == 80) or (scheme == "https" and parsed.port == 443)
    ):
        netloc = f"{netloc}:{parsed.port}"

    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith("utm_")
        ]
    )
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunparse((scheme, netloc, path, "", query, ""))


def infer_platform(url: str) -> str:
    """Human-readable platform name from the URL's domain.

    ``spread_score`` counts *distinct platforms*, so this string is load-bearing: two
    spellings of the same platform would read as spread that did not happen.
    """
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return "unknown"
    host = host[4:] if host.startswith("www.") else host
    for domain, name in _PLATFORM_BY_DOMAIN.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host


def assert_public_url(url: str) -> str:
    """Reject anything that is not a plain http(s) URL resolving to a public address.

    Every hostname is resolved and *all* returned addresses must be global. Rejecting
    on any single private address (rather than requiring all of them to be private)
    means a hostname with a split A record cannot smuggle a request to the internal
    interface.

    Residual risk, stated rather than hidden: this validates at resolution time and
    ``requests`` resolves again when it connects, so a hostname whose DNS flips between
    the two (rebinding) is not covered. Closing that needs connect-to-pinned-IP with a
    Host override; the redirect loop in ``fetch_url`` re-validates every hop, which is
    the vector that actually shows up in practice (an open redirect to 169.254.169.254).
    """
    candidate = (url or "").strip()
    parsed = urlparse(candidate)

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ContentFetchError("Only http:// and https:// URLs can be ingested.")
    host = parsed.hostname
    if not host:
        raise ContentFetchError("That URL has no hostname.")
    if parsed.username or parsed.password:
        raise ContentFetchError("URLs with embedded credentials are not accepted.")

    try:
        resolved = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ContentFetchError(f"Could not resolve {host}.") from exc

    for family, _type, _proto, _canon, sockaddr in resolved:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            raise ContentFetchError(f"Could not interpret the address for {host}.") from None
        if not address.is_global or address.is_multicast:
            raise ContentFetchError(
                f"{host} resolves to a non-public address ({address}); refusing to fetch it."
            )
    return candidate


# ── Fetching ──────────────────────────────────────────────────────────────────


@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    text: str
    etag: str | None = None
    last_modified: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304

    @property
    def looks_like_feed(self) -> bool:
        lowered = self.content_type.lower()
        if any(token in lowered for token in _FEED_CONTENT_TYPES):
            return True
        head = self.text.lstrip()[:512].lower()
        return "<rss" in head or "<feed" in head or "<rdf:rdf" in head


def _read_capped(response: requests.Response) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=16384):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ContentFetchError("That URL returned more data than we will read (2 MB cap).")
        chunks.append(chunk)
    body = b"".join(chunks)
    # `response.encoding` only (never `apparent_encoding`): the latter reads
    # `response.content`, which raises "already consumed" once the body has been
    # streamed through iter_content. Feeds and articles are effectively always UTF-8,
    # and errors="replace" keeps a mislabelled charset from failing the ingest.
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return body.decode("utf-8", errors="replace")


def fetch_url(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    db=None,
    user_id: str | None = None,
) -> FetchResult:
    """Fetch a user-supplied URL, validating every redirect hop.

    Redirects are followed manually so each ``Location`` gets the same public-address
    check as the original URL — ``allow_redirects=True`` would validate only the first.
    """
    from AINDY.platform_layer.external_call_service import perform_external_call

    current = assert_public_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.5",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    # One Session across the redirect chain: redirects are followed by hand (so each
    # hop is re-validated), and a shared session reuses the connection instead of
    # standing up a new one per hop.
    session = requests.Session()
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            target = current
            try:
                response = perform_external_call(
                    service_name="http",
                    endpoint=target,
                    method="GET",
                    db=db,
                    user_id=user_id,
                    extra={"purpose": "rippletrace_content_ingest"},
                    operation=lambda: session.get(
                        target,
                        headers=headers,
                        timeout=FETCH_TIMEOUT_SECONDS,
                        allow_redirects=False,
                        stream=True,
                    ),
                )
            except ContentFetchError:
                raise
            except requests.RequestException as exc:
                raise ContentFetchError(f"Could not fetch that URL: {exc}") from exc

            try:
                if response.status_code == 304:
                    return FetchResult(
                        url=current,
                        status_code=304,
                        content_type=response.headers.get("Content-Type", ""),
                        text="",
                        etag=etag,
                        last_modified=last_modified,
                    )

                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise ContentFetchError("That URL redirected without a destination.")
                    current = assert_public_url(urljoin(current, location))
                    continue

                if response.status_code >= 400:
                    raise ContentFetchError(
                        f"That URL returned HTTP {response.status_code}."
                    )

                return FetchResult(
                    url=current,
                    status_code=response.status_code,
                    content_type=response.headers.get("Content-Type", ""),
                    text=_read_capped(response),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )
            finally:
                response.close()
    finally:
        session.close()

    raise ContentFetchError("That URL redirected too many times.")


# ── HTML metadata ─────────────────────────────────────────────────────────────


@dataclass
class PageMetadata:
    url: str
    title: str = ""
    description: str = ""
    site_name: str = ""
    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    canonical_url: str = ""
    feed_urls: list[str] = field(default_factory=list)


class _MetadataParser(HTMLParser):
    """Collects <title>, <meta> and <link rel> without a DOM library.

    ``convert_charrefs`` is on, so title text arrives already unescaped.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            self.metas.append(attributes)
        elif tag == "link":
            self.links.append(attributes)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)


def _first_meta(metas: list[dict[str, str]], keys: tuple[str, ...]) -> str:
    """Return the first non-empty meta content matching any of ``keys``.

    Key order is the priority order, so an OpenGraph tag beats a bare ``name=``.
    """
    for key in keys:
        for meta in metas:
            identity = (meta.get("property") or meta.get("name") or "").lower()
            if identity == key and meta.get("content", "").strip():
                return meta["content"].strip()
    return ""


def _parse_timestamp(value: str) -> datetime | None:
    """Parse the two date shapes feeds actually use: ISO 8601 and RFC 822."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_page_metadata(html: str, base_url: str) -> PageMetadata:
    """Extract drop-point fields from an HTML page.

    Also reports any advertised RSS/Atom feed, which is what lets a user paste an
    article URL and be offered the recurring supply behind it.
    """
    parser = _MetadataParser()
    try:
        parser.feed(html or "")
    except Exception as exc:  # malformed markup must not break ingestion
        logger.debug("[rippletrace] HTML parse degraded for %s: %s", base_url, exc)

    metas = parser.metas
    title = (
        _first_meta(metas, ("og:title", "twitter:title"))
        or unescape("".join(parser.title_parts)).strip()
    )
    description = _first_meta(metas, ("og:description", "twitter:description", "description"))
    site_name = _first_meta(metas, ("og:site_name", "application-name"))
    published = _parse_timestamp(
        _first_meta(metas, ("article:published_time", "datepublished", "date", "og:updated_time"))
    )

    tags: list[str] = []
    for meta in metas:
        identity = (meta.get("property") or meta.get("name") or "").lower()
        content = meta.get("content", "").strip()
        if not content:
            continue
        if identity in ("article:tag", "og:article:tag"):
            tags.append(content)
        elif identity == "keywords":
            tags.extend(part.strip() for part in content.split(",") if part.strip())

    canonical = ""
    feed_urls: list[str] = []
    for link in parser.links:
        rels = (link.get("rel") or "").lower().split()
        href = (link.get("href") or "").strip()
        if not href:
            continue
        if "canonical" in rels and not canonical:
            canonical = urljoin(base_url, href)
        if "alternate" in rels and any(
            token in (link.get("type") or "").lower() for token in ("rss", "atom", "xml")
        ):
            feed_urls.append(urljoin(base_url, href))

    return PageMetadata(
        url=base_url,
        title=title,
        description=description,
        site_name=site_name,
        published_at=published,
        tags=_dedupe_preserving_order(tags),
        canonical_url=canonical,
        feed_urls=_dedupe_preserving_order(feed_urls),
    )


# ── Feeds ─────────────────────────────────────────────────────────────────────


@dataclass
class FeedEntry:
    url: str
    title: str = ""
    summary: str = ""
    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class ParsedFeed:
    title: str = ""
    site_url: str = ""
    entries: list[FeedEntry] = field(default_factory=list)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name and (child.text or "").strip():
            return unescape(child.text.strip())
    return ""


def _atom_link(element, *, rel: str = "alternate") -> str:
    """Pick an Atom <link>. Prefers rel=alternate; falls back to any rel-less link."""
    fallback = ""
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        if not href:
            continue
        child_rel = (child.attrib.get("rel") or "alternate").lower()
        if child_rel == rel:
            return href
        if not fallback:
            fallback = href
    return fallback


def parse_feed(xml_text: str, base_url: str) -> ParsedFeed:
    """Parse RSS 2.0, RDF/RSS 1.0 or Atom into a uniform entry list.

    Raises ``ContentFetchError`` when the document is not a feed at all, so the caller
    can fall back to treating the URL as a page.
    """
    try:
        root = DefusedET.fromstring((xml_text or "").strip())
    except Exception as exc:
        raise ContentFetchError("That URL did not return a readable feed.") from exc

    root_name = _local_name(root.tag)
    if root_name == "feed":
        return _parse_atom(root, base_url)
    if root_name in ("rss", "rdf"):
        return _parse_rss(root, base_url)
    raise ContentFetchError("That URL did not return an RSS or Atom feed.")


def _parse_atom(root, base_url: str) -> ParsedFeed:
    feed = ParsedFeed(
        title=_child_text(root, "title"),
        site_url=urljoin(base_url, _atom_link(root)) if _atom_link(root) else "",
    )
    for element in root:
        if _local_name(element.tag) != "entry":
            continue
        href = _atom_link(element)
        if not href:
            continue
        feed.entries.append(
            FeedEntry(
                url=urljoin(base_url, href),
                title=_child_text(element, "title"),
                summary=_child_text(element, "summary") or _child_text(element, "content"),
                published_at=_parse_timestamp(
                    _child_text(element, "published") or _child_text(element, "updated")
                ),
                tags=_dedupe_preserving_order(
                    [
                        (child.attrib.get("term") or "").strip()
                        for child in element
                        if _local_name(child.tag) == "category"
                        and (child.attrib.get("term") or "").strip()
                    ]
                ),
            )
        )
    return feed


def _parse_rss(root, base_url: str) -> ParsedFeed:
    # RSS 2.0 nests items under <channel>; RDF/RSS 1.0 puts them beside it.
    channel = next((child for child in root if _local_name(child.tag) == "channel"), None)
    feed = ParsedFeed(
        title=_child_text(channel, "title") if channel is not None else "",
        site_url=_child_text(channel, "link") if channel is not None else "",
    )
    containers = [container for container in (channel, root) if container is not None]
    seen_items: list = []
    for container in containers:
        for element in container:
            if _local_name(element.tag) == "item" and element not in seen_items:
                seen_items.append(element)

    for element in seen_items:
        href = _child_text(element, "link") or _atom_link(element)
        if not href:
            # Some feeds only carry a permalink guid.
            guid = _child_text(element, "guid")
            href = guid if guid.startswith("http") else ""
        if not href:
            continue
        feed.entries.append(
            FeedEntry(
                url=urljoin(base_url, href),
                title=_child_text(element, "title"),
                summary=_child_text(element, "description"),
                published_at=_parse_timestamp(
                    _child_text(element, "pubdate")
                    or _child_text(element, "date")
                    or _child_text(element, "published")
                ),
                tags=_dedupe_preserving_order(
                    [
                        unescape((child.text or "").strip())
                        for child in element
                        if _local_name(child.tag) == "category" and (child.text or "").strip()
                    ]
                ),
            )
        )
    return feed


# ── Shared helpers ────────────────────────────────────────────────────────────


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = (value or "").strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def strip_html(text: str, *, limit: int = 2000) -> str:
    """Flatten a feed summary to plain text for theme extraction."""
    without_tags = re.sub(r"<[^>]+>", " ", text or "")
    collapsed = re.sub(r"\s+", " ", unescape(without_tags)).strip()
    return collapsed[:limit]
