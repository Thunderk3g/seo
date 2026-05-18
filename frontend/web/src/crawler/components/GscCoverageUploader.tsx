import { useState } from 'react';
import Icon from './Icon';
import { crawlerApi } from '../api';

/**
 * Banner reminding the operator how to feed GSC Coverage data into the
 * crawler reports, with a one-click "Refresh" that flushes the in-memory
 * cache so the next page render uses the newest CSV in
 * ``backend/data/gsc/coverage/``.
 */
export default function GscCoverageUploader() {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setBusy(true);
    setStatus(null);
    setError(null);
    try {
      const res = await crawlerApi.refreshGscCoverage();
      if (res.loaded_urls > 0) {
        setStatus(`Loaded ${res.loaded_urls.toLocaleString()} URLs from the latest export.`);
      } else {
        setStatus('No coverage CSV found in backend/data/gsc/coverage/.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cc-gsc-banner card">
      <div className="cc-gsc-banner__icon">
        <Icon name="cloud_upload" />
      </div>
      <div className="cc-gsc-banner__body">
        <div className="cc-gsc-banner__title">Google Search Console — indexing data</div>
        <div className="cc-gsc-banner__desc">
          Export the <strong>Indexing → Pages</strong> report from Search Console as CSV, rename it{' '}
          <code>coverage_YYYY-MM-DD.csv</code>, and drop it in{' '}
          <code>backend/data/gsc/coverage/</code>. The reports automatically use the most recently
          modified file. Click refresh after dropping a new file.
        </div>
        {status && <div className="cc-gsc-banner__status cc-gsc-banner__status--ok">{status}</div>}
        {error && <div className="cc-gsc-banner__status cc-gsc-banner__status--err">{error}</div>}
      </div>
      <button
        type="button"
        className="btn btn-primary"
        onClick={refresh}
        disabled={busy}
      >
        <Icon name={busy ? 'hourglass_empty' : 'refresh'} />
        {busy ? 'Refreshing…' : 'Refresh GSC coverage'}
      </button>
    </div>
  );
}
