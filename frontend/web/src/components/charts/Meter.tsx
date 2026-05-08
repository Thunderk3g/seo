// Meter — minimal horizontal progress bar primitive.
//
// Mirrors .design-ref/project/charts.jsx Meter (lines 123-131). The width
// transition is intentional so callers can swap `value` and watch the bar
// animate smoothly without any extra plumbing.
//
// No matching `.meter` / `.meter-fill` classes were found in
// .design-ref/project/styles.css, so the styling is inlined to stay
// self-contained.

interface MeterProps {
  value: number;
  max?: number;
  color?: string;
  height?: number;
}

export default function Meter({
  value,
  max = 100,
  color = 'var(--accent)',
  height = 4,
}: MeterProps) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div
      style={{
        height,
        background: 'rgba(255,255,255,0.06)',
        borderRadius: 999,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: '100%',
          background: color,
          transition: 'width 0.6s cubic-bezier(0.3,0.7,0.4,1)',
        }}
      />
    </div>
  );
}
