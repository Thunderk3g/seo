interface Row {
  query?: string;
  clicks?: number;
  impressions?: number;
  ctr?: number;
  position?: number;
}

export default function GscTopQueriesCard({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  const rows = (payload.rows as Row[]) || [];
  const title = (payload.title as string) || 'Top search queries';
  return (
    <div className="seo-card chat-card">
      <div className="chat-card-title">{title}</div>
      <table className="chat-card-table">
        <thead>
          <tr>
            <th>Query</th>
            <th className="num">Clicks</th>
            <th className="num">Impr.</th>
            <th className="num">CTR</th>
            <th className="num">Pos</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.query}</td>
              <td className="num">{r.clicks ?? '—'}</td>
              <td className="num">{r.impressions ?? '—'}</td>
              <td className="num">
                {r.ctr != null ? `${(r.ctr * 100).toFixed(1)}%` : '—'}
              </td>
              <td className="num">
                {r.position != null ? r.position.toFixed(1) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
