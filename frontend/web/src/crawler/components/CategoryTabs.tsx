import Icon from './Icon';
import { fmtNum } from '../format';
import type { CategoryMeta } from '../api';

interface Props {
  categories: CategoryMeta[];
  value: string | null; // category_key, or null for "All"
  subdomain: string; // restricts which categories appear
  onChange: (v: string | null) => void;
}

export default function CategoryTabs({ categories, value, subdomain, onChange }: Props) {
  const visible = categories.filter((c) =>
    subdomain === 'all' ? true : c.subdomain === subdomain,
  );
  if (visible.length === 0) return null;

  return (
    <div className="cc-tabs cc-tabs--category" role="tablist">
      <button
        type="button"
        role="tab"
        aria-selected={value === null}
        className={`cc-tab cc-tab--category ${value === null ? 'cc-tab--active' : ''}`}
        onClick={() => onChange(null)}
      >
        <Icon name="apps" />
        <span className="cc-tab__label">All categories</span>
      </button>
      {visible.map((c) => {
        const isActive = value === c.key;
        const ni = c.counts?.not_indexed ?? 0;
        const ok = c.counts?.indexed ?? 0;
        const total = c.counts?.crawled ?? 0;
        return (
          <button
            key={c.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`cc-tab cc-tab--category ${isActive ? 'cc-tab--active' : ''}`}
            onClick={() => onChange(c.key)}
          >
            <Icon name={c.icon} />
            <span className="cc-tab__label">{c.label}</span>
            <span className="cc-tab__badge">{fmtNum(total)}</span>
            {ni > 0 && (
              <span className="cc-tab__chip cc-tab__chip--bad" title="Not indexed">
                ✗ {fmtNum(ni)}
              </span>
            )}
            {ok > 0 && (
              <span className="cc-tab__chip cc-tab__chip--ok" title="Indexed">
                ✓ {fmtNum(ok)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
