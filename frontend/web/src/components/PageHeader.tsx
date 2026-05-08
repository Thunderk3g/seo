// PageHeader — shared title + subtitle + actions header used across list pages.
//
// Mirrors `.design-ref/project/pages.jsx:682–692` and uses the existing
// `.page-header` / `.page-title` / `.page-subtitle` / `.page-actions` styles
// in `styles/lattice.css`.

import type { ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}

export default function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}
