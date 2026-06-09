"""Read-only Google Search Console connectivity probe.

Answers ONE question: "Is GSC data still pulling?" — without touching anything.

It loads the cached OAuth token, refreshes it IN MEMORY ONLY (never writes
token.json back), makes a single read-only searchanalytics query for the last
~10 days, and PRINTS the result. It creates no CSVs, overwrites nothing, and
deletes nothing. The full puller (gsc_pull.py) is left untouched.

    python backend/scripts/gsc_probe.py
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Mirror gsc_pull.py's anchoring so paths resolve regardless of cwd.
_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "gsc"
SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']
TOKEN_FILE = str(_DATA_DIR / 'token.json')
SITES_FILE = str(_DATA_DIR / 'sites.json')

# Match the puller's reporting lag; widen the window so we don't false-negative.
DATA_LAG_DAYS = 3
PROBE_WINDOW_DAYS = 10


def get_service_readonly():
    """Build the GSC service WITHOUT persisting any token changes to disk."""
    if not os.path.exists(TOKEN_FILE):
        print(f"[FAIL] No cached token at {TOKEN_FILE} — never authenticated.")
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.valid:
        print("[ok] Cached access token still valid.")
    elif creds and creds.expired and creds.refresh_token:
        print("[..] Access token expired; refreshing in memory (token.json NOT rewritten)...")
        try:
            creds.refresh(Request())
            print("[ok] Refresh succeeded — refresh token is still good.")
        except Exception as e:  # google.auth.exceptions.RefreshError etc.
            print(f"[FAIL] Refresh failed: {e}")
            print("       -> The refresh token is likely revoked/expired.")
            print("       -> Fix: run `python backend/scripts/gsc_pull.py` once to re-auth in the browser.")
            return None
    else:
        print("[FAIL] No valid creds and no refresh token — browser re-auth required.")
        return None
    return build('searchconsole', 'v1', credentials=creds)


def pick_site(service):
    sites = service.sites().list().execute().get('siteEntry', [])
    print(f"[ok] API reachable — {len(sites)} verified site(s):")
    for s in sites:
        print(f"       - {s['siteUrl']} ({s['permissionLevel']})")
    accessible = [s for s in sites if s.get('permissionLevel') != 'siteUnverifiedUser']
    return accessible[0]['siteUrl'] if accessible else None


def probe(service, site_url):
    end_date = (datetime.now() - timedelta(days=DATA_LAG_DAYS)).strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=DATA_LAG_DAYS + PROBE_WINDOW_DAYS)).strftime('%Y-%m-%d')
    print(f"\n[..] Querying {site_url}  web/date  {start_date} .. {end_date}")
    body = {
        'startDate': start_date,
        'endDate': end_date,
        'dimensions': ['date'],
        'rowLimit': 25,
        'type': 'web',
        'dataState': 'all',
    }
    rows = service.searchanalytics().query(siteUrl=site_url, body=body).execute().get('rows', [])
    if not rows:
        print("[WARN] Auth works but 0 rows returned for this window (no recent data?).")
        return
    dates = sorted(r['keys'][0] for r in rows)
    total_clicks = sum(r.get('clicks', 0) for r in rows)
    total_impr = sum(r.get('impressions', 0) for r in rows)
    print(f"[PASS] GSC IS PULLING — {len(rows)} day-rows, {dates[0]} .. {dates[-1]}")
    print(f"       totals over window: clicks={int(total_clicks)}, impressions={int(total_impr)}")
    print("       sample (latest 3 days):")
    for r in sorted(rows, key=lambda r: r['keys'][0])[-3:]:
        print(f"         {r['keys'][0]}: clicks={int(r.get('clicks',0))} "
              f"impr={int(r.get('impressions',0))} pos={r.get('position',0):.1f}")


def main():
    print("=== GSC read-only probe (no files written, nothing deleted) ===")
    service = get_service_readonly()
    if not service:
        sys.exit(1)
    try:
        site_url = pick_site(service)
        if not site_url:
            print("[FAIL] No accessible site.")
            sys.exit(1)
        probe(service, site_url)
    except HttpError as e:
        print(f"[FAIL] API error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
