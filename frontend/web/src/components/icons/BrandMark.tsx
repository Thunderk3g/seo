// BrandMark.tsx — Lattice brand mark, ported verbatim from
// .design-ref/project/icons.jsx (function BrandMark).

export interface BrandMarkProps {
  size?: number;
  color?: string;
}

export default function BrandMark({
  size = 22,
  color = 'currentColor',
}: BrandMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="none"
      aria-hidden="true"
    >
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
