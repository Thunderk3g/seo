// HealthGauge — full-ring SVG gauge for the SEO Health Score.
//
// Mirrors .design-ref/project/charts.jsx Gauge (lines 89-119): a 360° track
// rotated -90° so the fill begins at 12 o'clock and sweeps clockwise. The
// score value is tweened from 0 → score over 800ms with an easeOutCubic
// curve. `pathLength=100` keeps the static fallback dasharray of
// `${score} ${100 - score}` working when animation is disabled.
//
// Color palette stays band-driven so the calling sites don't need to change:
//   good (≥80) → #6ee7b7   warn (≥50) → #fbbf24   poor → #f87171

import { useEffect, useState } from 'react';

interface Props {
  score: number;            // 0..100
  band: 'good' | 'warn' | 'poor';
  size?: number;            // pixel width/height
  thickness?: number;       // arc stroke width
  animate?: boolean;
}

const BAND_COLOR: Record<Props['band'], string> = {
  good: '#6ee7b7',
  warn: '#fbbf24',
  poor: '#f87171',
};

const BAND_LABEL: Record<Props['band'], string> = {
  good: 'Good',
  warn: 'Needs attention',
  poor: 'Poor',
};

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export default function HealthGauge({
  score,
  band,
  size = 200,
  thickness = 16,
  animate = true,
}: Props) {
  // Clamp defensively even though the backend already does it.
  const safe = Math.max(0, Math.min(100, score));

  const cx = size / 2;
  const cy = size / 2;
  const r = (size - thickness) / 2;

  const color = BAND_COLOR[band];
  const label = BAND_LABEL[band];

  const shouldAnimate = animate && !prefersReducedMotion();
  const [v, setV] = useState(shouldAnimate ? 0 : safe);

  useEffect(() => {
    if (!shouldAnimate) {
      setV(safe);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const from = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / 800);
      const eased = 1 - Math.pow(1 - k, 3);
      setV(from + (safe - from) * eased);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [safe, shouldAnimate]);

  // pathLength=100 lets us keep the static fallback dasharray of
  // `${safe} ${100 - safe}` while the animated path uses the real circumference.
  const c = 2 * Math.PI * r;
  const len = (v / 100) * c;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`SEO Health score ${safe} of 100, ${label}`}
        style={{ display: 'block' }}
      >
        {/* Track — full ring */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={thickness}
          pathLength={100}
        />
        {/* Fill arc — rotated -90° so it starts at 12 o'clock. */}
        <g transform={`rotate(-90 ${cx} ${cy})`}>
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={thickness}
            strokeDasharray={`${len} ${c - len}`}
            strokeLinecap="round"
          />
        </g>
        {/* Center number */}
        <text
          x={cx}
          y={cy - 2}
          textAnchor="middle"
          fontSize={size * 0.28}
          fontWeight={600}
          fill="currentColor"
          dominantBaseline="middle"
          style={{ fontFeatureSettings: '"tnum"' }}
        >
          {safe}
        </text>
        {/* Subtitle (band name) */}
        <text
          x={cx}
          y={cy + size * 0.18}
          textAnchor="middle"
          fontSize={size * 0.075}
          fill={color}
          dominantBaseline="middle"
          style={{ letterSpacing: '0.04em', textTransform: 'uppercase' }}
        >
          {label}
        </text>
      </svg>
    </div>
  );
}
