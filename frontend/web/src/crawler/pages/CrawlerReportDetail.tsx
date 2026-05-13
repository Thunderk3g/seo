import { useEffect, useState } from 'react';
import { Link, useParams } from 'wouter';
import DataTable from '../components/DataTable';
import EmptyState from '../components/EmptyState';
import Icon from '../components/Icon';
import { crawlerApi, type TableData } from '../api';

export default function CrawlerReportDetail() {
  const params = useParams<{ key: string }>();
  const key = params.key;
  const [data, setData] = useState<TableData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    crawlerApi
      .table(key)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [key]);

  return (
    <div className="cc-scope">
      <div className="page-head">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <Link href="/crawler/reports" className="btn btn-ghost" style={{ padding: '4px 10px' }}>
              <Icon name="arrow_back" size="16px" /> Back to reports
            </Link>
          </div>
          <h1>
            <span
              className="material-icons-outlined"
              style={{ fontSize: 26, verticalAlign: 'middle', marginRight: 8, color: 'var(--primary)' }}
            >
              description
            </span>
            {data?.label || key}
          </h1>
          <p>
            <span className="material-icons-outlined" style={{ fontSize: 14, verticalAlign: 'middle', marginRight: 4 }}>
              info
            </span>
            {data?.description}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <a className="btn btn-ghost" href={crawlerApi.downloadUrl(key)}>
            <Icon name="download" /> CSV
          </a>
          <a className="btn btn-accent" href={crawlerApi.xlsxUrl()}>
            <Icon name="insert_chart" /> Full XLSX
          </a>
        </div>
      </div>

      {error && <EmptyState icon="error" title="Could not load table" hint={error} />}
      {!error && data && data.count === 0 && (
        <EmptyState icon="inbox" title="No rows in this report" hint="Run a crawl to populate it." />
      )}
      {!error && data && data.count > 0 && <DataTable headers={data.headers} rows={data.rows} />}
    </div>
  );
}
