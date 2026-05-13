import { useEffect, useState } from 'react';
import TreeNode from '../components/TreeNode';
import TreeGraph from '../components/TreeGraph';
import { crawlerApi, type TreeNodeData, type TreeResponse } from '../api';

function filterTree(node: TreeNodeData | undefined, q: string): TreeNodeData | null {
  if (!node) return null;
  const query = q.trim().toLowerCase();
  if (!query) return node;

  const matches = (n: TreeNodeData) =>
    n.url.toLowerCase().includes(query) || (n.title || '').toLowerCase().includes(query);

  const walk = (n: TreeNodeData): TreeNodeData | null => {
    const keptChildren = (n.children || []).map(walk).filter((x): x is TreeNodeData => Boolean(x));
    if (matches(n) || keptChildren.length > 0) {
      return { ...n, children: keptChildren };
    }
    return null;
  };

  return walk(node);
}

export default function SiteTreePage() {
  const [data, setData] = useState<TreeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [depth, setDepth] = useState(4);
  const [filter, setFilter] = useState('');
  const [view, setView] = useState<'graph' | 'list'>('graph');

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    crawlerApi
      .tree(depth, 5000)
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((e) => {
        if (alive) setError(e instanceof Error ? e.message : 'Failed to load tree');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [depth]);

  const filteredRoot = filterTree(data?.root, filter);

  return (
    <div className="cc-scope">
      <div className="page-head">
        <div>
          <h1>
            <span
              className="material-icons-outlined"
              style={{ fontSize: 26, verticalAlign: 'middle', marginRight: 8, color: 'var(--primary)' }}
            >
              account_tree
            </span>
            Site Tree
          </h1>
          <p>
            <span className="material-icons-outlined" style={{ fontSize: 14, verticalAlign: 'middle', marginRight: 4 }}>
              hub
            </span>
            Hierarchical crawl map — master page at the top, discovered links branching below.
          </p>
        </div>
        <div className="tree-controls">
          <div className="view-toggle" role="tablist" aria-label="View mode">
            <button
              type="button"
              className={`vt-btn ${view === 'graph' ? 'active' : ''}`}
              onClick={() => setView('graph')}
              role="tab"
              aria-selected={view === 'graph'}
            >
              <span className="material-icons-outlined">schema</span>
              Graph
            </button>
            <button
              type="button"
              className={`vt-btn ${view === 'list' ? 'active' : ''}`}
              onClick={() => setView('list')}
              role="tab"
              aria-selected={view === 'list'}
            >
              <span className="material-icons-outlined">list</span>
              List
            </button>
          </div>
          <div className="input-wrap">
            <span className="material-icons-outlined">search</span>
            <input
              className="tree-input"
              placeholder="Filter by URL or title…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          <label className="depth-picker">
            <span className="material-icons-outlined">layers</span>
            Depth
            <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
              {[2, 3, 4, 5, 6, 7, 8].map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <span className="material-icons-outlined">{view === 'graph' ? 'schema' : 'account_tree'}</span>
          {view === 'graph' ? 'Decomposition Tree' : 'Crawl Tree'}
          {data && (
            <>
              <span className="pill">{data.total_nodes_returned} nodes</span>
              <span className="pill">{data.total_edges} edges</span>
              {data.truncated && <span className="pill pill-warn">truncated</span>}
            </>
          )}
        </div>
        <div className={`card-body ${view === 'graph' ? 'tg-card-body' : 'tree-wrap'}`}>
          {loading && (
            <div className="empty">
              <span className="material-icons-outlined">hourglass_top</span>
              Loading tree…
            </div>
          )}
          {!loading && error && (
            <div className="empty">
              <span className="material-icons-outlined">error</span>
              {error}
            </div>
          )}
          {!loading && !error && filteredRoot && view === 'list' && <TreeNode node={filteredRoot} root />}
          {!loading && !error && filteredRoot && view === 'graph' && (
            <TreeGraph root={filteredRoot} autoExpandAll={!!filter.trim()} />
          )}
          {!loading && !error && data && !filteredRoot && (
            <div className="empty">
              <span className="material-icons-outlined">search_off</span>
              No nodes match &ldquo;{filter}&rdquo;
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
