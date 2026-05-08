// Treemap — slice-and-dice treemap of the top-level directories in a site
// tree. Mirrors `.design-ref/project/pages.jsx:542–581`.
//
// Layout: a 2-row "naive" slice-and-dice. We sort the root's children by
// url_count desc, then split them into two rows by cumulative half-total.
// Each row is sized vertically by its share of the total, and each cell
// inside a row is sized horizontally by its share of the row total.
//
// We use absolute positioning (left/top/width/height in %) so the grid
// fills the parent .treemap card cleanly — the .tm-cell class in
// styles/lattice.css already declares `position: absolute`.

import type { SiteTree, TreeNode } from '../../api/types';

interface TreemapProps {
  tree: SiteTree;
  /** How many of the largest root-children to include. Default 8. */
  topN?: number;
}

// Rotating palette so adjacent cells visibly differ. Mirrors the design ref.
const COLORS = [
  'var(--accent)',
  '#60a5fa',
  '#a78bfa',
  '#fbbf24',
  '#f87171',
  '#fb923c',
  '#34d399',
  '#f472b6',
];

interface Item {
  name: string;
  value: number;
  path: string;
}

function sumValue(arr: Item[]): number {
  return arr.reduce((s, x) => s + x.value, 0);
}

export default function Treemap({ tree, topN = 8 }: TreemapProps) {
  // Take the root's children — these are the top-level directories.
  // The TreeService already returns children sorted by url_count desc, but
  // we re-sort defensively in case that changes.
  const items: Item[] = (tree.children ?? [])
    .slice()
    .sort((a: TreeNode, b: TreeNode) => b.url_count - a.url_count)
    .slice(0, topN)
    .map((c) => ({ name: c.name, value: c.url_count, path: c.path }));

  if (items.length === 0) {
    return (
      <div className="card vis-card">
        <div className="card-head">
          <h3>Treemap by directory</h3>
        </div>
        <div style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            No top-level directories in this session yet — the treemap is empty.
          </p>
        </div>
      </div>
    );
  }

  const total = sumValue(items);

  // Naive 2-row layout: walk items in order, fill row 1 until cumulative
  // share crosses half of total, then dump the rest into row 2.
  const row1: Item[] = [];
  const row2: Item[] = [];
  const half = total / 2;
  let cum = 0;
  for (const it of items) {
    if (cum < half) {
      row1.push(it);
      cum += it.value;
    } else {
      row2.push(it);
    }
  }

  // Row heights as a % of the card. Guard against degenerate single-row.
  const row1Sum = sumValue(row1);
  const row1Height =
    row2.length === 0 ? 100 : (row1Sum / total) * 100;
  const row2Height = 100 - row1Height;

  function renderRow(row: Item[], topPct: number, heightPct: number, palOffset: number) {
    const rowTotal = sumValue(row) || 1;
    let leftPct = 0;
    return row.map((it, i) => {
      const widthPct = (it.value / rowTotal) * 100;
      const cell = (
        <div
          key={it.path || it.name}
          className="tm-cell"
          style={{
            left: `${leftPct}%`,
            top: `${topPct}%`,
            width: `${widthPct}%`,
            height: `${heightPct}%`,
            background: COLORS[(i + palOffset) % COLORS.length],
          }}
          title={`${it.path} · ${it.value.toLocaleString()} URLs`}
        >
          <div className="tm-name">/{it.name}</div>
          <div className="tm-count">{it.value.toLocaleString()}</div>
        </div>
      );
      leftPct += widthPct;
      return cell;
    });
  }

  return (
    <div className="card vis-card">
      <div className="card-head card-head-flex">
        <h3>Treemap by directory</h3>
        <div className="text-muted" style={{ fontSize: 11 }}>
          Top {items.length} of {tree.children.length} directories ·{' '}
          {total.toLocaleString()} URLs
        </div>
      </div>
      <div className="treemap" role="img" aria-label="Treemap by top-level directory">
        {renderRow(row1, 0, row1Height, 0)}
        {row2.length > 0 && renderRow(row2, row1Height, row2Height, 4)}
      </div>
    </div>
  );
}
