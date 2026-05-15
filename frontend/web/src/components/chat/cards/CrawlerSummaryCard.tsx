export default function CrawlerSummaryCard({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  const totals = (payload.totals as Record<string, unknown>) || {};
  const title = (payload.title as string) || 'Crawler summary';
  const entries = Object.entries(totals);
  return (
    <div className="seo-card chat-card">
      <div className="chat-card-title">{title}</div>
      <div className="chat-card-grid">
        {entries.map(([k, v]) => (
          <div key={k} className="chat-card-stat">
            <div className="chat-card-stat-value">
              {typeof v === 'number' ? v.toLocaleString() : String(v ?? '—')}
            </div>
            <div className="chat-card-stat-label">{k.replace(/_/g, ' ')}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
