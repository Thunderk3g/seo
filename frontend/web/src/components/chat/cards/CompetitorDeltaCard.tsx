interface CompetitorRow {
  domain?: string;
  competition_level?: number;
  common_keywords?: number;
  organic_keywords?: number;
  organic_traffic?: number;
}

export default function CompetitorDeltaCard({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  const rows = (payload.competitors as CompetitorRow[]) || [];
  const title = (payload.title as string) || 'Competitors';
  return (
    <div className="seo-card chat-card">
      <div className="chat-card-title">{title}</div>
      <table className="chat-card-table">
        <thead>
          <tr>
            <th>Domain</th>
            <th className="num">Overlap</th>
            <th className="num">Shared kws</th>
            <th className="num">Their kws</th>
            <th className="num">Est. traffic</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.domain}</td>
              <td className="num">
                {r.competition_level != null
                  ? r.competition_level.toFixed(2)
                  : '—'}
              </td>
              <td className="num">
                {r.common_keywords != null
                  ? r.common_keywords.toLocaleString()
                  : '—'}
              </td>
              <td className="num">
                {r.organic_keywords != null
                  ? r.organic_keywords.toLocaleString()
                  : '—'}
              </td>
              <td className="num">
                {r.organic_traffic != null
                  ? r.organic_traffic.toLocaleString()
                  : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
