"""Hostname helpers — single source of truth for parent-brand resolution.

`auth.hdfclife.com`, `customer.hdfclife.com`, `hdfclife.com` all share the
parent brand `hdfclife.com`. We compute that via tldextract against the
bundled Public Suffix List (no network at import — the corp proxy blocks
publicsuffix.org). Every writer of `CrawlSnapshot.target_domain` should
flow through `apex()` for the consolidated competitor table to roll up
correctly. The `CrawlSnapshot.save()` override does this automatically.
"""
from __future__ import annotations

from urllib.parse import urlparse

import tldextract


# `suffix_list_urls=()` pins to the bundled PSL snapshot only. Without
# this, tldextract's first call fetches publicsuffix.org which the
# corporate proxy will reject — same class of failure as the pip-on-
# PyTorch-index TLS issue. Reusable instance is faster than building a
# new TLDExtract per call.
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())


def apex(host_or_url: str) -> str:
    """Return the registrable parent domain for a host or URL.

    Examples::

        apex("auth.hdfclife.com")             == "hdfclife.com"
        apex("https://www.tataaia.com/x")     == "tataaia.com"
        apex("sales.baliconline.in")          == "baliconline.in"
        apex("")                              == ""
        apex("localhost")                     == "localhost"

    Falls back to the input (lowercased, stripped) when tldextract can't
    resolve a public suffix — keeps test fixtures and weird internal
    hosts working without raising.
    """
    raw = (host_or_url or "").strip().lower()
    if not raw:
        return ""

    # Accept either a bare host or a full URL.
    if "://" in raw:
        host = urlparse(raw).netloc or raw
    else:
        host = raw

    # Strip port if present.
    if ":" in host:
        host = host.rsplit(":", 1)[0]

    ext = _EXTRACT(host)
    if ext.registered_domain:
        return ext.registered_domain
    # tldextract returns blank registered_domain for single-label hosts
    # like 'localhost' or IPs. Fall back to the host we had.
    return host
