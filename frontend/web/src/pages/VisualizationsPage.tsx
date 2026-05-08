// VisualizationsPage — three-tab visual explorer for the active site's
// latest crawl session. Tabs:
//   - Site tree   (default)  — collapsible hierarchical list
//   - Treemap                — slice-and-dice over the top-level dirs
//   - Network graph          — depth-ringed link graph
//
// Mirrors `.design-ref/project/pages.jsx:385–408`. The tab switcher lives
// in PageHeader's `actions` slot per the reference. The Site-tree tab keeps
// its own `max_depth` selector inline in the card head (it's only relevant
// for that view).

import { useState } from 'react';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useSessions } from '../api/hooks/useSessions';
import { useTree } from '../api/hooks/useTree';
import type { SiteTree, TreeNode } from '../api/types';
import PageHeader from '../components/PageHeader';
import Icon from '../components/icons/Icon';
import Treemap from '../components/charts/Treemap';
import NetworkGraph from '../components/charts/NetworkGraph';

type TabId = 'tree' | 'treemap' | 'graph';

const TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: 'tree', label: 'Site tree' },
  { id: 'treemap', label: 'Treemap' },
  { id: 'graph', label: 'Network graph' },
] as const;

const MAX_DEPTH_OPTIONS = [2, 4, 6, 8] as const;

// ── Site-tree row (unchanged from prior implementation) ─────────────────────

interface TreeRowProps {
  node: TreeNode;
  depth: number;
  rootCount: number;
}

function TreeRow({ node, depth, rootCount }: TreeRowProps) {
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = node.children.length > 0;
  const pct =
    rootCount > 0 ? Math.min(100, (node.url_count / rootCount) * 100) : 0;
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
        <span aria-hidden="true" style={{ display: 'inline-flex', width: 11, justifyContent: 'center' }}>
          {hasChildren ? (
            <Icon
              name="chevRight"
              size={11}
              style={{
                transform: `rotate(${open ? 90 : 0}deg)`,
                transition: 'transform 0.15s',
                opacity: 0.5,
              }}
            />
          ) : null}
        </span>
        <span aria-hidden="true" style={{ display: 'inline-flex', width: 13, justifyContent: 'center' }}>
          <Icon
            name={hasChildren ? 'folder' : 'file'}
            size={13}
            style={{ color: hasChildren ? 'var(--accent)' : 'rgba(255,255,255,0.4)' }}
          />
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

// ── Site-tree tab body ──────────────────────────────────────────────────────

interface SiteTreeCardProps {
  root: SiteTree;
  maxDepth: number;
  onMaxDepthChange: (d: number) => void;
  isFetching: boolean;
}

function SiteTreeCard({
  root,
  maxDepth,
  onMaxDepthChange,
  isFetching,
}: SiteTreeCardProps) {
  return (
    <div className="card">
      <div className="card-head card-head-flex">
        <h3>Site tree</h3>
        <div className="tabs small" role="group" aria-label="Max tree depth">
          {MAX_DEPTH_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              className={'tab ' + (d === maxDepth ? 'active' : '')}
              onClick={() => onMaxDepthChange(d)}
              disabled={isFetching}
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
  );
}

// ── Page ────────────────────────────────────────────────────────────────────

export default function VisualizationsPage() {
  const { activeSiteId } = useActiveSite();
  const sessionsQuery = useSessions(activeSiteId);
  const session = sessionsQuery.data?.[0] ?? null;
  const sessionId = session?.id ?? null;

  const [activeTab, setActiveTab] = useState<TabId>('tree');
  const [maxDepth, setMaxDepth] = useState<number>(4);
  const treeQuery = useTree(sessionId, maxDepth);

  const subtitle = (() => {
    if (!activeSiteId) return 'No site selected';
    if (sessionsQuery.isPending) return 'Loading sessions…';
    if (!session) return 'No crawl sessions yet — start one from the topbar';
    if (activeTab === 'tree') {
      if (treeQuery.isPending) return 'Loading site tree…';
      if (treeQuery.isError) return 'Failed to load site tree';
      const total = treeQuery.data?.url_count ?? 0;
      const reached = treeQuery.data?.max_depth_reached ?? 0;
      return `${total.toLocaleString()} ${total === 1 ? 'URL' : 'URLs'} in tree · max depth reached ${reached}`;
    }
    return `Visual structure of ${session.website_domain} — explore by tree, treemap, or graph.`;
  })();

  const root = treeQuery.data ?? null;

  // Tab switcher rendered into the PageHeader actions slot. Disabled until
  // we have a session to render against.
  const tabSwitcher = (
    <div className="tabs" role="tablist" aria-label="Visualization view">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={activeTab === t.id}
          className={'tab ' + (activeTab === t.id ? 'active' : '')}
          onClick={() => setActiveTab(t.id)}
          disabled={!sessionId}
        >
          {t.label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="page-grid">
      <PageHeader
        title="Visualizations"
        subtitle={subtitle}
        actions={tabSwitcher}
      />

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

      {/* ── Site tree tab ───────────────────────────────────────────── */}
      {session && activeTab === 'tree' && (
        <>
          {treeQuery.isError && (
            <div className="card" style={{ padding: 'var(--pad)' }}>
              <p style={{ color: 'var(--error, #f87171)' }}>
                Failed to load site tree
                {treeQuery.error instanceof Error
                  ? `: ${treeQuery.error.message}`
                  : '.'}
              </p>
            </div>
          )}
          {treeQuery.isPending && (
            <div className="card" style={{ padding: 'var(--pad)' }}>
              <p className="text-muted">Loading site tree…</p>
            </div>
          )}
          {root && (
            <SiteTreeCard
              root={root}
              maxDepth={maxDepth}
              onMaxDepthChange={setMaxDepth}
              isFetching={treeQuery.isFetching}
            />
          )}
        </>
      )}

      {/* ── Treemap tab ─────────────────────────────────────────────── */}
      {session && activeTab === 'treemap' && (
        <>
          {treeQuery.isError && (
            <div className="card" style={{ padding: 'var(--pad)' }}>
              <p style={{ color: 'var(--error, #f87171)' }}>
                Failed to load tree data
                {treeQuery.error instanceof Error
                  ? `: ${treeQuery.error.message}`
                  : '.'}
              </p>
            </div>
          )}
          {treeQuery.isPending && (
            <div className="card" style={{ padding: 'var(--pad)' }}>
              <p className="text-muted">Loading treemap…</p>
            </div>
          )}
          {root && <Treemap tree={root} />}
        </>
      )}

      {/* ── Network graph tab ──────────────────────────────────────── */}
      {session && sessionId && activeTab === 'graph' && (
        <NetworkGraph sessionId={sessionId} />
      )}
    </div>
  );
}
