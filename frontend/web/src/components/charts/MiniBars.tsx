// MiniBars — minimal vertical bar chart using flex divs (no SVG, no library).
//
// Bars are sized proportional to the max count; the value is shown above each
// bar and a label below it. Mirrors .design-ref/project/charts.jsx BarChart.
// To extend: add a `valueFormat` prop or per-bar colors via an `entries[i].color`.

interface BarEntry {
  label: string;
  count: number;
}

interface Props {
  entries: BarEntry[];
  color?: string;
  height?: number;
}

export default function MiniBars({
  entries,
  color = 'var(--accent)',
  height = 200,
}: Props) {
  if (!entries || entries.length === 0) {
    return (
      <div
        style={{
          height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-3)',
          fontSize: 12,
        }}
      >
        No data
      </div>
    );
  }

  const max = Math.max(...entries.map((e) => e.count), 0);
  const usableHeight = height - 24; // reserve room for value + label rows
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: 6,
        height,
        paddingTop: 8,
      }}
    >
      {entries.map((e, i) => {
        const h = max > 0 ? (e.count / max) * usableHeight : 1;
        return (
          <div
            key={`${e.label}-${i}`}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 6,
              minWidth: 0,
            }}
          >
            <div
              style={{
                fontSize: 10,
                color: 'var(--text-3)',
                fontVariantNumeric: 'tabular-nums',
                height: 12,
              }}
            >
              {e.count.toLocaleString()}
            </div>
            <div
              title={`${e.label}: ${e.count}`}
              style={{
                width: '100%',
                height: Math.max(1, h),
                background: color,
                borderRadius: '3px 3px 0 0',
                minHeight: 1,
                opacity: 0.85,
                transition: 'height 0.6s var(--ease, cubic-bezier(0.2,0.7,0.3,1))',
              }}
            />
            <div
              style={{
                fontSize: 10,
                color: 'var(--text-3)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                width: '100%',
                textAlign: 'center',
              }}
            >
              {e.label}
            </div>
          </div>
        );
      })}
    </div>
  );
}
