// LiveArea — area chart for live/streaming time series.
//
// Mirrors .design-ref/project/charts.jsx LiveArea (lines 163-183). Behaves
// like Sparkline but with larger defaults and an always-on gradient fill so
// rolling buffers (e.g. crawl-rate over the last N samples) read cleanly.
// `max` allows callers to lock the y-axis ceiling so the line doesn't jitter
// when samples are added/removed.

import { useId } from 'react';

interface LiveAreaProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  max?: number;
}

export default function LiveArea({
  data,
  width = 220,
  height = 48,
  color = 'var(--accent)',
  max,
}: LiveAreaProps) {
  const gradientId = useId();

  if (!data || data.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" />;
  }

  const m = max ?? Math.max(...data, 1);
  const dx = width / (data.length - 1);
  const pts = data.map<[number, number]>((v, i) => [
    i * dx,
    height - (v / m) * (height - 4) - 2,
  ]);
  const path = pts
    .map((p, i) => (i === 0 ? `M${p[0]} ${p[1]}` : `L${p[0]} ${p[1]}`))
    .join(' ');
  const area = `${path} L${width} ${height} L0 ${height} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: 'block' }}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
    </svg>
  );
}
