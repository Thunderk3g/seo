// TimeSeriesChart — minimal multi-series SVG line chart with axes.
//
// Pure SVG, no chart library. Designed for the Adobe Analytics
// page-views + visits trend. Supports up to 4 series; each series is
// rendered as a single polyline with a gradient area fill underneath
// the primary one. X-axis labels are decimated so a 30-day window
// shows ~6 labels, not 30.
//
// Visual conventions match the existing Sparkline / MiniBars /
// MiniDonut family — Bajaj blue (var(--accent)) for the primary
// series, a softer accent for the secondary.

import { useId, useMemo } from 'react';

export interface TimeSeriesPoint {
  date: string; // ISO yyyy-mm-dd
  [key: string]: number | string;
}

interface SeriesDef {
  key: string;
  label: string;
  color: string;
  fill?: boolean; // gradient area fill under the line
}

interface Props {
  data: TimeSeriesPoint[];
  series: SeriesDef[];
  height?: number;
  yLabel?: string;
  /** Number of x-axis ticks to render (date labels decimated). */
  xTicks?: number;
}

export default function TimeSeriesChart({
  data,
  series,
  height = 220,
  yLabel,
  xTicks = 6,
}: Props) {
  const gradientId = useId();
  // Compact compact-style number formatter for axis ticks.
  const fmt = (n: number) => {
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (abs >= 1_000) return (n / 1_000).toFixed(0) + 'K';
    return String(Math.round(n));
  };

  // Viewport math.
  const width = 720;
  const padLeft = 44;
  const padRight = 14;
  const padTop = 12;
  const padBottom = 24;
  const innerW = width - padLeft - padRight;
  const innerH = height - padTop - padBottom;

  const { maxY, points, xLabels } = useMemo(() => {
    if (!data || data.length === 0) {
      return { maxY: 1, points: {} as Record<string, [number, number][]>, xLabels: [] as { x: number; label: string }[] };
    }
    let mx = 0;
    for (const p of data) {
      for (const s of series) {
        const v = Number(p[s.key] ?? 0);
        if (v > mx) mx = v;
      }
    }
    mx = mx > 0 ? mx : 1;

    const dx = data.length > 1 ? innerW / (data.length - 1) : 0;
    const pts: Record<string, [number, number][]> = {};
    for (const s of series) {
      pts[s.key] = data.map<[number, number]>((p, i) => [
        padLeft + i * dx,
        padTop + innerH - (Number(p[s.key] ?? 0) / mx) * innerH,
      ]);
    }

    // Decimate x labels — keep ~xTicks evenly spaced.
    const labels: { x: number; label: string }[] = [];
    const step = Math.max(1, Math.floor(data.length / xTicks));
    data.forEach((p, i) => {
      if (i % step === 0 || i === data.length - 1) {
        labels.push({ x: padLeft + i * dx, label: shortDate(p.date) });
      }
    });

    return { maxY: mx, points: pts, xLabels: labels };
  }, [data, series, innerW, innerH, padLeft, padTop, xTicks]);

  if (!data || data.length < 2) {
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
        Not enough data points to plot a trend.
      </div>
    );
  }

  // Y-axis tick lines + labels (4 ticks).
  const yTicks = [0, 0.25, 0.5, 0.75, 1.0].map((f) => {
    const y = padTop + innerH - f * innerH;
    return { y, label: fmt(f * maxY) };
  });

  // Primary series area path.
  const primary = series[0];
  const primaryPts = points[primary.key] || [];
  const areaPath =
    primary?.fill !== false && primaryPts.length > 1
      ? `M ${primaryPts[0][0]} ${padTop + innerH} L ${primaryPts
          .map(([x, y]) => `${x} ${y}`)
          .join(' L ')} L ${primaryPts[primaryPts.length - 1][0]} ${padTop + innerH} Z`
      : '';

  return (
    <div className="ts-chart-wrap">
      <svg
        width="100%"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Time series of ${series.map((s) => s.label).join(' and ')}`}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={primary?.color ?? 'var(--accent)'} stopOpacity="0.28" />
            <stop offset="100%" stopColor={primary?.color ?? 'var(--accent)'} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Y grid lines */}
        {yTicks.map((t, i) => (
          <line
            key={`yg-${i}`}
            x1={padLeft}
            x2={width - padRight}
            y1={t.y}
            y2={t.y}
            stroke="var(--border-1)"
            strokeWidth={1}
            strokeDasharray="2,3"
          />
        ))}

        {/* Y labels */}
        {yTicks.map((t, i) => (
          <text
            key={`yl-${i}`}
            x={padLeft - 6}
            y={t.y + 3}
            fontSize="10"
            textAnchor="end"
            fill="var(--text-3)"
          >
            {t.label}
          </text>
        ))}

        {/* X labels */}
        {xLabels.map((tk, i) => (
          <text
            key={`xl-${i}`}
            x={tk.x}
            y={height - 6}
            fontSize="10"
            textAnchor="middle"
            fill="var(--text-3)"
          >
            {tk.label}
          </text>
        ))}

        {/* Primary area fill */}
        {areaPath && <path d={areaPath} fill={`url(#${gradientId})`} />}

        {/* All series lines */}
        {series.map((s) => {
          const pts = points[s.key] || [];
          if (pts.length < 2) return null;
          const d = `M ${pts.map(([x, y]) => `${x} ${y}`).join(' L ')}`;
          return (
            <path
              key={s.key}
              d={d}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          );
        })}
      </svg>

      <div className="ts-chart-legend">
        {series.map((s) => (
          <span key={s.key} className="ts-chart-legend-item">
            <span
              className="ts-chart-legend-dot"
              style={{ background: s.color }}
            />
            <span>{s.label}</span>
          </span>
        ))}
        {yLabel && <span className="ts-chart-ylabel">· {yLabel}</span>}
      </div>
    </div>
  );
}

function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
