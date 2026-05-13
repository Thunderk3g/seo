import { useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import type { TreeNodeData } from '../api';

const NODE_W = 240;
const NODE_H = 58;
const COL_GAP = 70;
const ROW_GAP = 12;
const COL_WIDTH = NODE_W + COL_GAP;
const ROW_HEIGHT = NODE_H + ROW_GAP;

function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname + u.search;
    return path === '/' ? u.hostname : path;
  } catch {
    return url;
  }
}

function truncate(s: string | undefined | null, n: number): string {
  if (!s) return '';
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function statusColor(code: string | number | undefined | null): string {
  if (!code) return '#8A93A6';
  const c = String(code);
  if (c.startsWith('2')) return '#34A853';
  if (c.startsWith('3')) return '#4285F4';
  if (c.startsWith('4') || c.startsWith('5')) return '#EA4335';
  return '#8A93A6';
}

function collectExpandable(node: TreeNodeData | undefined, set: Set<string>): void {
  if (!node) return;
  if (node.children && node.children.length > 0) {
    set.add(node.url);
    node.children.forEach((c) => collectExpandable(c, set));
  }
}

interface PlacedNode {
  ref: TreeNodeData;
  x: number;
  y: number;
  depth: number;
}
interface PlacedEdge {
  from: PlacedNode;
  to: PlacedNode;
}
interface DragState {
  sx: number;
  sy: number;
  px: number;
  py: number;
  moved: boolean;
}

export default function TreeGraph({ root, autoExpandAll = false }: { root: TreeNodeData; autoExpandAll?: boolean }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([root.url]));
  const [zoom, setZoom] = useState(0.95);
  const [pan, setPan] = useState({ x: 24, y: 24 });
  const dragRef = useRef<DragState | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (autoExpandAll) {
      const s = new Set<string>();
      collectExpandable(root, s);
      s.add(root.url);
      setExpanded(s);
    } else {
      setExpanded(new Set([root.url]));
    }
  }, [root, autoExpandAll]);

  const layout = useMemo(() => {
    const nodes: PlacedNode[] = [];
    const edges: PlacedEdge[] = [];
    let nextY = 0;

    const walk = (node: TreeNodeData, depth: number): PlacedNode => {
      const isExpanded = expanded.has(node.url);
      const hasChildren = !!node.children && node.children.length > 0;

      if (!isExpanded || !hasChildren) {
        const y = nextY;
        nextY += ROW_HEIGHT;
        const placed: PlacedNode = { ref: node, x: depth * COL_WIDTH, y, depth };
        nodes.push(placed);
        return placed;
      }

      const startY = nextY;
      const placedKids = node.children.map((c) => walk(c, depth + 1));
      const endY = nextY;
      const centerY = (startY + endY - ROW_HEIGHT) / 2;
      const placed: PlacedNode = { ref: node, x: depth * COL_WIDTH, y: centerY, depth };
      nodes.push(placed);
      placedKids.forEach((k) => edges.push({ from: placed, to: k }));
      return placed;
    };

    walk(root, 0);

    const maxX = nodes.reduce((m, n) => Math.max(m, n.x + NODE_W), 0);
    const maxY = Math.max(nextY, ROW_HEIGHT);
    return { nodes, edges, width: maxX, height: maxY };
  }, [root, expanded]);

  const toggle = (url: string) => {
    setExpanded((prev) => {
      const s = new Set(prev);
      if (s.has(url)) s.delete(url);
      else s.add(url);
      return s;
    });
  };

  const onMouseDown = (e: ReactMouseEvent) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest('[data-tg-click]')) return;
    dragRef.current = { sx: e.clientX, sy: e.clientY, px: pan.x, py: pan.y, moved: false };
  };
  const onMouseMove = (e: ReactMouseEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.sx;
    const dy = e.clientY - dragRef.current.sy;
    if (Math.abs(dx) + Math.abs(dy) > 2) dragRef.current.moved = true;
    setPan({ x: dragRef.current.px + dx, y: dragRef.current.py + dy });
  };
  const endDrag = () => {
    dragRef.current = null;
  };

  const zoomIn = () => setZoom((z) => Math.min(2, z * 1.15));
  const zoomOut = () => setZoom((z) => Math.max(0.25, z / 1.15));
  const resetView = () => {
    setZoom(0.95);
    setPan({ x: 24, y: 24 });
  };
  const fit = () => {
    if (!wrapRef.current) return;
    const b = wrapRef.current.getBoundingClientRect();
    const pad = 40;
    const sx = (b.width - pad * 2) / Math.max(layout.width, 1);
    const sy = (b.height - pad * 2) / Math.max(layout.height, 1);
    const z = Math.max(0.25, Math.min(1.2, Math.min(sx, sy)));
    setZoom(z);
    setPan({ x: pad, y: pad });
  };

  return (
    <div
      className="tg-wrap"
      ref={wrapRef}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={endDrag}
      onMouseLeave={endDrag}
      style={{ cursor: dragRef.current ? 'grabbing' : 'grab' }}
    >
      <div className="tg-controls" data-tg-click>
        <button className="tg-btn" onClick={zoomIn} title="Zoom in">
          <span className="material-icons-outlined">add</span>
        </button>
        <button className="tg-btn" onClick={zoomOut} title="Zoom out">
          <span className="material-icons-outlined">remove</span>
        </button>
        <button className="tg-btn" onClick={fit} title="Fit to screen">
          <span className="material-icons-outlined">fit_screen</span>
        </button>
        <button className="tg-btn" onClick={resetView} title="Reset view">
          <span className="material-icons-outlined">center_focus_strong</span>
        </button>
        <span className="tg-zoom">{Math.round(zoom * 100)}%</span>
      </div>

      <div className="tg-legend" data-tg-click>
        <span>
          <i style={{ background: '#34A853' }} /> 2xx
        </span>
        <span>
          <i style={{ background: '#4285F4' }} /> 3xx
        </span>
        <span>
          <i style={{ background: '#EA4335' }} /> 4xx/5xx
        </span>
        <span>
          <i style={{ background: '#8A93A6' }} /> unknown
        </span>
      </div>

      <svg className="tg-canvas" width="100%" height="100%">
        <defs>
          <filter id="tg-shadow" x="-10%" y="-10%" width="120%" height="140%">
            <feDropShadow dx="0" dy="1" stdDeviation="1.2" floodColor="#1A2238" floodOpacity="0.18" />
          </filter>
        </defs>

        <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
          {layout.edges.map((e, i) => {
            const x1 = e.from.x + NODE_W;
            const y1 = e.from.y + NODE_H / 2;
            const x2 = e.to.x;
            const y2 = e.to.y + NODE_H / 2;
            const mx = (x1 + x2) / 2;
            return <path key={i} className="tg-edge" d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} />;
          })}

          {layout.nodes.map((n, i) => {
            const node = n.ref;
            const isExp = expanded.has(node.url);
            const hasChildren = !!node.children && node.children.length > 0;
            const isRoot = n.depth === 0;
            const color = statusColor(node.status_code);
            const urlLabel = isRoot ? truncate(node.url, 34) : shortUrl(node.url);
            return (
              <g
                key={`${node.url}-${i}`}
                transform={`translate(${n.x}, ${n.y})`}
                className={`tg-node ${isRoot ? 'is-root' : ''}`}
              >
                <rect className="tg-rect" width={NODE_W} height={NODE_H} rx={8} filter="url(#tg-shadow)" />
                <rect x={0} y={0} width={5} height={NODE_H} rx={2} fill={color} />
                <text className="tg-url" x={16} y={23}>
                  {truncate(urlLabel, 28)}
                </text>
                <text className="tg-title" x={16} y={43}>
                  {truncate(node.title || '(no title)', 32)}
                </text>
                <text className="tg-status" x={NODE_W - 12} y={23} textAnchor="end" fill={color}>
                  {node.status_code || '—'}
                </text>
                {hasChildren && (
                  <g
                    data-tg-click
                    transform={`translate(${NODE_W - 2}, ${NODE_H / 2})`}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      toggle(node.url);
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    <circle r={12} className="tg-toggle-bg" />
                    <text x={0} y={4} textAnchor="middle" className="tg-toggle-txt">
                      {isExp ? '−' : `+${node.total_children || node.children.length}`}
                    </text>
                  </g>
                )}
                <a
                  data-tg-click
                  href={node.url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(ev) => ev.stopPropagation()}
                >
                  <rect className="tg-hit" x={5} y={0} width={NODE_W - 30} height={NODE_H} fill="transparent" />
                </a>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="tg-hint">
        Drag to pan · Click a node to open URL · Click the badge on the right of a node to expand / collapse
      </div>
    </div>
  );
}
