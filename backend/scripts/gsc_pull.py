"""Google Search Console batch puller.

Refactored from the original ``test/gsc_pull.py`` so it can be invoked
from any working directory: paths are anchored against the project's
``test/`` directory where the OAuth secrets and pulled CSVs already
live. Run with:

    python backend/scripts/gsc_pull.py

OAuth client secret + cached token + CSV outputs all stay under
``test/`` (gitignored). The SEO AI ``GSCCSVAdapter`` reads from the
same ``test/gsc_data/`` tree by default.
"""
import os
import csv
import json
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Anchor every path against ``<repo>/test/`` so this works regardless
# of cwd. The original script assumed cwd == test/.
_TEST_DIR = Path(__file__).resolve().parents[2] / "test"

SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']
CLIENT_SECRETS_FILE = str(
    _TEST_DIR
    / 'client_secret_247784932262-kb00a8epkqisvnadt095j0bi8njut3es.apps.googleusercontent.com.json'
)
TOKEN_FILE = str(_TEST_DIR / 'token.json')
OUTPUT_DIR = str(_TEST_DIR / 'gsc_data')

# GSC retains ~16 months of data. Use 480 days to capture the full window.
LOOKBACK_DAYS = 480
# GSC reporting has a ~2-3 day lag.
DATA_LAG_DAYS = 3
# Max rows the API returns per request.
ROW_LIMIT_PER_REQUEST = 25000

# Force Google sign-in to open in Chrome where possible.
_CHROME_PATHS = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    os.path.expanduser(r'~\AppData\Local\Google\Chrome\Application\chrome.exe'),
]
for _chrome_path in _CHROME_PATHS:
    if os.path.exists(_chrome_path):
        webbrowser.register(
            'chrome', None, webbrowser.BackgroundBrowser(_chrome_path), preferred=True
        )
        break


def get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                print(f"Error: {CLIENT_SECRETS_FILE} not found.")
                return None
            print("Please check your browser for the Google Sign-in page...")
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES, redirect_uri='http://localhost:8080/'
            )
            creds = flow.run_local_server(port=8080)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('searchconsole', 'v1', credentials=creds)


def safe_name(site_url):
    return (site_url
            .replace('https://', '')
            .replace('http://', '')
            .replace('sc-domain:', 'sc-domain_')
            .replace('/', '_')
            .replace(':', '_')
            .strip('_'))


def fetch_all_rows(service, site_url, start_date, end_date, dimensions, search_type='web'):
    """Paginate through all rows for the given dimension set and search type."""
    all_rows = []
    start_row = 0
    while True:
        body = {
            'startDate': start_date,
            'endDate': end_date,
            'dimensions': dimensions,
            'rowLimit': ROW_LIMIT_PER_REQUEST,
            'startRow': start_row,
            'type': search_type,
            'dataState': 'all',
        }
        for attempt in range(3):
            try:
                response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
                break
            except HttpError as e:
                status = getattr(e.resp, 'status', None)
                if status in (429, 500, 503) and attempt < 2:
                    wait = 2 ** attempt
                    print(f"    transient error {status}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                print(f"    ! API error for dims={dimensions}, type={search_type}: {e}")
                return all_rows
        rows = response.get('rows', [])
        all_rows.extend(rows)
        if len(rows) < ROW_LIMIT_PER_REQUEST:
            break
        start_row += ROW_LIMIT_PER_REQUEST
        print(f"    paginating... {len(all_rows)} rows so far")
    return all_rows


def save_rows_csv(rows, dimensions, path):
    if not rows:
        return 0
    fieldnames = list(dimensions) + ['clicks', 'impressions', 'ctr', 'position']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            entry = {}
            for i, dim in enumerate(dimensions):
                entry[dim] = row['keys'][i]
            entry['clicks'] = row.get('clicks', 0)
            entry['impressions'] = row.get('impressions', 0)
            entry['ctr'] = row.get('ctr', 0)
            entry['position'] = row.get('position', 0)
            writer.writerow(entry)
    return len(rows)


def pull_site_data(service, site_url):
    end_date = (datetime.now() - timedelta(days=DATA_LAG_DAYS)).strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS + DATA_LAG_DAYS)).strftime('%Y-%m-%d')
    print(f"\n=== {site_url} ({start_date} to {end_date}) ===")

    site_dir = os.path.join(OUTPUT_DIR, safe_name(site_url))
    os.makedirs(site_dir, exist_ok=True)

    dimension_sets = [
        ['query'],
        ['page'],
        ['country'],
        ['device'],
        ['date'],
        ['searchAppearance'],
        ['query', 'page'],
        ['query', 'country'],
        ['query', 'device'],
        ['page', 'country'],
        ['page', 'device'],
        ['date', 'device'],
        ['date', 'country'],
    ]
    search_types = ['web', 'image', 'video', 'news', 'discover', 'googleNews']

    for stype in search_types:
        for dims in dimension_sets:
            label = f"{stype}__{'_'.join(dims)}"
            print(f"  fetching {label} ...")
            rows = fetch_all_rows(service, site_url, start_date, end_date, dims, search_type=stype)
            if rows:
                fname = os.path.join(site_dir, f"{label}.csv")
                n = save_rows_csv(rows, dims, fname)
                print(f"    saved {n} rows -> {fname}")
            else:
                print(f"    no data")

    # Sitemaps list + per-sitemap detail
    try:
        sitemaps = service.sitemaps().list(siteUrl=site_url).execute().get('sitemap', [])
        if sitemaps:
            with open(os.path.join(site_dir, 'sitemaps.json'), 'w', encoding='utf-8') as f:
                json.dump(sitemaps, f, indent=2, default=str)
            print(f"  saved {len(sitemaps)} sitemap entries -> sitemaps.json")
        else:
            print("  no sitemaps")
    except HttpError as e:
        print(f"  ! sitemaps error: {e}")


def main():
    service = get_service()
    if not service:
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    sites = service.sites().list().execute().get('siteEntry', [])
    print(f"\n--- {len(sites)} verified site(s) ---")
    for i, s in enumerate(sites, 1):
        print(f"{i}. {s['siteUrl']} ({s['permissionLevel']})")

    with open(os.path.join(OUTPUT_DIR, 'sites.json'), 'w', encoding='utf-8') as f:
        json.dump(sites, f, indent=2)

    accessible = [s for s in sites if s.get('permissionLevel') != 'siteUnverifiedUser']
    print(f"\nPulling data for {len(accessible)} accessible site(s)...")

    for s in accessible:
        try:
            pull_site_data(service, s['siteUrl'])
        except HttpError as e:
            print(f"!! Failed for {s['siteUrl']}: {e}")

    print(f"\nDone. Data saved under: {OUTPUT_DIR}/")


if __name__ == '__main__':
    main()
