import type { ButtonHTMLAttributes, ReactNode } from 'react';
import Icon from './Icon';

type Variant = 'primary' | 'accent' | 'danger' | 'ghost';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  icon?: string;
  children?: ReactNode;
}

export default function Button({ variant = 'primary', icon, children, ...rest }: ButtonProps) {
  return (
    <button className={`btn btn-${variant}`} {...rest}>
      {icon && <Icon name={icon} />}
      {children}
    </button>
  );
}
