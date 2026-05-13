"""Smoke test for the SEO AI Agent System.

Runs the orchestrator inline against the real crawler / GSC / sitemap
data on disk and the live Groq API. Used once to verify Phase 0 works
end-to-end; not part of the test suite (it bills Groq).

    python smoke_test_seo_ai.py
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

# Windows cp1252 console can't render anything outside the BCP-codepage.
# Force UTF-8 so we can print quoted titles / narrative without crashes.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # py3.7+
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Load .env explicitly — Django's settings module does not pull dotenv.
ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

# Force SQLite for the smoke test even if .env points at the Postgres
# dev settings. The hard set overrides whatever the env file loaded.
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.dev_sqlite"

import django
django.setup()

from apps.seo_ai.agents.orchestrator import Orchestrator  # noqa: E402
from apps.seo_ai.models import SEORun  # noqa: E402


def main() -> int:
    domain = sys.argv[1] if len(sys.argv) > 1 else "bajajlifeinsurance.com"
    print(f"Running grading for {domain}...")
    run = SEORun.objects.create(domain=domain, triggered_by="smoke_test")
    try:
        Orchestrator(run).execute()
    except Exception as exc:
        print(f"FAILED: {exc}")
        run.refresh_from_db()
        print(f"  status={run.status} error={run.error[:200]!r}")
        return 1

    run.refresh_from_db()
    print(f"\nRun {run.id} -> status={run.status}")
    print(f"  overall_score : {run.overall_score}")
    print(f"  sub_scores    : {run.sub_scores}")
    print(f"  total cost USD: {run.total_cost_usd:.4f}")
    findings = run.findings.all().order_by("-priority")[:8]
    print(f"\nTop {len(findings)} findings:")
    for f in findings:
        print(
            f"  [{f.severity:<8}] ({f.agent}) {f.title} — priority={f.priority}"
        )
    nar = (run.model_versions or {}).get("narrative") or {}
    if nar:
        print("\nExecutive summary:")
        print(nar.get("executive_summary", "(none)"))
        print(f"\nAction this week: {nar.get('top_action_this_week', '(none)')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
