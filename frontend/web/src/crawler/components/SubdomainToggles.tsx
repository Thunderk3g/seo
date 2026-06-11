import { useCallback, useEffect, useState } from 'react';
import { crawlerApi, type SubdomainOption } from '../api';

/**
 * On-demand subdomain crawl scope for the generic page-audit crawler.
 * Base crawl is www-only; flip a switch to ALSO crawl branch.* /
 * investmentcorner.* on the next Start. Disabled while a crawl is
 * running (scope is read at Start). NOT the content crawler.
 */
export default function SubdomainToggles({ running }: { running: boolean }) {
  const [options, setOptions] = useState<SubdomainOption[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    crawlerApi
      .subdomains()
      .then((r) => setOptions(r.available))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load, running]);

  const toggle = async (key: string, enabled: boolean) => {
    setBusy(key);
    setError(null);
    try {
      const r = await crawlerApi.setSubdomain(key, enabled);
      if (r.ok === false) {
        setError(r.message || 'Could not change scope.');
      } else {
        setOptions(r.available);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  if (!options.length) return null;

  return (
    <div
      className="card"
      style={{ padding: '12px 16px', margin: '0 0 12px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 14 }}
    >
      <span style={{ fontWeight: 700, color: '#002c6e', fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className="material-icons-outlined" style={{ fontSize: 18, color: 'var(--primary)' }}>
          account_tree
        </span>
        Crawl scope
      </span>
      <span style={{ fontSize: 12, color: '#475569' }}>
        Base crawl is <code>www.bajajlifeinsurance.com</code> only. Enable a subdomain to include it on the next Start:
      </span>
      {options.map((o) => (
        <label
          key={o.key}
          title={o.host}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 12.5,
            color: '#334155',
            opacity: running ? 0.55 : 1,
            cursor: running ? 'not-allowed' : 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={o.enabled}
            disabled={running || busy === o.key}
            onChange={(e) => toggle(o.key, e.target.checked)}
          />
          <span>
            {o.label}{' '}
            <code style={{ fontSize: 11, color: '#94a3b8' }}>{o.host.split('.')[0]}.*</code>
          </span>
        </label>
      ))}
      {running && (
        <span style={{ fontSize: 11.5, color: '#b45309' }}>
          Stop the crawl to change scope.
        </span>
      )}
      {error && <span style={{ fontSize: 11.5, color: '#b91c1b' }}>{error}</span>}
    </div>
  );
}
