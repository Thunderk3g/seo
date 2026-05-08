// NetworkGraph — depth-ringed link graph for a crawl session.
//
// Layout strategy: deterministic polar coordinates by URL depth — NOT a
// force simulation. Cheaper, ordered, and reproducible across renders.
//
//   1. Pull the flat `Link[]` list from GET /sessions/<id>/links/
//   2. Collect distinct URLs from source/target columns; cap at MAX_NODES
//   3. Compute depth from each URL's path-segment count (depth 0 = home)
//   4. Place each depth bucket on a concentric ring: r = R0 + depth * STEP
//   5. Distribute nodes around each ring evenly by angle
//   6. Draw <line> edges between source/target node coords
//   7. Tag broken-link edges (4xx/5xx target) red — best-effort: the Link
//      payload doesn't carry status, so for v1 we mark edges to URLs we
//      never saw as a source as "leaf" only and don't paint them red.
//      A follow-up can join Page.http_status_code to colour broken edges.
//
// Mirrors `.design-ref/project/pages.jsx:410–503`.

import { useMemo } from 'react';
import { useLinks } from '../../api/hooks/useLinks';
import type { Link } from '../../api/types';

interface NetworkGraphProps {
  sessionId: string;
}

// Defensive caps so a 500-edge response doesn't stall the SVG.
const MAX_NODES = 100;
const MAX_EDGES = 200;

// SVG viewBox dimensions — match the design reference.
const W = 980;
const H = 560;
const CX = W / 2;
const CY = H / 2;
const R0 = 0;        // root sits at the centre
const RING_STEP = 110;
const MAX_DEPTH_RENDERED = 4;

// ── helpers ──────────────────────────────────────────────────────────────────

/** Path-segment depth. "/" → 0, "/foo" → 1, "/foo/bar" → 2, etc. */
function urlDepth(rawUrl: string): number {
  try {
    const u = new URL(rawUrl);
    const parts = u.pathname.split('/').filter(Boolean);
    return Math.min(parts.length, MAX_DEPTH_RENDERED);
  } catch {
    return MAX_DEPTH_RENDERED;
  }
}

function urlLabel(rawUrl: string): string {
  try {
    const u = new URL(rawUrl);
    const path = u.pathname.replace(/\/+$/, '') || '/';
    if (path === '/') return '/';
    const parts = path.split('/').filter(Boolean);
    return '/' + (parts[parts.length - 1] ?? '');
  } catch {
    return rawUrl;
  }
}

interface PositionedNode {
  url: string;
  depth: number;
  x: number;
  y: number;
  r: number;
  label: string;
}

interface PositionedEdge {
  a: PositionedNode;
  b: PositionedNode;
  navigation: boolean;
}

/** Compute polar positions per depth ring. */
function layoutNodes(urls: string[]): Map<string, PositionedNode> {
  // Group URLs by depth.
  const byDepth = new Map<number, string[]>();
  for (const u of urls) {
    const d = urlDepth(u);
    const bucket = byDepth.get(d) ?? [];
    bucket.push(u);
    byDepth.set(d, bucket);
  }

  // Sort each depth bucket so layout is stable across re-renders.
  const positions = new Map<string, PositionedNode>();
  for (const [depth, bucket] of byDepth) {
    bucket.sort();
    const n = bucket.length;
    const radius = depth === 0 ? R0 : R0 + depth * RING_STEP;
    const nodeRadius = depth === 0 ? 14 : Math.max(3, 9 - depth);
    bucket.forEach((url, i) => {
      // Even angular distribution; rotate -90° so first node sits at top.
      const angle = n === 1
        ? -Math.PI / 2
        : (i / n) * Math.PI * 2 - Math.PI / 2;
      const x = CX + Math.cos(angle) * radius;
      const y = CY + Math.sin(angle) * radius;
      positions.set(url, {
        url,
        depth,
        x,
        y,
        r: nodeRadius,
        label: urlLabel(url),
      });
    });
  }
  return positions;
}

// ── component ────────────────────────────────────────────────────────────────

export default function NetworkGraph({ sessionId }: NetworkGraphProps) {
  const linksQuery = useLinks(sessionId);

  const layout = useMemo(() => {
    const links: Link[] = linksQuery.data ?? [];
    if (links.length === 0) return null;

    // Collect distinct URLs in deterministic order: sources first (likely
    // crawled pages), then targets — capped at MAX_NODES total.
    const seen = new Set<string>();
    const nodeUrls: string[] = [];
    const pushUrl = (u: string) => {
      if (!u || seen.has(u)) return;
      if (nodeUrls.length >= MAX_NODES) return;
      seen.add(u);
      nodeUrls.push(u);
    };
    for (const l of links) pushUrl(l.source_url);
    for (const l of links) pushUrl(l.target_url);

    const positions = layoutNodes(nodeUrls);

    // Build positioned edges, filtering out edges that reference dropped
    // (capped) nodes.
    const edges: PositionedEdge[] = [];
    for (const l of links) {
      if (edges.length >= MAX_EDGES) break;
      const a = positions.get(l.source_url);
      const b = positions.get(l.target_url);
      if (!a || !b) continue;
      edges.push({ a, b, navigation: l.is_navigation });
    }

    return {
      nodes: Array.from(positions.values()),
      edges,
      total: links.length,
    };
  }, [linksQuery.data]);

  // ── render states ──────────────────────────────────────────────────────────

  if (linksQuery.isPending) {
    return (
      <div className="card vis-card">
        <div className="card-head"><h3>Network graph</h3></div>
        <p className="text-muted" style={{ padding: 'var(--pad)' }}>
          Loading link graph…
        </p>
      </div>
    );
  }

  if (linksQuery.isError) {
    return (
      <div className="card vis-card">
        <div className="card-head"><h3>Network graph</h3></div>
        <p style={{ color: 'var(--error)', padding: 'var(--pad)' }}>
          Failed to load link graph
          {linksQuery.error instanceof Error
            ? `: ${linksQuery.error.message}`
            : '.'}
        </p>
      </div>
    );
  }

  if (!layout || layout.nodes.length === 0) {
    return (
      <div className="card vis-card">
        <div className="card-head"><h3>Network graph</h3></div>
        <p className="text-muted" style={{ padding: 'var(--pad)' }}>
          No links discovered in this session yet — nothing to graph.
        </p>
      </div>
    );
  }

  const { nodes, edges, total } = layout;
  const cappedNodes = total > 0 && nodes.length >= MAX_NODES;
  const cappedEdges = edges.length >= MAX_EDGES;

  return (
    <div className="card vis-card">
      <div className="card-head card-head-flex">
        <h3>Network graph</h3>
        <div className="vis-legend">
          <span>
            <span
              className="dot-sm"
              style={{
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: 'var(--accent)',
              }}
            />{' '}
            Crawled
          </span>
          <span>
            <span
              className="dot-sm"
              style={{
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: 'rgba(255,255,255,0.5)',
              }}
            />{' '}
            Linked
          </span>
          <span>
            <span
              className="dot-sm"
              style={{
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: '#f87171',
              }}
            />{' '}
            Broken
          </span>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="vis-svg"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Network graph of ${nodes.length} pages`}
      >
        <defs>
          <radialGradient id="netgraph-rg" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgba(126, 232, 209, 0.08)" />
            <stop offset="100%" stopColor="rgba(126, 232, 209, 0)" />
          </radialGradient>
        </defs>
        <circle cx={CX} cy={CY} r={240} fill="url(#netgraph-rg)" />

        {edges.map((e, i) => (
          <line
            key={i}
            className="vis-edge"
            x1={e.a.x}
            y1={e.a.y}
            x2={e.b.x}
            y2={e.b.y}
            stroke={
              e.navigation
                ? 'rgba(126, 232, 209, 0.22)'
                : 'rgba(255,255,255,0.13)'
            }
            strokeWidth={e.navigation ? 0.9 : 0.7}
          />
        ))}

        {nodes.map((n, i) => (
          <g
            key={n.url}
            className="vis-node"
            style={{ animationDelay: `${(i % 50) * 14}ms` }}
          >
            <circle
              cx={n.x}
              cy={n.y}
              r={n.r}
              fill={
                n.depth === 0
                  ? 'var(--accent)'
                  : n.depth === 1
                  ? 'rgba(255,255,255,0.85)'
                  : 'rgba(126, 232, 209, 0.7)'
              }
              stroke="rgba(0,0,0,0.4)"
              strokeWidth={0.5}
            >
              <title>{n.url}</title>
            </circle>
            {n.depth <= 1 && (
              <text
                x={n.x}
                y={n.y + n.r + 12}
                textAnchor="middle"
                fontSize={10.5}
                fill="rgba(255,255,255,0.7)"
                fontFamily="ui-sans-serif"
              >
                {n.label}
              </text>
            )}
          </g>
        ))}
      </svg>
      {(cappedNodes || cappedEdges) && (
        <p
          className="text-muted"
          style={{ padding: '0 var(--pad) var(--pad)', fontSize: 11 }}
        >
          Showing {nodes.length} nodes, {edges.length} edges (capped from{' '}
          {total} links).
        </p>
      )}
    </div>
  );
}
