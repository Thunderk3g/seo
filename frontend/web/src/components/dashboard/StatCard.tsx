// StatCard — single KPI tile for the dashboard's `.stat-row`.
//
// Mirrors `.design-ref/project/dashboard.jsx` StatCard (lines 3-18). The
// component used to live inline in DashboardPage; extracted here so the
// 4-row layout file stays a thin composer of cards.
//
// `sparkData` is optional. When non-empty it renders a <Sparkline> next to
// the value; otherwise the Sparkline component itself returns an empty SVG
// of the same dimensions, keeping the layout stable.

import type { ReactNode } from 'react';
import Sparkline from '../charts/Sparkline';

export interface StatCardProps {
  label: string;
  value: number | string;
  color: string;
  sub: ReactNode;
  sparkData?: number[];
  sparkColor?: string;
  dim?: boolean;
}

export default function StatCard({
  label,
  value,
  color,
  sub,
  sparkData,
  sparkColor,
  dim,
}: StatCardProps) {
  return (
    <div className="card stat-card">
      <div className="stat-head">
        <div className="stat-dot" style={{ background: color }} />
        <span className="stat-label">{label}</span>
      </div>
      <div className="stat-value-row">
        <div className="stat-value">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </div>
        <Sparkline
          data={sparkData ?? []}
          width={110}
          height={36}
          color={sparkColor || color}
          fill
        />
      </div>
      <div className={'stat-sub ' + (dim ? 'dim' : '')}>{sub}</div>
    </div>
  );
}
