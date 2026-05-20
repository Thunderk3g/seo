/**
 * shadcn/ui — Badge primitive.
 *
 * Bajaj severity tier built in: `variant="error" | "warning" | "notice"
 * | "success"` maps to the same colour tokens used elsewhere in the app.
 */
import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'text-brand-text border-brand-border',
        error: 'border-transparent bg-severity-error-soft text-severity-error',
        warning: 'border-transparent bg-severity-warning-soft text-severity-warning',
        notice: 'border-transparent bg-brand-accent-soft text-severity-notice',
        success: 'border-transparent bg-severity-success-soft text-severity-success',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps): React.JSX.Element {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
