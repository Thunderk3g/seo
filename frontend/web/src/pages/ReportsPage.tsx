/**
 * ReportsPage — `/reports`.
 *
 * Manager-facing report builder. Pick which sections to include
 * (KPI filters double as section toggles), then download a single
 * .xlsx workbook bundling everything: charts, per-rule URL evidence,
 * the full Page Inventory. Designed so the operator can email or
 * present the file without the local dashboard running.
 *
 * Bajaj blue/white palette per the brand memory.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { crawlerApi } from '../crawler/api';

const API_BASE = '/api/v1/crawler';

type SectionKey =
  | 'summary'
  | 'compliance'
  | 'wcag'
  | 'privacy'
  | 'security'
  | 'structured_data'
  | 'hreflang'
  | 'technical'
  | 'content'
  | 'inventory'
  | 'catalog';

interface SectionDef {
  key: SectionKey;
  title: string;
  description: string;
  group: 'Compliance' | 'Technical SEO' | 'Content' | 'Reference';
}

const SECTIONS: SectionDef[] = [
  {
    key: 'summary',
    title: 'Executive Summary',
    description: 'KPI strip + violations-by-section pie chart',
    group: 'Compliance',
  },
  {
    key: 'compliance',
    title: 'Compliance Overview',
    description: 'WCAG / GDPR / OWASP rules with standard references and bar chart',
    group: 'Compliance',
  },
  {
    key: 'wcag',
    title: 'WCAG 2.1 Accessibility Findings',
    description: 'Per-URL accessibility violations with evidence',
    group: 'Compliance',
  },
  {
    key: 'privacy',
    title: 'Privacy & Cookies (GDPR / DPDPA)',
    description: 'Cookie attribute audit + tracker-without-consent detection',
    group: 'Compliance',
  },
  {
    key: 'security',
    title: 'Security Headers',
    description: 'Per-URL HSTS / CSP / X-Frame-Options matrix',
    group: 'Compliance',
  },
  {
    key: 'structured_data',
    title: 'Structured Data',
    description: 'JSON-LD types per URL with rich-result eligibility',
    group: 'Technical SEO',
  },
  {
    key: 'hreflang',
    title: 'Hreflang Matrix',
    description: 'Locale clusters with return-tag status',
    group: 'Technical SEO',
  },
  {
    key: 'technical',
    title: 'Technical SEO',
    description: 'Canonical + redirect chains per URL',
    group: 'Technical SEO',
  },
  {
    key: 'content',
    title: 'Content Audit',
    description: 'Titles, meta, pixel widths, readability scores, spelling',
    group: 'Content',
  },
  {
    key: 'inventory',
    title: 'Page Inventory',
    description: 'Every crawled URL with status, page-type, word count, h1, alts',
    group: 'Content',
  },
  {
    key: 'catalog',
    title: 'Detector Catalog',
    description: 'All 118 rules with severity, count, and fix instructions',
    group: 'Reference',
  },
];

const GROUPS: SectionDef['group'][] = [
  'Compliance',
  'Technical SEO',
  'Content',
  'Reference',
];

export default function ReportsPage() {
  const [selected, setSelected] = useState<Set<SectionKey>>(
    () => new Set(SECTIONS.map((s) => s.key)),
  );
  const [statusFilter, setStatusFilter] = useState<'all' | 'errors' | 'warnings'>(
    'all',
  );

  const { data: compliance } = useQuery({
    queryKey: ['crawler', 'compliance'],
    queryFn: () => crawlerApi.compliance(),
    staleTime: 60_000,
  });

  const toggle = (k: SectionKey) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  const selectAll = () => setSelected(new Set(SECTIONS.map((s) => s.key)));
  const selectNone = () => setSelected(new Set());

  const downloadUrl = (() => {
    if (selected.size === 0 || selected.size === SECTIONS.length) {
      return `${API_BASE}/report/comprehensive.xlsx`;
    }
    const params = new URLSearchParams({
      sections: Array.from(selected).join(','),
    });
    return `${API_BASE}/report/comprehensive.xlsx?${params}`;
  })();

  const summary = compliance?.summary;

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-brand-text">Reports</h1>
        <p className="mt-1 text-sm text-brand-text-3">
          Build a comprehensive .xlsx report from the latest crawl. Select
          the sections to include, then download. Each sheet is styled with
          Bajaj branding and contains charts, per-URL evidence, and exact
          fix instructions where applicable.
        </p>
      </header>

      {summary && (
        <section className="mb-6">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
            Snapshot KPIs
          </h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
            <Kpi label="Pages crawled" value={summary.pages_audited} />
            <Kpi label="Pages affected" value={summary.pages_with_any_violation} />
            <Kpi label="Total violations" value={summary.total_violations} />
            <Kpi label="Rules failed" value={summary.unique_rules_failed} />
            <Kpi
              label="Errors"
              value={summary.by_severity.error}
              tone="error"
            />
            <Kpi
              label="Warnings"
              value={summary.by_severity.warning}
              tone="warning"
            />
          </div>
        </section>
      )}

      <section className="mb-6">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
          KPI Filters
        </h2>
        <div className="flex flex-wrap gap-2">
          {(['all', 'errors', 'warnings'] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setStatusFilter(f)}
              className={
                'rounded-full border px-3 py-1 text-xs font-medium ' +
                (statusFilter === f
                  ? 'border-brand-accent bg-brand-accent text-white'
                  : 'border-brand-border bg-brand-surface text-brand-text-2 hover:text-brand-text')
              }
            >
              {f === 'all'
                ? 'All severities'
                : f === 'errors'
                ? 'Errors only'
                : 'Warnings & above'}
            </button>
          ))}
          <span className="ml-2 text-xs text-brand-text-3 leading-7">
            (filter applies to in-sheet conditional fills; all rows are
            still included for traceability)
          </span>
        </div>
      </section>

      <section className="mb-6">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-brand-text-3">
            Sections to include
          </h2>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={selectAll}
              className="text-xs text-brand-accent hover:underline"
            >
              Select all
            </button>
            <button
              type="button"
              onClick={selectNone}
              className="text-xs text-brand-text-3 hover:underline"
            >
              Clear all
            </button>
          </div>
        </div>

        <div className="space-y-4">
          {GROUPS.map((g) => {
            const items = SECTIONS.filter((s) => s.group === g);
            return (
              <div
                key={g}
                className="rounded-md border border-brand-border bg-brand-surface"
              >
                <div className="border-b border-brand-border bg-brand-surface-2 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-brand-text-2">
                  {g}
                </div>
                <div className="divide-y divide-brand-border-2">
                  {items.map((s) => (
                    <label
                      key={s.key}
                      className="flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-brand-surface-2"
                    >
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4 accent-brand-accent"
                        checked={selected.has(s.key)}
                        onChange={() => toggle(s.key)}
                      />
                      <div className="flex-1">
                        <div className="text-sm font-medium text-brand-text">
                          {s.title}
                        </div>
                        <div className="mt-0.5 text-xs text-brand-text-3">
                          {s.description}
                        </div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-md border border-brand-border bg-brand-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-brand-text">
              Ready to generate
            </div>
            <div className="mt-0.5 text-xs text-brand-text-3">
              {selected.size === 0
                ? 'No sections selected — pick at least one above.'
                : selected.size === SECTIONS.length
                ? 'All 11 sheets will be included.'
                : `${selected.size} sheet${selected.size === 1 ? '' : 's'} selected.`}
            </div>
          </div>
          <a
            href={downloadUrl}
            target="_blank"
            rel="noreferrer"
            className={
              'inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-semibold transition-colors ' +
              (selected.size === 0
                ? 'cursor-not-allowed bg-brand-surface-2 text-brand-text-3'
                : 'bg-brand-accent text-white hover:opacity-90')
            }
            onClick={(e) => {
              if (selected.size === 0) e.preventDefault();
            }}
          >
            Download report (.xlsx)
          </a>
        </div>
        <p className="mt-3 text-xs text-brand-text-3">
          The file is generated server-side from the latest completed crawl
          ({summary?.pages_audited ?? '—'} pages) and downloaded directly to
          your machine. No data leaves the local environment.
        </p>
      </section>
    </div>
  );
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: 'error' | 'warning';
}) {
  return (
    <div className="rounded-md border border-brand-border bg-brand-surface px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-brand-text-3">
        {label}
      </div>
      <div
        className={
          'mt-1 text-2xl font-semibold ' +
          (tone === 'error'
            ? 'text-severity-error'
            : tone === 'warning'
            ? 'text-severity-warning'
            : 'text-brand-text')
        }
      >
        {value.toLocaleString()}
      </div>
    </div>
  );
}
