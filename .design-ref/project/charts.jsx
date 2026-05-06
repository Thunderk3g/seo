// charts.jsx — small SVG chart primitives.
// Sparkline, donut, ring (gauge), bar histogram, area.
// All accept a `color` (CSS color, supports var(--accent)).

function Sparkline({ data, width = 100, height = 32, color = 'currentColor', fill = true, strokeWidth = 1.5 }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const dx = width / (data.length - 1);
  const pts = data.map((v, i) => [i * dx, height - 2 - ((v - min) / range) * (height - 4)]);
  const path = pts.map((p, i) => (i === 0 ? `M${p[0]} ${p[1]}` : `L${p[0]} ${p[1]}`)).join(' ');
  const area = `${path} L${width} ${height} L0 ${height} Z`;
  const id = React.useId();
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block', overflow: 'visible' }}>
      {fill && (
        <>
          <defs>
            <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.35" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${id})`} />
        </>
      )}
      <path d={path} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// Multi-segment donut. segments: [{value, color, label}]
function Donut({ segments, size = 160, thickness = 18, label, sublabel, animate = true }) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  let acc = 0;
  const [t, setT] = React.useState(animate ? 0 : 1);
  React.useEffect(() => {
    if (!animate) return;
    let raf;
    const start = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - start) / 700);
      const eased = 1 - Math.pow(1 - k, 3);
      setT(eased);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [animate]);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke="rgba(255,255,255,0.04)" strokeWidth={thickness} />
      <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
        {segments.map((s, i) => {
          const len = (s.value / total) * c * t;
          const dasharray = `${len} ${c - len}`;
          const offset = -((acc / total) * c * t);
          acc += s.value;
          return (
            <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none"
                    stroke={s.color} strokeWidth={thickness}
                    strokeDasharray={dasharray} strokeDashoffset={offset}
                    strokeLinecap="butt" />
          );
        })}
      </g>
      {label != null && (
        <text x={size / 2} y={size / 2 - 2} textAnchor="middle"
              fontSize={size * 0.22} fontWeight="600" fill="currentColor"
              dominantBaseline="middle" style={{ fontFeatureSettings: '"tnum"' }}>
          {label}
        </text>
      )}
      {sublabel && (
        <text x={size / 2} y={size / 2 + size * 0.16} textAnchor="middle"
              fontSize={size * 0.075} fill="currentColor" opacity="0.55"
              style={{ letterSpacing: '0.04em', textTransform: 'uppercase' }}>
          {sublabel}
        </text>
      )}
    </svg>
  );
}

// Gauge ring (single value, 0-100), with track.
function Gauge({ value, size = 160, thickness = 12, color = 'var(--accent)', animate = true }) {
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const [v, setV] = React.useState(animate ? 0 : value);
  React.useEffect(() => {
    if (!animate) { setV(value); return; }
    let raf;
    const start = performance.now();
    const from = 0;
    const step = (now) => {
      const k = Math.min(1, (now - start) / 900);
      const eased = 1 - Math.pow(1 - k, 3);
      setV(from + (value - from) * eased);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, animate]);
  const len = (v / 100) * c;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke="rgba(255,255,255,0.06)" strokeWidth={thickness} />
      <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none"
                stroke={color} strokeWidth={thickness}
                strokeDasharray={`${len} ${c - len}`}
                strokeLinecap="round" />
      </g>
    </svg>
  );
}

// Horizontal stacked bars (tiny meter).
function Meter({ value, max = 100, color = 'var(--accent)', height = 4 }) {
  return (
    <div style={{ height, background: 'rgba(255,255,255,0.06)', borderRadius: 999, overflow: 'hidden' }}>
      <div style={{ width: `${Math.min(100, (value / max) * 100)}%`, height: '100%',
                    background: color, transition: 'width 0.6s cubic-bezier(0.3,0.7,0.4,1)' }} />
    </div>
  );
}

// Histogram / bar chart. data: [{label, value, color?}]
function BarChart({ data, height = 160, color = 'var(--accent)', valueFormat = (v) => v }) {
  const max = Math.max(...data.map((d) => d.value)) || 1;
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height, paddingTop: 8 }}>
      {data.map((d, i) => {
        const h = (d.value / max) * (height - 24);
        return (
          <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column',
                                alignItems: 'center', gap: 6, minWidth: 0 }}>
            <div style={{ fontSize: 10, color: 'var(--text-3)',
                          fontVariantNumeric: 'tabular-nums', height: 12 }}>
              {valueFormat(d.value)}
            </div>
            <div title={`${d.label}: ${d.value}`}
                 style={{ width: '100%', height: h, background: d.color || color,
                          borderRadius: '3px 3px 0 0', minHeight: 2,
                          opacity: 0.85, transition: 'height 0.6s cubic-bezier(0.3,0.7,0.4,1)' }} />
            <div style={{ fontSize: 10, color: 'var(--text-3)',
                          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                          width: '100%', textAlign: 'center' }}>
              {d.label}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Live area chart that scrolls left. data is rolling array.
function LiveArea({ data, width = 220, height = 48, color = 'var(--accent)', max }) {
  if (!data || data.length < 2) return <svg width={width} height={height} />;
  const m = max ?? Math.max(...data, 1);
  const dx = width / (data.length - 1);
  const pts = data.map((v, i) => [i * dx, height - ((v / m) * (height - 4)) - 2]);
  const path = pts.map((p, i) => (i === 0 ? `M${p[0]} ${p[1]}` : `L${p[0]} ${p[1]}`)).join(' ');
  const area = `${path} L${width} ${height} L0 ${height} Z`;
  const id = React.useId();
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${id})`} />
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

Object.assign(window, { Sparkline, Donut, Gauge, Meter, BarChart, LiveArea });
