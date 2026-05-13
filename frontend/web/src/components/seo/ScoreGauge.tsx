// ScoreGauge — circular progress used at the top of the Overview and
// the SEO Grade detail. Inline SVG so it scales cleanly and avoids
// pulling a chart lib for one ring.

interface Props {
  score: number | null;        // 0..100
  size?: number;
  thickness?: number;
  label?: string;              // small text under the number
}

export default function ScoreGauge({
  score,
  size = 156,
  thickness = 14,
  label = 'SEO Score',
}: Props) {
  const value = score ?? 0;
  const safe = Math.max(0, Math.min(100, value));
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const dash = (safe / 100) * c;
  const color =
    safe >= 80 ? 'var(--success)'
      : safe >= 50 ? 'var(--accent)'
        : safe >= 30 ? 'var(--warning)'
          : 'var(--error)';
  return (
    <div
      style={{
        position: 'relative',
        width: size,
        height: size,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--surface-3)"
          strokeWidth={thickness}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dasharray 0.6s ease' }}
        />
      </svg>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span
          style={{
            fontSize: 36,
            fontWeight: 600,
            letterSpacing: '-0.02em',
            color: 'var(--text)',
            lineHeight: 1,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {score === null ? '—' : Math.round(safe)}
        </span>
        <span
          style={{
            fontSize: 10.5,
            color: 'var(--text-3)',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            marginTop: 4,
          }}
        >
          {label}
        </span>
      </div>
    </div>
  );
}
