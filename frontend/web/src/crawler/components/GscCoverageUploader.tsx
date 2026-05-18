import { useState } from 'react';
import Icon from './Icon';
import { crawlerApi } from '../api';

/**
 * GSC coverage actions for the Reports page.
 *
 * Two buttons:
 *   - "Pull coverage from GSC" (primary) — runs the derivation against the
 *     latest performance CSVs in backend/data/gsc/<site>/ and a fresh
 *     sitemap.xml fetch. Writes a new coverage_derived_*.csv and rewrites
 *     the indexed_status column on every crawler CSV in one go.
 *   - "Refresh cache" (ghost) — used when an operator has manually dropped
 *     a coverage CSV themselves and just needs the in-memory cache flushed.
 */
export default function GscCoverageUploader() {
  const [busy, setBusy] = useState<'build' | 'inspect' | 'refresh' | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function buildCoverage() {
    setBusy('build');
    setStatus(null);
    setError(null);
    try {
      const res = await crawlerApi.buildGscCoverage({ backfill: true });
      if (!res.ok || !res.coverage) {
        setError(res.error || 'Coverage build failed.');
        return;
      }
      const c = res.coverage;
      const bf = res.backfill;
      const lines: string[] = [
        `Coverage built: ${c.indexed.toLocaleString()} indexed (proven), `
          + `${c.excluded.toLocaleString()} excluded, `
          + `${c.unknown.toLocaleString()} unknown (run URL Inspection to verify).`,
        `From ${c.indexed_urls_seen.toLocaleString()} performing URLs and `
          + `${c.sitemap_urls_seen.toLocaleString()} sitemap URLs.`,
      ];
      if (bf) {
        const total = Object.values(bf.files).reduce((s, f) => s + (f.updated ?? 0), 0);
        lines.push(`Sitemap backfill: ${total.toLocaleString()} rows updated.`);
      }
      setStatus(lines.join(' '));
      window.setTimeout(() => window.location.reload(), 1200);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function inspectUnknowns() {
    setBusy('inspect');
    setStatus(null);
    setError(null);
    try {
      const res = await crawlerApi.inspectGscUnknowns({ max: 1900 });
      if (!res.ok) {
        setError(res.error || 'URL Inspection failed.');
        return;
      }
      if (res.msg) {
        setStatus(res.msg);
        return;
      }
      const inspected = res.inspected ?? 0;
      const remaining = res.remaining ?? 0;
      const errors = res.errors ?? 0;
      setStatus(
        `Inspected ${inspected.toLocaleString()} URLs via GSC. `
        + (remaining > 0
            ? `${remaining.toLocaleString()} still unknown — run again tomorrow (2,000/day quota).`
            : 'All unknowns processed.')
        + (errors > 0 ? ` (${errors} errors skipped.)` : ''),
      );
      window.setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function refreshCache() {
    setBusy('refresh');
    setStatus(null);
    setError(null);
    try {
      const res = await crawlerApi.refreshGscCoverage();
      setStatus(
        res.loaded_urls > 0
          ? `Reloaded ${res.loaded_urls.toLocaleString()} URLs from the latest CSV.`
          : 'No coverage CSV present yet — click "Pull coverage from GSC" first.',
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="cc-gsc-banner card">
      <div className="cc-gsc-banner__icon">
        <Icon name="cloud_sync" />
      </div>
      <div className="cc-gsc-banner__body">
        <div className="cc-gsc-banner__title">Google Search Console — indexing data</div>
        <div className="cc-gsc-banner__desc">
          Click <strong>Pull coverage from GSC</strong> to derive indexed / not-indexed / excluded
          buckets from the performance data already in <code>backend/data/gsc/</code> plus a fresh
          <code>sitemap.xml</code> fetch. Also rewrites <code>from_sitemap</code> and{' '}
          <code>indexed_status</code> on every crawler CSV. No URL Inspection quota burnt.
          If you exported a Coverage CSV manually instead, click <strong>Refresh cache</strong>.
        </div>
        {status && <div className="cc-gsc-banner__status cc-gsc-banner__status--ok">{status}</div>}
        {error && <div className="cc-gsc-banner__status cc-gsc-banner__status--err">{error}</div>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'stretch' }}>
        <button
          type="button"
          className="btn btn-primary"
          onClick={buildCoverage}
          disabled={busy !== null}
        >
          <Icon name={busy === 'build' ? 'hourglass_empty' : 'cloud_download'} />
          {busy === 'build' ? 'Pulling…' : 'Pull coverage from GSC'}
        </button>
        <button
          type="button"
          className="btn btn-accent"
          onClick={inspectUnknowns}
          disabled={busy !== null}
          title="Calls URL Inspection API for the 'No GSC signal' set. Quota: 2,000/day."
        >
          <Icon name={busy === 'inspect' ? 'hourglass_empty' : 'verified'} />
          {busy === 'inspect' ? 'Inspecting…' : 'Verify unknowns'}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={refreshCache}
          disabled={busy !== null}
        >
          <Icon name={busy === 'refresh' ? 'hourglass_empty' : 'refresh'} />
          {busy === 'refresh' ? 'Refreshing…' : 'Refresh cache'}
        </button>
      </div>
    </div>
  );
}
