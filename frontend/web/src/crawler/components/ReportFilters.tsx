import Icon from './Icon';
import type { ReportFilters } from '../api';

interface Props {
  value: ReportFilters;
  onChange: (next: ReportFilters) => void;
  noiseCount?: number;
}

const INDEXED_OPTIONS = [
  { key: 'indexed',     label: 'Indexed by Google',          icon: 'check_circle' },
  { key: 'not_indexed', label: 'Not indexed by Google',      icon: 'cancel' },
  { key: 'excluded',    label: 'Excluded (4xx / redirects)', icon: 'block' },
  { key: 'unknown',     label: 'Unknown (not in GSC export)',icon: 'help_outline' },
] as const;

const SITEMAP_OPTIONS = [
  { key: '',         label: 'Any source' },
  { key: '1',        label: 'From sitemap.xml' },
  { key: '0',        label: 'Discovered via links only' },
] as const;

function parseSet(csv?: string): Set<string> {
  return new Set((csv ?? '').split(',').map((s) => s.trim()).filter(Boolean));
}

export default function ReportFiltersPanel({ value, onChange, noiseCount }: Props) {
  const indexedSet = parseSet(value.indexed);

  function toggleIndexed(k: string) {
    const next = new Set(indexedSet);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    onChange({ ...value, indexed: next.size ? Array.from(next).join(',') : undefined });
  }

  function setSitemap(k: string) {
    onChange({ ...value, from_sitemap: k || undefined });
  }

  function toggleNoise() {
    onChange({ ...value, hide_branch_404_noise: !value.hide_branch_404_noise });
  }

  function clearAll() {
    onChange({});
  }

  const hasAny =
    indexedSet.size > 0 ||
    !!value.from_sitemap ||
    !!value.hide_branch_404_noise ||
    !!value.subdomain ||
    !!value.category;

  return (
    <aside className="cc-filters" aria-label="Report filters">
      <div className="cc-filters__head">
        <Icon name="filter_list" />
        <span className="cc-filters__title">Filters</span>
        {hasAny && (
          <button
            type="button"
            className="cc-filters__clear"
            onClick={clearAll}
            aria-label="Clear all filters"
          >
            Clear
          </button>
        )}
      </div>

      <fieldset className="cc-filters__group">
        <legend>Indexing status</legend>
        {INDEXED_OPTIONS.map((opt) => (
          <label key={opt.key} className="cc-filters__check">
            <input
              type="checkbox"
              checked={indexedSet.has(opt.key)}
              onChange={() => toggleIndexed(opt.key)}
            />
            <Icon name={opt.icon} />
            <span>{opt.label}</span>
          </label>
        ))}
      </fieldset>

      <fieldset className="cc-filters__group">
        <legend>Discovery source</legend>
        {SITEMAP_OPTIONS.map((opt) => (
          <label key={opt.key || 'any'} className="cc-filters__radio">
            <input
              type="radio"
              name="from_sitemap"
              checked={(value.from_sitemap ?? '') === opt.key}
              onChange={() => setSitemap(opt.key)}
            />
            <span>{opt.label}</span>
          </label>
        ))}
      </fieldset>

      <fieldset className="cc-filters__group">
        <legend>Noise reduction</legend>
        <label className="cc-filters__check">
          <input
            type="checkbox"
            checked={!!value.hide_branch_404_noise}
            onChange={toggleNoise}
          />
          <Icon name="cleaning_services" />
          <span>
            Hide branch 404 noise
            {typeof noiseCount === 'number' && noiseCount > 0 ? (
              <em className="cc-filters__hint"> ({noiseCount.toLocaleString()})</em>
            ) : null}
          </span>
        </label>
      </fieldset>
    </aside>
  );
}
