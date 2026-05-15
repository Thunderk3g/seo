// Panel 4: the top-N competitor leaderboard. Each row shows the score
// breakdown so users see exactly *why* a rival was picked (LLM cites +
// SERP appearances + featured snippets + AI Overview citations).

import type { GapCompetitorRow } from '../../../api/seoTypes';

export default function TopCompetitorsPanel({
  rows,
}: {
  rows: GapCompetitorRow[];
}) {
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Top competitors discovered</h2>
        <span className="seo-card-sub">
          Scored across LLM citations + SERP rankings + featured snippets
          + AI Overview presence
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">
          No competitors aggregated yet. (Stage runs after both LLM and
          SERP searches finish.)
        </div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th style={{ width: 32 }}>#</th>
              <th>Domain</th>
              <th className="num">Score</th>
              <th className="num">LLM cites</th>
              <th className="num">SERP hits</th>
              <th className="num">Top-3</th>
              <th className="num">Featured</th>
              <th className="num">AI Overview</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td className="num">{c.rank}</td>
                <td className="seo-cell-query">
                  <a
                    href={`https://${c.domain}/`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {c.domain}
                  </a>
                </td>
                <td className="num">
                  <b>{c.score.toFixed(1)}</b>
                </td>
                <td className="num">{c.llm_citation_count}</td>
                <td className="num">{c.serp_appearance_count}</td>
                <td className="num">{c.serp_top3_count}</td>
                <td className="num">{c.featured_snippet_count}</td>
                <td className="num">{c.ai_overview_citation_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
