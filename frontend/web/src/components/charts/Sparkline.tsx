// Sparkline — minimal SVG line chart for compact trend visualisation.
//
// Mirrors .design-ref/project/charts.jsx Sparkline (lines 5-31). Renders a
// stroked polyline plus an optional gradient area fill below the line. Empty
// or single-point data renders an empty placeholder SVG to preserve layout.

import { useId } from 'react';

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: boolean;
  strokeWidth?: number;
}

export default function Sparkline({
  data,
  width = 100,
  height = 32,
  color = 'currentColor',
  fill = true,
  strokeWidth = 1.5,
}: SparklineProps) {
  const gradientId = useId();

  if (!data || data.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" />;
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const dx = width / (data.length - 1);
  const pts = data.map<[number, number]>((v, i) => [
    i * dx,
    height - 2 - ((v - min) / range) * (height - 4),
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
      style={{ display: 'block', overflow: 'visible' }}
    >
      {fill && (
        <>
          <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.35" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${gradientId})`} />
        </>
      )}
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
