import Icon from './Icon';
import { fmtNum } from '../format';
import type { CategoryCounts } from '../api';

type SubKey = 'all' | 'www' | 'branch' | 'investmentcorner';

interface Props {
  value: SubKey;
  onChange: (v: SubKey) => void;
  bySubdomain?: Record<string, CategoryCounts>;
}

const TABS: { key: SubKey; label: string; icon: string; sub: string }[] = [
  { key: 'all',              label: 'All surfaces',     icon: 'public',         sub: '*' },
  { key: 'www',              label: 'Main site (www)',  icon: 'language',       sub: 'www' },
  { key: 'branch',           label: 'Branch locator',   icon: 'store',          sub: 'branch' },
  { key: 'investmentcorner', label: 'Investment Corner',icon: 'article',        sub: 'investmentcorner' },
];

export default function SubdomainTabs({ value, onChange, bySubdomain }: Props) {
  return (
    <div className="cc-tabs cc-tabs--subdomain" role="tablist">
      {TABS.map((t) => {
        const counts = t.sub === '*'
          ? sumAll(bySubdomain)
          : bySubdomain?.[t.sub];
        const isActive = value === t.key;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`cc-tab ${isActive ? 'cc-tab--active' : ''}`}
            onClick={() => onChange(t.key)}
          >
            <Icon name={t.icon} />
            <span className="cc-tab__label">{t.label}</span>
            {counts ? (
              <span className="cc-tab__badge">{fmtNum(counts.crawled ?? 0)}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function sumAll(by?: Record<string, CategoryCounts>): CategoryCounts | undefined {
  if (!by) return undefined;
  const out: CategoryCounts = { crawled: 0, ok: 0, errors: 0, indexed: 0, not_indexed: 0 };
  for (const v of Object.values(by)) {
    out.crawled = (out.crawled ?? 0) + (v.crawled ?? 0);
    out.ok = (out.ok ?? 0) + (v.ok ?? 0);
    out.errors = (out.errors ?? 0) + (v.errors ?? 0);
    out.indexed = (out.indexed ?? 0) + (v.indexed ?? 0);
    out.not_indexed = (out.not_indexed ?? 0) + (v.not_indexed ?? 0);
  }
  return out;
}
