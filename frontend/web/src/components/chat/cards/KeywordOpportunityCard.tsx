interface Row {
  keyword?: string;
  position?: number;
  search_volume?: number;
  url?: string;
}

export default function KeywordOpportunityCard({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  const rows = (payload.rows as Row[]) || [];
  const title = (payload.title as string) || 'Keyword opportunities';
  return (
    <div className="seo-card chat-card">
      <div className="chat-card-title">{title}</div>
      <table className="chat-card-table">
        <thead>
          <tr>
            <th>Keyword</th>
            <th className="num">Pos</th>
            <th className="num">Volume</th>
            <th>URL</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.keyword}</td>
              <td className="num">{r.position ?? '—'}</td>
              <td className="num">
                {r.search_volume != null
                  ? r.search_volume.toLocaleString()
                  : '—'}
              </td>
              <td>
                {r.url ? (
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {r.url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 60)}
                  </a>
                ) : (
                  '—'
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
