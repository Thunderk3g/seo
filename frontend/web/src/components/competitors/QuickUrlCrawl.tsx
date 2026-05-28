/**
 * QuickUrlCrawl — paste any URL, get the unified PageDetailPage.
 *
 * Sits at the top of the Competitors page so the operator can spot-
 * check any competitor URL (or any URL at all) without waiting for
 * the nightly walk. Hits POST /api/v1/crawler/adhoc which:
 *   1. Validates the URL.
 *   2. Singleton-upserts a CrawlSnapshot(kind='adhoc', target_domain=<host>).
 *   3. Fetches + parses synchronously (1-30 s).
 *   4. Writes a CrawlerPageResult row with H1s / internal links / images
 *      / body text / JSON-LD — same shape as a competitor walk row.
 *
 * On success, navigates to /adhoc/pages/<snap>/<b64> which renders via
 * the unified PageDetailPage (Phase 2). The detail page reads
 * snapshot_kind='adhoc' and swaps its breadcrumb accordingly.
 */
import { useState } from 'react';
import { useLocation } from 'wouter';
import { crawlerApi } from '../../crawler/api';

export default function QuickUrlCrawl() {
  const [, setLocation] = useLocation();
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const target = url.trim();
    if (!target) {
      setError('Paste a URL first');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await crawlerApi.adhocCrawl(target);
      if (r.error) {
        setError(r.error);
      } else {
        setLocation(`/adhoc/pages/${r.snapshot_id}/${r.url_b64}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'fetch failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        alignItems: 'center',
        padding: '10px 12px',
        marginTop: 12,
        border: '1px solid var(--border, #E5E7EB)',
        borderRadius: 8,
        background: 'var(--bg-2, #F9FAFB)',
      }}
    >
      <form
        onSubmit={submit}
        style={{ display: 'flex', flex: 1, gap: 8, alignItems: 'center' }}
      >
        <label
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--text-2, #374151)',
            whiteSpace: 'nowrap',
          }}
        >
          Quick URL crawl
        </label>
        <input
          type="text"
          inputMode="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://kotaklife.com/term-insurance"
          disabled={busy}
          style={{
            flex: 1,
            padding: '6px 10px',
            fontSize: 13,
            border: '1px solid var(--border, #D1D5DB)',
            borderRadius: 6,
            background: '#FFFFFF',
            fontFamily: 'ui-monospace, monospace',
          }}
        />
        <button
          type="submit"
          disabled={busy || !url.trim()}
          style={{
            padding: '6px 14px',
            fontSize: 13,
            fontWeight: 600,
            background: busy ? '#9CA3AF' : 'var(--accent, #003DA5)',
            color: '#FFFFFF',
            border: 'none',
            borderRadius: 6,
            cursor: busy ? 'progress' : 'pointer',
          }}
        >
          {busy ? 'Crawling…' : 'Crawl'}
        </button>
      </form>
      {error && (
        <div
          style={{
            fontSize: 12,
            color: '#B91C1C',
            background: '#FEE2E2',
            padding: '4px 8px',
            borderRadius: 4,
            whiteSpace: 'nowrap',
            maxWidth: 320,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
          title={error}
        >
          {error}
        </div>
      )}
    </div>
  );
}
