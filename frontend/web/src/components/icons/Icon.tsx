// Icon.tsx — subset of icons ported from .design-ref/project/icons.jsx.
// Day 0 includes only icons used by the shell (sidebar nav + topbar).
// Add more from the design source as later streams need them.

import type { CSSProperties } from 'react';

const ICON_PATHS: Record<string, string> = {
  // Sidebar / nav
  dashboard: 'M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z',
  sessions: 'M3 12a9 9 0 1 0 9-9M3 12V5M3 12h7M9 9l3 3v3',
  pages:
    'M14 3v5h5M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M9 13h6 M9 17h6',
  issues:
    'M12 9v4M12 17h.01M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0z',
  analytics: 'M3 3v18h18 M7 14l4-4 4 4 5-5',
  visualizations:
    'M5 7a2 2 0 1 0 0 4 2 2 0 0 0 0-4z M19 13a2 2 0 1 0 0 4 2 2 0 0 0 0-4z M19 5a2 2 0 1 0 0 4 2 2 0 0 0 0-4z M19 7H7 M19 15H7 M5 11v2',
  exports: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3',
  settings:
    'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z',

  // Topbar / general
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M21 21l-4.35-4.35',
  bell: 'M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9 M13.73 21a2 2 0 0 1-3.46 0',
  refresh: 'M21 12a9 9 0 1 1-3-6.7L21 8 M21 3v5h-5',
  globe:
    'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M3 12h18 M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z',
  play: 'M5 3l14 9-14 9z',
  pause: 'M6 4h4v16H6z M14 4h4v16h-4z',
  stop: 'M5 5h14v14H5z',
  more: 'M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z M19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z M5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  zap: 'M13 2 3 14h7l-1 8 10-12h-7z',
  chevDown: 'M6 9l6 6 6-6',
  chevRight: 'M9 6l6 6-6 6',
  plus: 'M12 5v14M5 12h14',
  arrowUp: 'M12 19V5 M5 12l7-7 7 7',
  external:
    'M14 3h7v7 M21 3l-9 9 M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5',

  // Tree-row glyphs (folder/file ports of .design-ref/project/icons.jsx)
  folder:
    'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h6l2 3h8a2 2 0 0 1 2 2z',
  file: 'M14 3v5h5M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z',
};

export interface IconProps {
  name: keyof typeof ICON_PATHS | string;
  size?: number;
  strokeWidth?: number;
  className?: string;
  style?: CSSProperties;
}

export default function Icon({
  name,
  size = 16,
  strokeWidth = 1.6,
  className,
  style,
}: IconProps) {
  const d = ICON_PATHS[name];
  if (!d) {
    return (
      <span
        style={{ display: 'inline-block', width: size, height: size }}
        aria-hidden="true"
      />
    );
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      className={className}
      aria-hidden="true"
    >
      {d
        .split('M')
        .filter(Boolean)
        .map((p, i) => (
          <path key={i} d={'M' + p.trim()} />
        ))}
    </svg>
  );
}
