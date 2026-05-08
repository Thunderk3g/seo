// VisualizationsPage — site-tree visualisation for the active site's latest
// crawl session.
//
// Per spec §5.4.5, the full Visualizations page hosts three views: site
// tree, treemap, and force-graph. v1 ships ONLY the site tree as a nested
// list. The other two are deferred:
//   TODO(viz): Treemap by directory. Needs a slice-and-dice layout over
//              root.children. Same data; pure presentational.
//   TODO(viz): Force-directed link graph. Backend exposes the data via
//              GET /sessions/<uuid>/links/, but rendering it tastefully
//              requires a graph library — out of scope for v1.
//
// The tree is collapsible: depth-0 (root) and depth-1 are open by default;
// deeper levels start collapsed so a wide site is tractable on first paint.
// `max_depth` is server-side — changing it issues a fresh query.

import { useState } from 'react';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useTree } from '../api/hooks/useTree';
import type { TreeNode } from '../api/types';

const MAX_DEPTH_OPTIONS = [2, 4, 6, 8] as const;

interface TreeRowProps {
  node: TreeNode;
  depth: number;
  rootCount: number;
}

function TreeRow({ node, depth, rootCount }: TreeRowProps) {
  // Root + first level start expanded; deeper levels collapse by default
  // so a sprawling tree doesn't dump everything on first paint.
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = node.children.length > 0;
  // Bar width is relative to the root's url_count so every row's bar is
  // comparable. Cap at 100% defensively.
  const pct = rootCount > 0 ? Math.min(100, (node.url_count / rootCount) * 100) : 0;
  // Display name: the root sends "/" (from TreeService); children send their
  // segment. Prefix children with "/" so the breadcrumb visual stays consistent.
  const label = depth === 0 ? node.name : '/' + node.name;

  return (
    <li role="treeitem" aria-expanded={hasChildren ? open : undefined}>
      <button
        type="button"
        className="tree-row"
        style={{ paddingLeft: 12 + depth * 18 }}
        onClick={() => hasChildren && setOpen((v) => !v)}
        title={node.path}
      >
        <span aria-hidden="true" style={{ display: 'inline-block', width: 11 }}>
          {hasChildren ? (open ? '▾' : '▸') : ''}
        </span>
        <span aria-hidden="true" style={{ display: 'inline-block', width: 13 }}>
          {hasChildren ? '▣' : '·'}
        </span>
        <span className="tree-row-name">{label}</span>
        <span className="tree-row-count num">
          {node.url_count.toLocaleString()}
          {node.direct_url_count !== node.url_count && (
            <span className="text-muted" style={{ marginLeft: 6 }}>
              ({node.direct_url_count.toLocaleString()} direct)
            </span>
          )}
        </span>
        <div className="tree-row-bar" aria-hidden="true">
          <div style={{ width: `${pct}%` }} />
        </div>
      </button>
      {open && hasChildren && (
        <ul role="group" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {node.children.map((c) => (
            <TreeRow
              key={c.path}
              node={c}
              depth={depth + 1}
              rootCount={rootCount}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function VisualizationsPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  // Use the most recent session — sessions are returned ordered by -started_at.
  const session = sessionsQuery.data?.[0] ?? null;
  const sessionId = session?.id ?? null;

  const [maxDepth, setMaxDepth] = useState<number>(4);
  const treeQuery = useTree(sessionId, maxDepth);

  const subtitle = (() => {
    if (!activeSiteId) return 'No site selected';
    if (sessionsQuery.isPending) return 'Loading sessions…';
    if (!session) return 'No crawl sessions yet — start one from the topbar';
    if (treeQuery.isPending) return 'Loading site tree…';
    if (treeQuery.isError) return 'Failed to load site tree';
    const total = treeQuery.data?.url_count ?? 0;
    const reached = treeQuery.data?.max_depth_reached ?? 0;
    return `${total.toLocaleString()} ${total === 1 ? 'URL' : 'URLs'} in tree · max depth reached ${reached}`;
  })();

  const root = treeQuery.data ?? null;

  return (
    <div className="page-grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Visualizations</h1>
          <div className="page-subtitle">{subtitle}</div>
        </div>
      </div>

      {!activeSiteId && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            Register a site from the topbar to explore its site tree.
          </p>
        </div>
      )}

      {activeSiteId && !session && !sessionsQuery.isPending && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">
            No crawl sessions exist for this site yet. Start one from the
            topbar to surface its structure.
          </p>
        </div>
      )}

      {session && treeQuery.isError && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p style={{ color: 'var(--error, #f87171)' }}>
            Failed to load site tree
            {treeQuery.error instanceof Error
              ? `: ${treeQuery.error.message}`
              : '.'}
          </p>
        </div>
      )}

      {session && treeQuery.isPending && (
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <p className="text-muted">Loading site tree…</p>
        </div>
      )}

      {session && root && (
        <div className="card">
          <div className="card-head card-head-flex">
            <h3>Site tree</h3>
            <div className="tabs small" role="group" aria-label="Max tree depth">
              {MAX_DEPTH_OPTIONS.map((d) => (
                <button
                  key={d}
                  type="button"
                  className={'tab ' + (d === maxDepth ? 'active' : '')}
                  onClick={() => setMaxDepth(d)}
                  // Disable while a fetch is in flight to avoid mid-flight
                  // double-clicks racing the cache.
                  disabled={treeQuery.isFetching}
                >
                  Depth {d}
                </button>
              ))}
            </div>
          </div>
          <div className="tree-full" role="tree" aria-label="Site tree">
            {root.url_count === 0 ? (
              <div style={{ padding: 14 }}>
                <p className="text-muted">
                  No pages in this session yet — the tree is empty.
                </p>
              </div>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                <TreeRow node={root} depth={0} rootCount={root.url_count} />
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
