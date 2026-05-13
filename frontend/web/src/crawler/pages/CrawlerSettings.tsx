import { useEffect, useState } from 'react';
import Icon from '../components/Icon';
import { crawlerApi, type CrawlerStatus } from '../api';

export default function CrawlerSettings() {
  const [status, setStatus] = useState<CrawlerStatus | null>(null);

  useEffect(() => {
    crawlerApi
      .status()
      .then(setStatus)
      .catch(() => {});
  }, []);

  return (
    <div className="cc-scope">
      <div className="page-head">
        <div>
          <h1>
            <span
              className="material-icons-outlined"
              style={{ fontSize: 26, verticalAlign: 'middle', marginRight: 8, color: 'var(--primary)' }}
            >
              tune
            </span>
            Crawler Settings
          </h1>
          <p>
            <span className="material-icons-outlined" style={{ fontSize: 14, verticalAlign: 'middle', marginRight: 4 }}>
              info
            </span>
            Runtime configuration. Edit <code>crawler-engine/.env</code> to change these values.
          </p>
        </div>
      </div>

      <div className="settings-group">
        <h3>
          <span
            className="material-icons-outlined"
            style={{ fontSize: 16, verticalAlign: 'middle', marginRight: 6, color: 'var(--primary)' }}
          >
            dns
          </span>
          Crawler
        </h3>
        <dl className="kv">
          <dt>Seed URL</dt>
          <dd>{status?.seed || '—'}</dd>
          <dt>Allowed domains</dt>
          <dd>{(status?.allowed_domains || []).join(', ') || '—'}</dd>
          <dt>Is running</dt>
          <dd>{String(status?.is_running ?? false)}</dd>
          <dt>Visited count</dt>
          <dd>{(status?.visited_count ?? 0).toLocaleString()}</dd>
          <dt>Queue count</dt>
          <dd>{(status?.queue_count ?? 0).toLocaleString()}</dd>
        </dl>
      </div>

      <div className="settings-group">
        <h3>
          <span
            className="material-icons-outlined"
            style={{ fontSize: 16, verticalAlign: 'middle', marginRight: 6, color: 'var(--primary)' }}
          >
            settings
          </span>
          Configurable via .env
        </h3>
        <dl className="kv">
          <dt>MAX_WORKERS</dt>
          <dd>Thread pool size · defaults to 12</dd>
          <dt>PER_WORKER_DELAY</dt>
          <dd>Polite delay per worker · defaults to 0.2s</dd>
          <dt>REQUEST_TIMEOUT</dt>
          <dd>HTTP timeout per request · defaults to 30s</dd>
          <dt>CHECKPOINT_EVERY</dt>
          <dd>Flush CSVs / state every N pages · defaults to 500</dd>
          <dt>RESPECT_ROBOTS</dt>
          <dd>Honor robots.txt · defaults to true</dd>
          <dt>MAX_DEPTH / MAX_PAGES</dt>
          <dd>Depth / page ceilings · 0 = unlimited</dd>
        </dl>
      </div>

      <div className="settings-group">
        <h3>
          <span
            className="material-icons-outlined"
            style={{ fontSize: 16, verticalAlign: 'middle', marginRight: 6, color: 'var(--primary)' }}
          >
            menu_book
          </span>
          Documentation
        </h3>
        <div className="card" style={{ padding: 16, display: 'flex', gap: 14 }}>
          <Icon name="article" style={{ color: 'var(--primary)' }} />
          <div style={{ fontSize: 13 }}>
            Interactive OpenAPI docs are available at{' '}
            <a href="http://127.0.0.1:8077/docs" target="_blank" rel="noreferrer">
              http://127.0.0.1:8077/docs
            </a>{' '}
            (FastAPI Swagger UI). See also <code>crawler-engine/CRAWLER_LOGIC.md</code>.
          </div>
        </div>
      </div>
    </div>
  );
}
