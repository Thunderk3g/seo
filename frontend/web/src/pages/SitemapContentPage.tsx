// SitemapContentPage — content inventory pulled from AEM sitemap JSON.
//
// Backed by `/api/v1/seo/sitemap/`, which reads the AEM page-model
// exports in `backend/data/aem/`. Each row is a public page with the
// authored title, description, template, last-modified time, and a
// component count. The rollup section surfaces SEO hygiene problems
// authoring teams care about: missing descriptions, titles outside
// 30–60 chars, descriptions outside 70–160 chars.

import { useMemo, useState } from 'react';
import { useSitemapDashboard } from '../api/hooks/useSitemapDashboard';
import type { SitemapDashboard, SitemapPageRow } from '../api/seoTypes';

const PAGE_SIZE = 25;
type TitleFilter = 'all' | 'short' | 'long' | 'missing';
type DescFilter = 'all' | 'short' | 'long' | 'missing';

export default function SitemapContentPage() {
  const { data, isLoading, isError } = useSitemapDashboard();

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Content via Sitemap</h1>
          <div className="seo-page-sub">
            Every public page exported from AEM, with authoring metadata
            and SEO hygiene flags.
          </div>
        </div>
      </header>

      {isLoading && <div className="seo-empty">Loading sitemap…</div>}
      {isError && (
        <div className="seo-error">
          Could not reach the SEO backend. Make sure the Django server is
          running on /api/v1/seo/.
        </div>
      )}

      {data && !data.available && (
        <div className="seo-empty">
          No AEM sitemap data on disk.{' '}
          {data.error ? <span>({data.error})</span> : null} Drop AEM JSON
          exports into <b>backend/data/aem/</b> to populate.
        </div>
      )}

      {data && data.available && <SitemapBody data={data} />}
    </div>
  );
}

function SitemapBody({ data }: { data: SitemapDashboard }) {
  const t = data.totals!;
  const pages = data.pages ?? [];

  return (
    <>
      <div className="seo-card seo-perf-card">
        <div className="seo-card-head">
          <h2>Content rollup</h2>
          <span className="seo-card-sub">
            Authored in AEM · {(data.distinct_templates ?? []).length} templates
          </span>
        </div>
        <div className="seo-perf-totals">
          <Kpi label="Total pages" value={t.pages.toLocaleString()} />
          <Kpi
            label="With description"
            value={`${t.with_description.toLocaleString()} (${pct(
              t.with_description,
              t.pages,
            )}%)`}
          />
          <Kpi
            label="Missing description"
            value={t.without_description.toLocaleString()}
          />
          <Kpi label="Short title (<30)" value={t.short_title.toLocaleString()} />
          <Kpi label="Long title (>60)" value={t.long_title.toLocaleString()} />
          <Kpi label="Short desc (<70)" value={t.short_desc.toLocaleString()} />
          <Kpi label="Long desc (>160)" value={t.long_desc.toLocaleString()} />
        </div>
      </div>

      <div className="seo-row-2-balanced">
        <TemplateCard templates={data.distinct_templates ?? []} pages={pages} />
        <ComponentUsageCard usage={data.component_usage ?? {}} />
      </div>

      <PagesTable pages={pages} />
    </>
  );
}

function PagesTable({ pages }: { pages: SitemapPageRow[] }) {
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState('');
  const [titleFilter, setTitleFilter] = useState<TitleFilter>('all');
  const [descFilter, setDescFilter] = useState<DescFilter>('all');
  const [templateFilter, setTemplateFilter] = useState<string>('all');

  const templates = useMemo(() => {
    const set = new Set<string>();
    for (const p of pages) if (p.template_name) set.add(p.template_name);
    return Array.from(set).sort();
  }, [pages]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return pages.filter((p) => {
      if (q) {
        const hay = `${p.title} ${p.public_url} ${p.description}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (titleFilter === 'short' && !(p.title_length > 0 && p.title_length < 30))
        return false;
      if (titleFilter === 'long' && p.title_length <= 60) return false;
      if (titleFilter === 'missing' && p.title_length > 0) return false;
      if (descFilter === 'short' && !(p.description_length > 0 && p.description_length < 70))
        return false;
      if (descFilter === 'long' && p.description_length <= 160) return false;
      if (descFilter === 'missing' && p.description_length > 0) return false;
      if (templateFilter !== 'all' && p.template_name !== templateFilter)
        return false;
      return true;
    });
  }, [pages, filter, titleFilter, descFilter, templateFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const slice = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Pages</h2>
        <span className="seo-card-sub">
          {filtered.length.toLocaleString()} of {pages.length.toLocaleString()}{' '}
          pages
        </span>
      </div>
      <div className="seo-toolbar">
        <input
          type="search"
          className="seo-input"
          placeholder="Filter by title, URL or description…"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setPage(0);
          }}
        />
        <select
          className="seo-input"
          value={titleFilter}
          onChange={(e) => {
            setTitleFilter(e.target.value as TitleFilter);
            setPage(0);
          }}
        >
          <option value="all">All titles</option>
          <option value="missing">Missing title</option>
          <option value="short">Short title (&lt;30)</option>
          <option value="long">Long title (&gt;60)</option>
        </select>
        <select
          className="seo-input"
          value={descFilter}
          onChange={(e) => {
            setDescFilter(e.target.value as DescFilter);
            setPage(0);
          }}
        >
          <option value="all">All descriptions</option>
          <option value="missing">Missing description</option>
          <option value="short">Short desc (&lt;70)</option>
          <option value="long">Long desc (&gt;160)</option>
        </select>
        <select
          className="seo-input"
          value={templateFilter}
          onChange={(e) => {
            setTemplateFilter(e.target.value);
            setPage(0);
          }}
        >
          <option value="all">All templates</option>
          {templates.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <div className="seo-empty">No pages match the current filters.</div>
      ) : (
        <>
          <table className="seo-table">
            <thead>
              <tr>
                <th>Page</th>
                <th>Title</th>
                <th className="num">Title len</th>
                <th className="num">Desc len</th>
                <th>Template</th>
                <th className="num">Comp.</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((p) => (
                <tr key={p.aem_path}>
                  <td className="seo-cell-query" title={p.public_url}>
                    <a href={p.public_url} target="_blank" rel="noreferrer">
                      {shortPath(p.public_url)}
                    </a>
                  </td>
                  <td className="seo-cell-query" title={p.title}>
                    {p.title || <span className="seo-mover-down">—</span>}
                  </td>
                  <td className={`num ${lengthClass(p.title_length, 30, 60)}`}>
                    {p.title_length}
                  </td>
                  <td className={`num ${lengthClass(p.description_length, 70, 160)}`}>
                    {p.description_length}
                  </td>
                  <td>{p.template_name || '—'}</td>
                  <td className="num">{p.component_count}</td>
                  <td>{formatDate(p.last_modified)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalPages > 1 && (
            <div className="seo-pager">
              <button
                className="seo-btn seo-btn-ghost"
                onClick={() => setPage(Math.max(0, safePage - 1))}
                disabled={safePage === 0}
              >
                ‹ Prev
              </button>
              <span className="seo-pager-meta">
                Page {safePage + 1} of {totalPages}
              </span>
              <button
                className="seo-btn seo-btn-ghost"
                onClick={() => setPage(Math.min(totalPages - 1, safePage + 1))}
                disabled={safePage >= totalPages - 1}
              >
                Next ›
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TemplateCard({
  templates,
  pages,
}: {
  templates: string[];
  pages: SitemapPageRow[];
}) {
  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const p of pages) {
      const k = p.template_name || '—';
      map[k] = (map[k] || 0) + 1;
    }
    return Object.entries(map).sort((a, b) => b[1] - a[1]);
  }, [pages]);
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Templates</h2>
        <span className="seo-card-sub">
          {templates.length} distinct · pages per template
        </span>
      </div>
      {counts.length === 0 ? (
        <div className="seo-empty">No template data.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Template</th>
              <th className="num">Pages</th>
            </tr>
          </thead>
          <tbody>
            {counts.map(([name, count]) => (
              <tr key={name}>
                <td>{name}</td>
                <td className="num">{count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ComponentUsageCard({ usage }: { usage: Record<string, number> }) {
  const rows = Object.entries(usage).sort((a, b) => b[1] - a[1]);
  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>Component usage</h2>
        <span className="seo-card-sub">top components across the site</span>
      </div>
      {rows.length === 0 ? (
        <div className="seo-empty">No component data.</div>
      ) : (
        <table className="seo-table">
          <thead>
            <tr>
              <th>Component</th>
              <th className="num">Uses</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, count]) => (
              <tr key={name}>
                <td>{name}</td>
                <td className="num">{count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="seo-perf-total">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
    </div>
  );
}

function pct(n: number, total: number): string {
  if (!total) return '0';
  return ((n / total) * 100).toFixed(0);
}

function lengthClass(len: number, lo: number, hi: number): string {
  if (len === 0) return 'seo-mover-down';
  if (len < lo) return 'seo-mover-warn';
  if (len > hi) return 'seo-mover-warn';
  return 'seo-mover-ok';
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toISOString().slice(0, 10);
}

function shortPath(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname || '/';
  } catch {
    return url;
  }
}
