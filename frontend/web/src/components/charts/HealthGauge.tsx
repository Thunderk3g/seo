// HealthGauge — minimal SVG semicircle gauge for the SEO Health Score.
//
// Renders a 180° track from -90° (left) to +90° (right) plus a colored
// fill arc proportional to `score`. Mirrors MiniDonut's stroke-dasharray
// trick: the path's `pathLength` is set to 100 so we can express the
// fill length as `score`/(100 - score) directly without recomputing the
// arc length. SVG plumbing only — no chart library.
//
// Color palette matches the spec:
//   good (≥80) → #6ee7b7   warn (≥50) → #fbbf24   poor → #f87171

interface Props {
  score: number;            // 0..100
  band: 'good' | 'warn' | 'poor';
  size?: number;            // pixel width (height ≈ size/2 + label room)
  thickness?: number;       // arc stroke width
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

export default function HealthGauge({
  score,
  band,
  size = 200,
  thickness = 16,
}: Props) {
  // Clamp defensively even though the backend already does it.
  const safe = Math.max(0, Math.min(100, score));

  const cx = size / 2;
  const cy = size / 2;
  const r = (size - thickness) / 2;

  // Two endpoints of the semicircle on the X-axis (y = cy).
  // Start at (cx - r, cy), end at (cx + r, cy), sweep over the top.
  const startX = cx - r;
  const endX = cx + r;
  const arcY = cy;

  // SVG arc command for the full 180° track. `large-arc-flag=0` and
  // `sweep-flag=1` draws the upper semicircle.
  const trackPath = `M ${startX} ${arcY} A ${r} ${r} 0 0 1 ${endX} ${arcY}`;

  // Total visual height = top of the arc (cy - r) down to label area.
  const heightPx = cy + thickness; // semicircle + a little padding

  const color = BAND_COLOR[band];
  const label = BAND_LABEL[band];

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
        height={heightPx}
        viewBox={`0 0 ${size} ${heightPx}`}
        role="img"
        aria-label={`SEO Health score ${safe} of 100, ${label}`}
      >
        {/* Track */}
        <path
          d={trackPath}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={thickness}
          strokeLinecap="round"
          pathLength={100}
        />
        {/* Fill — pathLength=100 lets us use score directly. */}
        <path
          d={trackPath}
          fill="none"
          stroke={color}
          strokeWidth={thickness}
          strokeLinecap="round"
          pathLength={100}
          strokeDasharray={`${safe} ${100 - safe}`}
        />
        {/* Center number */}
        <text
          x={cx}
          y={cy - thickness / 2}
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
          y={cy + thickness / 2 + 4}
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
