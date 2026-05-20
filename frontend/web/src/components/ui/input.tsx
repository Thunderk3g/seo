/**
 * shadcn/ui — Input primitive. Bajaj-themed via `bg-card` /
 * `text-foreground` / `border` tokens scoped under `.bajaj-ui`.
 */
import * as React from 'react';
import { cn } from '../../lib/utils';

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        'flex h-9 w-full rounded-md border border-brand-border bg-card px-3 py-1 text-sm text-brand-text shadow-sm transition-colors placeholder:text-brand-text-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = 'Input';

export { Input };
