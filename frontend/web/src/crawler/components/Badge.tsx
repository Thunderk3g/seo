import type { ReactNode } from 'react';
import type { BadgeTone } from '../format';

export default function Badge({ tone = 'muted', children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
