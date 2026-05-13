// PerformanceChart — dual-axis time-series for clicks (left, primary) and
// impressions (right, secondary). Inline SVG: no chart library, no
// dependency drift, ~120 lines.
//
// Why not Recharts: the dashboard has exactly one chart. Recharts adds
// ~50 KB gzipped and a context API for one component. The SVG below
// covers everything we need (axes, grid, two series, hover tooltip).

import { useMemo, useState } from 'react';
import type { GSCDailyRow } from '../../api/seoTypes';

interface Props {
  data: GSCDailyRow[];
  height?: number;
}

interface Point { x: number; y: number; row: GSCDailyRow }

export default function PerformanceChart({ data, height = 220 }: Props) {
  const [hover, setHover] = useState<Point | null>(null);

  const {
    width,
    padding,
    clicksPath,
    clicksArea,
    impressionsPath,
    clicksTicks,
    impressionsTicks,
    xLabels,
    clicksPoints,
  } = useMemo(() => {
    const W = 900;
    const H = height;
    const PAD = { top: 12, right: 56, bottom: 24, left: 56 };
    const plotW = W - PAD.left - PAD.right;
    const plotH = H - PAD.top - PAD.bottom;

    const maxC = Math.max(1, ...data.map((d) => d.clicks));
    const maxI = Math.max(1, ...data.map((d) => d.impressions));
    const n = Math.max(1, data.length - 1);

    const cp: Point[] = [];
    const ip: Point[] = [];
    data.forEach((row, i) => {
      const x = PAD.left + (i / n) * plotW;
      cp.push({ x, y: PAD.top + plotH - (row.clicks / maxC) * plotH, row });
      ip.push({ x, y: PAD.top + plotH - (row.impressions / maxI) * plotH, row });
    });

    const toPath = (pts: Point[]) =>
      pts
        .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
        .join(' ');

    const area =
      cp.length > 0
        ? `${toPath(cp)} L${cp[cp.length - 1].x.toFixed(2)},${PAD.top + plotH} L${cp[0].x.toFixed(2)},${PAD.top + plotH} Z`
        : '';

    const cTicks: { v: number; y: number }[] = [];
    const iTicks: { v: number; y: number }[] = [];
    for (let t = 0; t <= 4; t += 1) {
      const ratio = t / 4;
      cTicks.push({
        v: Math.round(maxC * (1 - ratio)),
        y: PAD.top + ratio * plotH,
      });
      iTicks.push({
        v: Math.round(maxI * (1 - ratio)),
        y: PAD.top + ratio * plotH,
      });
    }

    // X labels: pick ~6 spaced labels.
    const labels: { label: string; x: number }[] = [];
    if (data.length > 0) {
      const step = Math.max(1, Math.floor(data.length / 6));
      for (let i = 0; i < data.length; i += step) {
        labels.push({
          label: shortDate(data[i].date),
          x: PAD.left + (i / n) * plotW,
        });
      }
      // Always include the last one.
      labels.push({
        label: shortDate(data[data.length - 1].date),
        x: PAD.left + plotW,
      });
    }

    return {
      width: W,
      padding: PAD,
      clicksPath: toPath(cp),
      clicksArea: area,
      impressionsPath: toPath(ip),
      clicksTicks: cTicks,
      impressionsTicks: iTicks,
      xLabels: labels,
      clicksPoints: cp,
    };
  }, [data, height]);

  if (data.length === 0) {
    return (
      <div className="seo-perf-chart">
        <div className="seo-empty">No daily data available.</div>
      </div>
    );
  }

  return (
    <div className="seo-perf-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Daily clicks and impressions trend"
        onMouseLeave={() => setHover(null)}
      >
        {/* horizontal grid + clicks (left) axis */}
        <g className="grid">
          {clicksTicks.map((t) => (
            <line
              key={`g-${t.y}`}
              x1={padding.left}
              x2={width - padding.right}
              y1={t.y}
              y2={t.y}
            />
          ))}
        </g>
        <g className="axis">
          {clicksTicks.map((t) => (
            <text key={`yc-${t.y}`} x={padding.left - 8} y={t.y + 4} textAnchor="end">
              {formatCompact(t.v)}
            </text>
          ))}
          {impressionsTicks.map((t) => (
            <text
              key={`yi-${t.y}`}
              x={width - padding.right + 8}
              y={t.y + 4}
              textAnchor="start"
            >
              {formatCompact(t.v)}
            </text>
          ))}
          {xLabels.map((l, i) => (
            <text key={`x-${i}`} x={l.x} y={height - 6} textAnchor="middle">
              {l.label}
            </text>
          ))}
        </g>

        <path className="clicks-area" d={clicksArea} />
        <path className="impressions-line" d={impressionsPath} />
        <path className="clicks-line" d={clicksPath} />

        {/* invisible hit areas for hover */}
        {clicksPoints.map((p, i) => (
          <rect
            key={`hit-${i}`}
            x={p.x - 4}
            y={padding.top}
            width={8}
            height={height - padding.top - padding.bottom}
            fill="transparent"
            onMouseEnter={() => setHover({ ...p, y: p.y })}
          />
        ))}

        {hover && (
          <g>
            <line
              x1={hover.x}
              x2={hover.x}
              y1={padding.top}
              y2={height - padding.bottom}
              stroke="var(--border-2)"
            />
            <circle cx={hover.x} cy={hover.y} r="4" fill="var(--accent)" />
          </g>
        )}
      </svg>

      {hover && (
        <div
          style={{
            position: 'absolute',
            left: `${(hover.x / width) * 100}%`,
            top: 0,
            transform: 'translate(-50%, 0)',
            background: 'var(--surface)',
            border: '1px solid var(--border-2)',
            borderRadius: 8,
            padding: '8px 12px',
            boxShadow: 'var(--elev-2)',
            fontSize: 11.5,
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
            zIndex: 1,
          }}
        >
          <div style={{ fontWeight: 600, color: 'var(--text)' }}>
            {hover.row.date}
          </div>
          <div style={{ color: 'var(--accent)' }}>
            Clicks <b style={{ color: 'var(--text)' }}>{hover.row.clicks.toLocaleString()}</b>
          </div>
          <div style={{ color: 'var(--text-2)' }}>
            Impressions <b style={{ color: 'var(--text)' }}>{hover.row.impressions.toLocaleString()}</b>
          </div>
          <div style={{ color: 'var(--text-3)' }}>
            CTR <b style={{ color: 'var(--text)' }}>{(hover.row.ctr * 100).toFixed(2)}%</b>
            {'  '}· Pos <b style={{ color: 'var(--text)' }}>{hover.row.position.toFixed(1)}</b>
          </div>
        </div>
      )}
    </div>
  );
}

function shortDate(iso: string): string {
  // "2026-05-13" → "May 13"
  const d = new Date(iso + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
