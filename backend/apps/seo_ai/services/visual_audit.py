"""VisualAuditAgent — screenshot capture + (optional) multimodal review.

The shape:

  1. ``capture_page_screenshots(urls, viewport)`` — async Playwright pass
     that writes a PNG per URL into ``data/screenshots/<snapshot>/<hash>.png``
     and returns a manifest of ``{url, path, viewport, captured_at}``.
  2. ``analyse_screenshot(path, prompt)`` — sends the PNG to a multimodal
     model when ``VISUAL_LLM_PROVIDER`` is configured; otherwise emits a
     ``{available: False, reason: "no multimodal LLM"}`` stub so the
     orchestrator can keep going.

We deliberately keep the LLM call *behind a gate* so the screenshot
capture is useful even without multimodal credentials — the Inspector
UI can display the PNGs side-by-side (us vs them) with no LLM at all.
Adding Claude Sonnet 4.6 or GPT-4o vision later is a one-line config
swap.

Why a service not an agent: the screenshot capture is I/O-bound async,
the LLM call is per-image, and both are independently useful. Keeping
them as functions makes them composable from the Orchestrator V2,
ContentWriter (to ground "their hero looks like X" claims), and the
Custodians dashboard.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings

log = logging.getLogger("seo.ai.services.visual_audit")


@dataclass
class ScreenshotRecord:
    url: str
    path: str       # relative to BASE_DIR/data/screenshots
    viewport: str   # "1280x800" / "375x812" etc.
    captured_at: str
    bytes_written: int = 0
    error: str = ""


@dataclass
class VisualAuditResult:
    captured: list[ScreenshotRecord] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    elapsed_sec: float = 0.0
    error: str = ""


# ── helpers ───────────────────────────────────────────────────────────


def _shots_dir() -> Path:
    """Base directory for stored screenshots — created on demand."""
    base = Path(getattr(settings, "BASE_DIR", "")) / "data" / "screenshots"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()[:16]


# ── public API ──────────────────────────────────────────────────────


def capture_page_screenshots(
    urls: list[str],
    *,
    snapshot_id: str = "manual",
    viewport: tuple[int, int] = (1280, 800),
    timeout_ms: int = 20_000,
    full_page: bool = True,
) -> VisualAuditResult:
    """Capture one PNG per URL via Playwright.

    Synchronous wrapper around the Playwright async API so callers
    (Celery tasks, management commands, views) don't have to touch
    asyncio themselves. Falls back to ``error`` set on the result
    when Playwright isn't installed — never crashes the parent flow.

    URLs that 404 / timeout / get bot-detected return a ``skipped``
    entry; URLs that succeed return a ``captured`` entry pointing at
    the on-disk PNG.

    Storage layout::

        BASE_DIR/data/screenshots/<snapshot_id>/<hash16>.png

    ``hash16`` is the first 16 hex chars of sha256(url) so dedup is
    automatic across re-captures of the same URL.
    """
    t0 = time.monotonic()
    result = VisualAuditResult()
    if not urls:
        result.error = "no URLs provided"
        return result

    out_dir = _shots_dir() / snapshot_id
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        result.error = (
            f"Playwright not installed: {exc}. "
            "Add playwright to requirements + run 'playwright install chromium'."
        )
        return result

    vw_label = f"{viewport[0]}x{viewport[1]}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": viewport[0], "height": viewport[1]},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            for url in urls:
                page = context.new_page()
                target = out_dir / f"{_hash_url(url)}.png"
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    page.screenshot(
                        path=str(target),
                        full_page=full_page,
                        timeout=timeout_ms,
                    )
                    rec = ScreenshotRecord(
                        url=url,
                        path=str(target.relative_to(_shots_dir().parent.parent)),
                        viewport=vw_label,
                        captured_at=time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                        ),
                        bytes_written=target.stat().st_size if target.exists() else 0,
                    )
                    result.captured.append(rec)
                except Exception as exc:  # noqa: BLE001 — per-URL fault-tolerant
                    result.skipped.append({
                        "url": url,
                        "error": str(exc)[:200],
                    })
                    log.info("screenshot skipped %s: %s", url, exc)
                finally:
                    try:
                        page.close()
                    except Exception:  # noqa: BLE001
                        pass
            try:
                context.close()
                browser.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        result.error = f"playwright session failed: {exc}"
    finally:
        result.elapsed_sec = round(time.monotonic() - t0, 2)

    log.info(
        "capture_page_screenshots: captured=%d skipped=%d elapsed=%.1fs",
        len(result.captured), len(result.skipped), result.elapsed_sec,
    )
    return result


def analyse_screenshot(
    path: str | Path,
    *,
    prompt: str = "",
) -> dict[str, Any]:
    """Send a screenshot to a multimodal model for analysis.

    Gated by ``VISUAL_LLM_PROVIDER`` env var — when unset, returns a
    structured "not configured" stub so the orchestrator can carry
    on without crashing. Once the operator sets

      * ``VISUAL_LLM_PROVIDER=anthropic`` with ``ANTHROPIC_API_KEY``
      * or ``VISUAL_LLM_PROVIDER=openai`` with ``OPENAI_API_KEY``

    this function will dispatch the image + prompt to the configured
    vision model and return a structured analysis dict. The dispatch
    code is currently a stub — flip it on when the credentials land
    and the operator confirms the budget.
    """
    provider = (os.environ.get("VISUAL_LLM_PROVIDER") or "").strip().lower()
    if not provider:
        return {
            "available": False,
            "reason": "VISUAL_LLM_PROVIDER not set",
            "hint": (
                "Set VISUAL_LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY, "
                "or VISUAL_LLM_PROVIDER=openai + OPENAI_API_KEY, "
                "then re-run."
            ),
        }
    # Real implementation deferred until credentials are in hand —
    # see VISUAL_LLM dispatch in services/visual_audit_dispatch.py
    # (to be created once provider+key are confirmed).
    return {
        "available": False,
        "reason": f"provider '{provider}' configured but dispatcher not wired",
        "hint": "Add the dispatcher once the API key + budget are confirmed.",
    }
