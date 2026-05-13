import type { CSSProperties, HTMLAttributes } from 'react';

interface IconProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'color'> {
  name: string;
  size?: number | string;
  color?: string;
}

// Material Icons (outlined) glyph. The font is loaded in index.html.
export default function Icon({ name, size, color, style, ...rest }: IconProps) {
  const s: CSSProperties = {
    ...(size ? { fontSize: size } : {}),
    ...(color ? { color } : {}),
    ...(style || {}),
  };
  return (
    <span className="material-icons-outlined" style={s} {...rest}>
      {name}
    </span>
  );
}
