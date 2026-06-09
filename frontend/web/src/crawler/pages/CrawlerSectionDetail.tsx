import { Link, useParams } from 'wouter';
import Icon from '../components/Icon';
import { SECTION_REGISTRY } from '../components/ReportSectionsPanel';

/**
 * Full detail view for one report section. Reached by clicking a square block
 * on the Reports landing (/crawler/reports/section/:key). Renders the section's
 * self-contained Detail component from the shared registry — heavy sections
 * (broken-links, external-links) run their master scan only here, on open.
 */
export default function CrawlerSectionDetail() {
  const params = useParams<{ key: string }>();
  const def = params.key ? SECTION_REGISTRY[params.key] : undefined;

  return (
    <div className="cc-scope">
      <div className="page-head">
        <div>
          <h1>
            <span className="material-icons-outlined" style={{ fontSize: 24, verticalAlign: 'middle', marginRight: 8, color: 'var(--primary)' }}>
              {def?.icon ?? 'help_outline'}
            </span>
            {def?.title ?? 'Unknown section'}
          </h1>
          <p>
            <Link href="/crawler/reports" className="btn btn-ghost" style={{ padding: '2px 8px' }}>
              <Icon name="arrow_back" /> Back to Reports
            </Link>
          </p>
        </div>
      </div>

      {def ? <def.Detail /> : (
        <div className="card" style={{ padding: 16 }}>
          <Icon name="error" /> No such report section: <code>{params.key}</code>.
          <div style={{ marginTop: 8 }}><Link href="/crawler/reports">← Back to Reports</Link></div>
        </div>
      )}
    </div>
  );
}
