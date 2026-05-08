// SiteStructureMini — top-level folder breakdown for the dashboard's row 4.
//
// Mirrors `.design-ref/project/dashboard.jsx` SiteStructureMini (lines
// 291-312). Pulls the first two levels of the site tree via `useTree` and
// renders the top 6 children sorted by `url_count` desc, each with a
// horizontal Meter showing relative size against the largest child.

import { useTree } from '../../api/hooks/useTree';
import Icon from '../icons/Icon';
import Meter from '../charts/Meter';

interface Props {
  sessionId: string | null;
}

export default function SiteStructureMini({ sessionId }: Props) {
  // 2 is enough for the mini view: root + immediate children with counts.
  const tree = useTree(sessionId, 2);
  const children = tree.data?.children ?? [];

  const top = children
    .slice()
    .sort((a, b) => b.url_count - a.url_count)
    .slice(0, 6);
  const max = top[0]?.url_count ?? 0;

  return (
    <div className="card">
      <div className="card-head">
        <h3>Site structure</h3>
        <a className="link-btn" href="#visualizations">
          View tree <Icon name="chevRight" size={11} />
        </a>
      </div>

      {!sessionId && (
        <p className="text-muted" style={{ fontSize: 12 }}>
          No crawl session yet.
        </p>
      )}
      {sessionId && tree.isPending && (
        <p className="text-muted" style={{ fontSize: 12 }}>Loading…</p>
      )}
      {sessionId && tree.isError && (
        <p style={{ color: '#f87171', fontSize: 12 }}>
          Failed to load tree.
        </p>
      )}
      {sessionId && tree.data && top.length === 0 && (
        <p className="text-muted" style={{ fontSize: 12 }}>
          No subfolders discovered yet.
        </p>
      )}

      {top.length > 0 && (
        <div className="tree-mini">
          {top.map((n) => (
            <div key={n.path} className="tree-mini-row">
              <Icon name="folder" size={13} />
              <span className="tree-mini-name">/{n.name}</span>
              <span className="tree-mini-count">
                {n.url_count.toLocaleString()}
              </span>
              <div style={{ width: 80 }}>
                <Meter
                  value={n.url_count}
                  max={max || 1}
                  color="var(--accent)"
                  height={4}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
