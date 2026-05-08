// MiniDonut — minimal SVG donut chart, no chart library.
//
// Renders concentric arcs as overlapping <circle>s with stroke-dasharray
// proportional to each entry's share of the total. Visual style mirrors
// .design-ref/project/charts.jsx Donut (rotated -90deg so 0% starts at 12
// o'clock). To extend: add an `animate` prop and ease the dasharray over time
// like the design-ref version, or accept a click handler per segment.

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
}

export default function MiniDonut({
  entries,
  total,
  size = 160,
  thickness = 18,
  centerLabel = 'URLs',
}: Props) {
  const sum = entries.reduce((s, e) => s + e.count, 0);
  const computedTotal = total ?? sum;
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const cx = size / 2;
  const cy = size / 2;

  // Empty / all-zero state — render a single grey ring as the empty placeholder.
  const hasData = sum > 0;

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
            const len = (e.count / sum) * c;
            const dasharray = `${len} ${c - len}`;
            const offset = -((acc / sum) * c);
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
