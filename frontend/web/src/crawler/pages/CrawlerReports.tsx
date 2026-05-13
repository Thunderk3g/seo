import { useEffect, useState } from 'react';
import ReportCard from '../components/ReportCard';
import Icon from '../components/Icon';
import { crawlerApi, type TableMeta } from '../api';

export default function CrawlerReports() {
  const [tables, setTables] = useState<TableMeta[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    crawlerApi
      .tables()
      .then((d) => alive && setTables(d.tables))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
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
              assessment
            </span>
            Reports
          </h1>
          <p>
            <span className="material-icons-outlined" style={{ fontSize: 14, verticalAlign: 'middle', marginRight: 4 }}>
              summarize
            </span>
            Every crawl artefact, beautified. Pick a report to drill in — or grab the full bundle.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <a className="btn btn-ghost" href={crawlerApi.downloadUrl('results')}>
            <Icon name="download" /> Raw CSV
          </a>
          <a className="btn btn-accent" href={crawlerApi.xlsxUrl()}>
            <Icon name="insert_chart" /> Download Excel Bundle
          </a>
        </div>
      </div>

      {error && (
        <div className="card" style={{ padding: 16, borderColor: 'var(--red)', color: 'var(--red)' }}>
          <Icon name="error" /> {error}
        </div>
      )}

      <div
        className="card"
        style={{ marginBottom: 18, padding: 14, display: 'flex', gap: 14, alignItems: 'flex-start' }}
      >
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 10,
            background: 'var(--accent-light)',
            display: 'grid',
            placeItems: 'center',
            flexShrink: 0,
          }}
        >
          <Icon name="insert_chart" style={{ color: '#8A6200' }} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 14 }}>Beautified Excel workbook</div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 2 }}>
            One XLSX file · every report as a separate sheet · summary page with KPIs and a pie chart · brand-coloured
            headers, frozen panes, auto-filters, and conditional formatting on status columns.
          </div>
        </div>
        <a className="btn btn-primary" href={crawlerApi.xlsxUrl()}>
          <Icon name="download" /> Generate &amp; Download
        </a>
      </div>

      <div className="report-grid">
        {tables.map((t) => (
          <ReportCard key={t.key} table={t} />
        ))}
      </div>
    </div>
  );
}
