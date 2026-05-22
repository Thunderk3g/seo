"""AXE-core color-contrast accessibility check via Playwright.

The pure-Python WCAG checks in Phase D.3 cannot evaluate color
contrast — that needs the browser's rendered CSS cascade. This
module spins up a Playwright Chromium per URL, injects axe-core
4.x, runs the ``color-contrast`` rule only, and returns the
violations.

Operator-tunable via env:
  CRAWLER_AXE_ENABLED         true / false (default false — opt-in
                              because it's slow: ~3-5s per URL)
  CRAWLER_AXE_TIMEOUT_MS      page-load timeout (default 20000)
  CRAWLER_AXE_VIEWPORT_W      device viewport width (default 1280)
  CRAWLER_AXE_VIEWPORT_H      device viewport height (default 800)

The axe-core script is loaded from CDN on first run and cached
in-process so subsequent runs don't re-fetch. If the CDN is blocked
(Cisco WSA / corporate proxy), set CRAWLER_AXE_SCRIPT_PATH to a
locally vendored copy of axe.min.js.

Returns a flat dict shaped for the page-result row:

  {
    "color_contrast_violations_count": int,   # element count
    "color_contrast_violations": [
        {"selector": str, "fg": str, "bg": str,
         "ratio": float, "expected": float, "impact": str,
         "snippet": str},
        ...  (capped at 20)
    ],
    "axe_tool_used": "playwright+axe" | "skipped" | "error",
    "axe_error_message": str,
  }
"""
from __future__ import annotations

import os
from typing import Any


# Cached axe-core script body. Populated on first run from CDN or
# local path; re-used for every subsequent URL in the same process.
_AXE_SOURCE: str | None = None


def _enabled() -> bool:
    return (os.environ.get("CRAWLER_AXE_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _empty(used: str = "skipped", error: str = "") -> dict:
    return {
        "color_contrast_violations_count": 0,
        "color_contrast_violations": [],
        "axe_tool_used": used,
        "axe_error_message": error,
    }


def _load_axe_source() -> str:
    """Lazy-load axe-core.

    Lookup order:
      1. ``CRAWLER_AXE_SCRIPT_PATH`` env points at a local axe.min.js.
      2. The vendored copy that ships with the ``axe-core-python``
         pip package (Cisco WSA-friendly — no outbound network).
      3. (Last resort) CDN. Will fail in environments without
         outbound HTTPS, by design.
    """
    global _AXE_SOURCE
    if _AXE_SOURCE is not None:
        return _AXE_SOURCE
    local_path = (os.environ.get("CRAWLER_AXE_SCRIPT_PATH") or "").strip()
    if local_path and os.path.isfile(local_path):
        with open(local_path, "r", encoding="utf-8") as f:
            _AXE_SOURCE = f.read()
        return _AXE_SOURCE
    # Vendored via axe-core-python pip dep — works offline / behind
    # corporate proxies that block cdnjs.
    try:
        import pathlib
        import axe_core_python  # type: ignore
        bundled = pathlib.Path(axe_core_python.__file__).parent / "axe.min.js"
        if bundled.is_file():
            with open(bundled, "r", encoding="utf-8") as f:
                _AXE_SOURCE = f.read()
            return _AXE_SOURCE
    except ImportError:
        pass
    # CDN last-resort. Fails in WSA-firewalled environments.
    import requests
    cdn_url = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"
    resp = requests.get(cdn_url, timeout=15)
    resp.raise_for_status()
    _AXE_SOURCE = resp.text
    return _AXE_SOURCE


def axe_color_contrast(url: str) -> dict:
    """Run axe-core's color-contrast rule against ``url`` in a real
    Chromium. Returns the flat violations dict described in the module
    docstring."""
    if not _enabled():
        return _empty("skipped")

    try:
        axe_source = _load_axe_source()
    except Exception as exc:  # noqa: BLE001 — CDN or local read failure
        return _empty("error", f"axe-core load failed: {exc}")

    timeout_ms = int(os.environ.get("CRAWLER_AXE_TIMEOUT_MS", "20000"))
    vp_w = int(os.environ.get("CRAWLER_AXE_VIEWPORT_W", "1280"))
    vp_h = int(os.environ.get("CRAWLER_AXE_VIEWPORT_H", "800"))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _empty("error", "playwright not installed in this container")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            try:
                context = browser.new_context(viewport={"width": vp_w, "height": vp_h})
                page = context.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                # Best-effort settle for late-rendered content; we don't
                # need full networkidle because color contrast is computed
                # from already-laid-out DOM.
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:  # noqa: BLE001 — fall through; we have what we have
                    pass
                page.add_script_tag(content=axe_source)
                # Run ONLY the color-contrast rule for speed. Operators
                # who want the full WCAG suite can change the runOnly arg.
                axe_result = page.evaluate(
                    """async () => {
                        return await axe.run(document, {
                          runOnly: { type: 'rule', values: ['color-contrast'] }
                        });
                    }"""
                )
                def _ratio_float(v):
                    """axe returns ratios as strings like '4.5:1' or '12.83'
                    depending on the field — coerce to a float we can sort on."""
                    if v is None or v == "":
                        return 0.0
                    s = str(v)
                    if ":" in s:
                        s = s.split(":", 1)[0]
                    try:
                        return float(s)
                    except (TypeError, ValueError):
                        return 0.0

                violations = []
                for v in axe_result.get("violations", []) or []:
                    for node in (v.get("nodes") or [])[:20]:
                        any_data = (node.get("any") or [{}])[0].get("data") or {}
                        violations.append({
                            "selector": (node.get("target") or [""])[0],
                            "fg": any_data.get("fgColor", ""),
                            "bg": any_data.get("bgColor", ""),
                            "ratio": _ratio_float(any_data.get("contrastRatio")),
                            "expected": _ratio_float(any_data.get("expectedContrastRatio")),
                            "impact": v.get("impact", ""),
                            "snippet": (node.get("html") or "")[:240],
                        })
                return {
                    "color_contrast_violations_count": len(violations),
                    "color_contrast_violations": violations[:20],
                    "axe_tool_used": "playwright+axe",
                    "axe_error_message": "",
                }
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 — never break the crawl
        return _empty("error", str(exc)[:240])
