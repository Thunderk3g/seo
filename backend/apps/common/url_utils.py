"""URL handling utilities shared across the backend.

The primary helper is :func:`normalize_seed_url`, which canonicalises
user-supplied domains/URLs before they are handed to the crawler engine.
It defends against the duplicated-scheme bug (e.g. ``https://https://...``)
that previously caused the crawler to construct invalid URLs such as
``https://https:/robots.txt`` and fail with DNS errors.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_SCHEME_PREFIX_RE = re.compile(r"^https?://", re.IGNORECASE)
_ANY_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
# A permissive host validator: letters, digits, dots, hyphens, plus optional
# punycode/IDN characters. Rejects whitespace and other obviously-bad input.
_HOST_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_seed_url(raw: str) -> str:
    """Accept a user-supplied domain. Return canonical ``https://<host>/<path>``
    or raise :class:`ValueError`.

    Handles: bare domain, http(s)://, scheme-relative ``//``, leading/trailing
    whitespace, *duplicated schemes* (the actual bug), default-port stripping
    (``:443`` for https, ``:80`` for http), IDN hosts (encoded as punycode),
    paths/query preservation, and rejection of non-http(s) schemes / non-URLs.
    """
    if not isinstance(raw, str):
        raise ValueError("seed url must be a string")

    s = raw.strip()
    if not s:
        raise ValueError("seed url is empty")

    # 1) Strip duplicated leading http(s):// prefixes. After every strip we
    #    re-check whether the remainder *still* starts with another scheme;
    #    if so, strip again. We stop as soon as zero-or-one scheme remains.
    while True:
        m = _SCHEME_PREFIX_RE.match(s)
        if not m:
            break
        rest = s[m.end():]
        if _SCHEME_PREFIX_RE.match(rest):
            # The remainder still has another scheme — drop the leading one
            # and loop. This collapses ``https://https://x.com`` → ``x.com``.
            s = rest
            continue
        # Single (or terminal) scheme — keep it and exit the loop.
        break

    # 2) Re-attach a scheme if needed.
    if s.startswith("//"):
        # Scheme-relative form (e.g. ``//x.com/path``) → assume https.
        s = "https:" + s
    elif not _SCHEME_PREFIX_RE.match(s):
        # Anything else with a scheme prefix at this point (e.g. ``ftp://x``)
        # is not http/https and must be rejected up front. Otherwise treat as
        # a bare domain and default to https.
        if _ANY_SCHEME_RE.match(s):
            raise ValueError(f"unsupported scheme in {raw!r}")
        s = "https://" + s

    parsed = urlsplit(s)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {parsed.scheme!r}")

    # urlsplit returns hostname lowercased & strips brackets; port separately.
    host = parsed.hostname
    if not host:
        raise ValueError(f"could not extract host from {raw!r}")

    # 3) Punycode-encode non-ASCII (IDN) hosts. Pure-ASCII hosts may contain
    #    characters (e.g. ``_``) that ``encode('idna')`` rejects, so we only
    #    invoke idna encoding when the host is non-ASCII.
    try:
        host.encode("ascii")
        ascii_host = host
    except UnicodeEncodeError:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError(f"invalid IDN host {host!r}: {exc}") from exc

    ascii_host = ascii_host.lower()

    # Reject hosts containing whitespace or other characters that would never
    # appear in a real domain (e.g. ``"not a url"`` parsed as a bare domain).
    if not _HOST_RE.match(ascii_host):
        raise ValueError(f"invalid host {ascii_host!r}")

    # 4) Re-assemble netloc, dropping default ports.
    port = parsed.port
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{ascii_host}:{port}"
    else:
        netloc = ascii_host

    # 5) Path defaults to "/", query is preserved, fragment is dropped.
    path = parsed.path or "/"
    query = parsed.query

    return urlunsplit((scheme, netloc, path, query, ""))
