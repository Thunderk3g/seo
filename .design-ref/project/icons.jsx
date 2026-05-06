// icons.jsx — single source of truth for icons.
// All icons are 1.5px stroke, 24×24 viewBox, currentColor.
// <Icon name="..." size={16} /> for everything.

const __ICON_PATHS = {
  // Sidebar / nav
  dashboard: 'M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z',
  sessions: 'M3 12a9 9 0 1 0 9-9M3 12V5M3 12h7M9 9l3 3v3',
  pages: 'M14 3v5h5M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M9 13h6 M9 17h6',
  issues: 'M12 9v4M12 17h.01M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0z',
  analytics: 'M3 3v18h18 M7 14l4-4 4 4 5-5',
  visualizations: 'M5 7a2 2 0 1 0 0 4 2 2 0 0 0 0-4z M19 13a2 2 0 1 0 0 4 2 2 0 0 0 0-4z M19 5a2 2 0 1 0 0 4 2 2 0 0 0 0-4z M19 7H7 M19 15H7 M5 11v2',
  exports: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z',

  // Topbar / general
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M21 21l-4.35-4.35',
  bell: 'M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9 M13.73 21a2 2 0 0 1-3.46 0',
  filter: 'M22 3H2l8 9.46V19l4 2v-8.54z',
  download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3',
  play: 'M5 3l14 9-14 9z',
  pause: 'M6 4h4v16H6z M14 4h4v16h-4z',
  stop: 'M5 5h14v14H5z',
  chevDown: 'M6 9l6 6 6-6',
  chevRight: 'M9 6l6 6-6 6',
  chevLeft: 'M15 6l-6 6 6 6',
  check: 'M20 6L9 17l-5-5',
  x: 'M18 6 6 18 M6 6l12 12',
  plus: 'M12 5v14M5 12h14',
  external: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6 M15 3h6v6 M10 14L21 3',
  copy: 'M9 9h11v11H9z M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1',
  more: 'M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z M19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z M5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  refresh: 'M21 12a9 9 0 1 1-3-6.7L21 8 M21 3v5h-5',
  link: 'M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 1 0-7.07-7.07l-1 1 M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1-1',
  globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M3 12h18 M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z',
  folder: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h6l2 3h8a2 2 0 0 1 2 2z',
  file: 'M14 3v5h5M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z',
  arrowUp: 'M12 19V5 M5 12l7-7 7 7',
  arrowDown: 'M12 5v14 M19 12l-7 7-7-7',
  arrowRight: 'M5 12h14 M12 5l7 7-7 7',
  spider: 'M12 6a3 3 0 1 1 0 6 3 3 0 0 1 0-6z M6 4l3 4 M18 4l-3 4 M3 9l4 1 M21 9l-4 1 M3 15l4-2 M21 15l-4-2 M6 20l3-4 M18 20l-3-4',
  zap: 'M13 2 3 14h7l-1 8 10-12h-7z',
  cpu: 'M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3 M5 5h14v14H5z M9 9h6v6H9z',
  database: 'M12 3c4.97 0 9 1.34 9 3v12c0 1.66-4.03 3-9 3s-9-1.34-9-3V6c0-1.66 4.03-3 9-3z M3 6c0 1.66 4.03 3 9 3s9-1.34 9-3 M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3',
  user: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z M12 1v2 M12 21v2 M4.22 4.22l1.42 1.42 M18.36 18.36l1.42 1.42 M1 12h2 M21 12h2 M4.22 19.78l1.42-1.42 M18.36 5.64l1.42-1.42',
  moon: 'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z',
  trend: 'M23 6l-9.5 9.5-5-5L1 18 M17 6h6v6',
  eye: 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  history: 'M3 12a9 9 0 1 0 9-9 M3 12V5 M3 12h7 M12 7v5l3 3',
  send: 'M22 2 11 13 M22 2l-7 20-4-9-9-4z',
};

// Spider/bug-style brand mark — clean geometric.
function BrandMark({ size = 22, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="none">
      {/* Hex node graph: a center node with three ring nodes — "lattice" of crawled URLs */}
      <circle cx="12" cy="12" r="3" fill={color} />
      <circle cx="4" cy="6" r="1.6" fill={color} opacity="0.85" />
      <circle cx="20" cy="6" r="1.6" fill={color} opacity="0.85" />
      <circle cx="4" cy="18" r="1.6" fill={color} opacity="0.55" />
      <circle cx="20" cy="18" r="1.6" fill={color} opacity="0.55" />
      <circle cx="12" cy="2.5" r="1.2" fill={color} opacity="0.7" />
      <circle cx="12" cy="21.5" r="1.2" fill={color} opacity="0.4" />
      <g stroke={color} strokeWidth="1" opacity="0.5">
        <line x1="12" y1="12" x2="4" y2="6" />
        <line x1="12" y1="12" x2="20" y2="6" />
        <line x1="12" y1="12" x2="4" y2="18" />
        <line x1="12" y1="12" x2="20" y2="18" />
        <line x1="12" y1="12" x2="12" y2="2.5" />
        <line x1="12" y1="12" x2="12" y2="21.5" />
      </g>
    </svg>
  );
}

function Icon({ name, size = 16, strokeWidth = 1.6, style, className }) {
  const d = __ICON_PATHS[name];
  if (!d) return <span style={{ display: 'inline-block', width: size, height: size }} />;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={strokeWidth}
         strokeLinecap="round" strokeLinejoin="round"
         style={style} className={className} aria-hidden="true">
      {d.split('M').filter(Boolean).map((p, i) => (
        <path key={i} d={'M' + p.trim()} />
      ))}
    </svg>
  );
}

Object.assign(window, { Icon, BrandMark });
