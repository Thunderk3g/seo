// MiniDonut — minimal SVG donut chart, no chart library.
//
// Renders concentric arcs as overlapping <circle>s with stroke-dasharray
// proportional to each entry's share of the total. Visual style mirrors
// .design-ref/project/charts.jsx Donut (rotated -90deg so 0% starts at 12
// o'clock).
//
// The reveal is animated via requestAnimationFrame over 700ms using an
// easeOutCubic curve (1 - (1 - k)^3). When `prefers-reduced-motion: reduce`
// is requested, the animation is skipped and arcs render at their final
// length on first paint.

import { useEffect, useState } from 'react';

interface DonutEntry {
  label: string;
  count: number;
  color: string;
}

interface Props {
  entries: DonutEntry[];
  total?: number;
  size?: number;
  thickness?: number;
  centerLabel?: string;
  animate?: boolean;
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export default function MiniDonut({
  entries,
  total,
  size = 160,
  thickness = 18,
  centerLabel = 'URLs',
  animate = true,
}: Props) {
  const sum = entries.reduce((s, e) => s + e.count, 0);
  const computedTotal = total ?? sum;
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const cx = size / 2;
  const cy = size / 2;

  // Empty / all-zero state — render a single grey ring as the empty placeholder.
  const hasData = sum > 0;

  const shouldAnimate = animate && !prefersReducedMotion();
  const [t, setT] = useState(shouldAnimate ? 0 : 1);

  useEffect(() => {
    if (!shouldAnimate) {
      setT(1);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / 700);
      const eased = 1 - Math.pow(1 - k, 3);
      setT(eased);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [shouldAnimate, sum, entries.length]);

  let acc = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {/* Track */}
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke="rgba(255,255,255,0.06)"
        strokeWidth={thickness}
      />
      {hasData && (
        <g transform={`rotate(-90 ${cx} ${cy})`}>
          {entries.map((e, i) => {
            if (e.count <= 0) return null;
            const len = (e.count / sum) * c * t;
            const dasharray = `${len} ${c - len}`;
            const offset = -((acc / sum) * c * t);
            acc += e.count;
            return (
              <circle
                key={`${e.label}-${i}`}
                cx={cx}
                cy={cy}
                r={r}
                fill="none"
                stroke={e.color}
                strokeWidth={thickness}
                strokeDasharray={dasharray}
                strokeDashoffset={offset}
                strokeLinecap="butt"
              />
            );
          })}
        </g>
      )}
      <text
        x={cx}
        y={cy - 2}
        textAnchor="middle"
        fontSize={size * 0.22}
        fontWeight={600}
        fill="currentColor"
        dominantBaseline="middle"
        style={{ fontFeatureSettings: '"tnum"' }}
      >
        {computedTotal.toLocaleString()}
      </text>
      <text
        x={cx}
        y={cy + size * 0.16}
        textAnchor="middle"
        fontSize={size * 0.075}
        fill="currentColor"
        opacity={0.55}
        style={{ letterSpacing: '0.04em', textTransform: 'uppercase' }}
      >
        {centerLabel}
      </text>
    </svg>
  );
}
