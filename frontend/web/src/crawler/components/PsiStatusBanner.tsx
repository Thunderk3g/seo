// Banner that surfaces the last PSI / Core Web Vitals run outcome on
// the Reports landing page. The four PSI columns (pagespeed_score,
// lcp_ms, cls, inp_ms) in crawl_results.csv used to fail silently when
// Phase 3 didn't run — this banner makes the failure (or success)
// explicit so the operator knows whether to expect populated values
// in the table.

import { useEffect, useState } from 'react';
import Icon from './Icon';
import { crawlerApi } from '../api';

type PsiStatus = Awaited<ReturnType<typeof crawlerApi.psiStatus>>;

function formatTime(iso?: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

export default function PsiStatusBanner() {
  const [status, setStatus] = useState<PsiStatus | null>(null);

  useEffect(() => {
    let alive = true;
    crawlerApi
      .psiStatus()
      .then((s) => alive && setStatus(s))
      .catch(() => alive && setStatus(null));
    return () => {
      alive = false;
    };
  }, []);

  if (!status || Object.keys(status).length === 0) {
    // No PSI run has happened yet — don't render anything.
    return null;
  }

  // Phase 3 ran successfully — green confirmation card.
  if (status.ok) {
    const merged = status.rows_written ?? 0;
    const inspected = status.urls_inspected ?? 0;
    const failed = status.failed ?? 0;
    return (
      <div
        className="card"
        style={{
          padding: 12,
          marginBottom: 16,
          borderColor: 'var(--green)',
          background: 'rgba(34, 197, 94, 0.06)',
          color: 'var(--text-1)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icon name="speed" />
          <strong>Page Speed (PSI) — last run OK</strong>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 4 }}>
          Merged <strong>{merged}</strong> PSI rows into{' '}
          <code>crawl_results.csv</code> from{' '}
          <strong>{inspected}</strong> URLs
          {failed > 0 && (
            <>
              {' '}
              (<strong>{failed}</strong> URL{failed === 1 ? '' : 's'} failed)
            </>
          )}
          {status.finished_at && (
            <span style={{ marginLeft: 8, color: 'var(--text-3)' }}>
              · {formatTime(status.finished_at)}
            </span>
          )}
        </div>
      </div>
    );
  }

  // Phase 3 didn't merge anything — red warning card with the reason.
  return (
    <div
      className="card"
      style={{
        padding: 12,
        marginBottom: 16,
        borderColor: 'var(--red)',
        background: 'rgba(239, 68, 68, 0.06)',
        color: 'var(--text-1)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Icon name="warning" />
        <strong>Page Speed (PSI) capture skipped on the last run</strong>
      </div>
      <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 4 }}>
        <em>{status.error || 'Reason not recorded'}</em>
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 6 }}>
        The <code>pagespeed_score</code>, <code>lcp_ms</code>,{' '}
        <code>cls</code>, and <code>inp_ms</code> columns in the results
        table will stay empty until this is resolved. Common causes:{' '}
        PSI service-account file missing, PSI_ENABLED=false, or the
        crawler ran on an old Celery worker image.
        {status.finished_at && (
          <span style={{ marginLeft: 8 }}>
            · {formatTime(status.finished_at)}
          </span>
        )}
      </div>
    </div>
  );
}
