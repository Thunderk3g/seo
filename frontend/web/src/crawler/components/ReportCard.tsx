import { Link } from 'wouter';
import Icon from './Icon';
import { crawlerApi, type TableMeta } from '../api';
import { fmtNum } from '../format';

export default function ReportCard({ table }: { table: TableMeta }) {
  return (
    <div className="report-card">
      <div className="rc-head">
        <div className="rc-icon">
          <Icon name={table.icon} />
        </div>
        <div>
          <div className="rc-title">{table.label}</div>
          <div className="rc-count">{fmtNum(table.count)}</div>
        </div>
      </div>
      <div className="rc-desc">{table.description}</div>
      <div className="rc-actions">
        <Link href={`/crawler/reports/${table.key}`} className="btn btn-ghost" style={{ flex: 1, justifyContent: 'center' }}>
          <Icon name="visibility" /> View
        </Link>
        <a href={crawlerApi.downloadUrl(table.key)} className="btn btn-primary" style={{ flex: 1, justifyContent: 'center' }}>
          <Icon name="download" /> CSV
        </a>
      </div>
    </div>
  );
}
