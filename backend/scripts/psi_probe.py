"""Read-only PageSpeed Insights (Core Web Vitals) connectivity probe.

Answers ONE question: "Is CWV/PSI actually working?" — the same way gsc_probe
answers it for Search Console. It boots Django, builds the real PSIAdapter the
crawler uses, and fetches CWV for a single URL, then PRINTS the result (metrics
or the exact error). It writes nothing except PSI's normal 7-day disk cache.

    python backend/scripts/psi_probe.py [url]
"""
import os
import sys
from pathlib import Path

# Run-from-anywhere: put the Django project root (backend/) on sys.path so
# `config` and `apps` import the same way manage.py sees them.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from apps.seo_ai.adapters.cwv_psi import PSIAdapter, AdapterDisabledError  # noqa: E402


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.bajajlifeinsurance.com/"
    print("=== PSI / Core Web Vitals probe (read-only) ===")
    cfg = getattr(settings, "PSI", {}) or {}
    print(f"  enabled            : {cfg.get('enabled')}")
    print(f"  service_account    : {cfg.get('service_account_json')}")
    print(f"  strategies         : {cfg.get('strategies')}")
    print(f"  ssl_verify (raw)   : {cfg.get('ssl_verify')!r}")
    print(f"  probing URL        : {url}\n")

    try:
        psi = PSIAdapter()
    except AdapterDisabledError as exc:
        print(f"[FAIL] PSI adapter disabled: {exc}")
        print("       -> CWV will be silently skipped on every crawl.")
        sys.exit(1)

    print("[..] Fetching mobile strategy (this can take 5-40s)...")
    rec = psi.fetch(url, strategy="mobile")

    if rec.error:
        print(f"[FAIL] PSI returned an error: {rec.error}")
        low = rec.error.lower()
        if "auth" in low or "token" in low or "invalid_grant" in low or "401" in low or "403" in low:
            print("       -> Service-account auth problem (token mint/refresh or API not enabled).")
            print("          Check: PageSpeed Insights API enabled on project geoseo-496810,")
            print("          and the SA key in data/secrets/psi-sa.json is not revoked.")
        elif "ssl" in low or "certificate" in low:
            print("       -> TLS interception. Set PSI_SSL_VERIFY=false or point it at the corp CA bundle.")
        sys.exit(1)

    print(f"[PASS] CWV IS WORKING (cached={rec.cached}, latency={rec.latency_ms}ms)")
    print(f"       performance score : {rec.performance_score}")
    print(f"       lab  LCP={rec.lab_lcp_ms}ms  CLS={rec.lab_cls}  TBT={rec.lab_tbt_ms}ms  TTFB={rec.lab_ttfb_ms}ms")
    if rec.has_field_data:
        print(f"       field LCP={rec.field_lcp_ms}ms ({rec.field_lcp_category})  "
              f"CLS={rec.field_cls} ({rec.field_cls_category})  "
              f"INP={rec.field_inp_ms}ms ({rec.field_inp_category})")
    else:
        print("       field (CrUX) data: none (normal for low-traffic URLs)")


if __name__ == "__main__":
    main()
