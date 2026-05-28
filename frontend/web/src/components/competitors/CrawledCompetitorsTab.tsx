// "Crawled Competitors" tab — surfaces the Phase G Scrapy walk output.
//
// Reads /api/v1/seo/competitor/crawls/ which returns every domain we've
// ever crawled (latest complete snapshot per domain) with page counts +
// change-event totals, plus a denormalized `parent_domain` so we can
// roll subdomains up under their brand.
//
// UX: parent-brand rows by default; click the ▸ to expand and see the
// subdomains underneath (e.g. `hdfclife.com` parent expands to show
// `auth.hdfclife.com`, `insta.hdfclife.com`, …). Each subdomain row
// still routes to `/competitors/<subdomain>/` — the parent row routes
// to `/competitors/<parent>/` when there's a parent-domain snapshot.

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'wouter';
import { api } from '../../api/client';
import { useCompetitorCrawls } from '../../api/hooks/useCompetitorCrawls';
import type { CompetitorCrawlRow } from '../../api/hooks/useCompetitorCrawls';

function formatRelative(iso: string | null): string {
  if (!iso) return '—';
  try {
    const ts = new Date(iso).getTime();
    const ageSec = Math.max(0, Math.round((Date.now() - ts) / 1000));
    if (ageSec < 60) return `${ageSec}s ago`;
    if (ageSec < 3600) return `${Math.round(ageSec / 60)}m ago`;
    if (ageSec < 86400) return `${Math.round(ageSec / 3600)}h ago`;
    return `${Math.round(ageSec / 86400)}d ago`;
  } catch {
    return iso;
  }
}

interface BrandGroup {
  parent: string;
  rows: CompetitorCrawlRow[];
  totals: {
    pages_in_db: number;
    pages_ok: number;
    pages_attempted: number;
    change_events: number;
    last_started_at: string | null;
  };
}

function groupByBrand(rows: CompetitorCrawlRow[]): BrandGroup[] {
  const buckets = new Map<string, CompetitorCrawlRow[]>();
  for (const r of rows) {
    const key = r.parent_domain || r.domain;
    const list = buckets.get(key) || [];
    list.push(r);
    buckets.set(key, list);
  }
  const groups: BrandGroup[] = [];
  for (const [parent, items] of buckets) {
    let pages_in_db = 0;
    let pages_ok = 0;
    let pages_attempted = 0;
    let change_events = 0;
    let last_ts = 0;
    let last_started_at: string | null = null;
    for (const r of items) {
      pages_in_db += r.pages_in_db;
      pages_ok += r.pages_ok;
      pages_attempted += r.pages_attempted;
      change_events += r.change_events;
      const ts = r.started_at ? Date.parse(r.started_at) : 0;
      if (ts > last_ts) {
        last_ts = ts;
        last_started_at = r.started_at;
      }
    }
    // Subdomains sorted so the apex itself comes first when present.
    items.sort((a, b) => {
      if (a.domain === parent && b.domain !== parent) return -1;
      if (b.domain === parent && a.domain !== parent) return 1;
      return a.domain.localeCompare(b.domain);
    });
    groups.push({
      parent,
      rows: items,
      totals: {
        pages_in_db,
        pages_ok,
        pages_attempted,
        change_events,
        last_started_at,
      },
    });
  }
  // Brands sorted by freshness, tiebreak by parent name.
  groups.sort((a, b) => {
    const aTs = a.totals.last_started_at ? Date.parse(a.totals.last_started_at) : 0;
    const bTs = b.totals.last_started_at ? Date.parse(b.totals.last_started_at) : 0;
    if (aTs !== bTs) return bTs - aTs;
    return a.parent.localeCompare(b.parent);
  });
  return groups;
}

function okRatio(ok: number, attempted: number): string {
  if (attempted <= 0) return '';
  return ` (${Math.round((ok / attempted) * 100)}%)`;
}

function SubRow({ c, isApex }: { c: CompetitorCrawlRow; isApex: boolean }) {
  return (
    <tr style={{ background: 'var(--bg-2, transparent)' }}>
      <td className="seo-cell-query" style={{ paddingLeft: 36 }}>
        <Link
          href={`/competitors/${encodeURIComponent(c.domain)}`}
          style={{
            color: 'var(--text-2)',
            textDecoration: 'none',
            fontWeight: isApex ? 500 : 400,
            fontSize: 13,
          }}
        >
          {c.domain}
        </Link>
      </td>
      <td className="num" style={{ fontSize: 13 }}>
        {c.pages_in_db.toLocaleString()}
      </td>
      <td className="num" style={{ fontSize: 13 }}>
        {c.pages_ok}/{c.pages_attempted}
        {c.pages_attempted > 0 && (
          <span style={{ color: 'var(--text-3)', marginLeft: 6 }}>
            {okRatio(c.pages_ok, c.pages_attempted)}
          </span>
        )}
      </td>
      <td className="num" style={{ fontSize: 13 }}>
        {c.change_events.toLocaleString()}
      </td>
      <td style={{ color: 'var(--text-3)', fontSize: 12 }}>
        {formatRelative(c.started_at)}
      </td>
    </tr>
  );
}

function BrandRow({
  group,
  expanded,
  onToggle,
}: {
  group: BrandGroup;
  expanded: boolean;
  onToggle: () => void;
}) {
  const apexRow = group.rows.find((r) => r.domain === group.parent);
  const target = apexRow?.domain || group.parent;
  return (
    <>
      <tr>
        <td className="seo-cell-query">
          <button
            type="button"
            onClick={onToggle}
            disabled={group.rows.length <= 1}
            style={{
              background: 'transparent',
              border: 'none',
              cursor: group.rows.length > 1 ? 'pointer' : 'default',
              padding: 0,
              marginRight: 6,
              fontSize: 12,
              color: 'var(--text-3)',
              width: 12,
              textAlign: 'left',
            }}
            aria-label={expanded ? 'Collapse subdomains' : 'Expand subdomains'}
          >
            {group.rows.length > 1 ? (expanded ? '▾' : '▸') : ' '}
          </button>
          <Link
            href={`/competitors/${encodeURIComponent(target)}`}
            style={{
              color: 'var(--accent)',
              textDecoration: 'none',
              fontWeight: 600,
            }}
          >
            {group.parent}
          </Link>
          {group.rows.length > 1 && (
            <span
              style={{
                marginLeft: 8,
                color: 'var(--text-3)',
                fontSize: 11,
              }}
            >
              {group.rows.length} subdomain
              {group.rows.length === 1 ? '' : 's'}
            </span>
          )}
        </td>
        <td className="num">
          {group.totals.pages_in_db.toLocaleString()}
        </td>
        <td className="num">
          {group.totals.pages_ok}/{group.totals.pages_attempted}
          {group.totals.pages_attempted > 0 && (
            <span style={{ color: 'var(--text-3)', marginLeft: 6 }}>
              {okRatio(group.totals.pages_ok, group.totals.pages_attempted)}
            </span>
          )}
        </td>
        <td className="num">{group.totals.change_events.toLocaleString()}</td>
        <td style={{ color: 'var(--text-2)', fontSize: 12 }}>
          {formatRelative(group.totals.last_started_at)}
        </td>
      </tr>
      {expanded &&
        group.rows.map((r) => (
          <SubRow key={r.snapshot_id} c={r} isApex={r.domain === group.parent} />
        ))}
    </>
  );
}

interface PauseState {
  paused: boolean;
  updated_at: string | null;
}

function WalkPauseToggle() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['competitor-walk-pause'],
    queryFn: () => api.get<PauseState>('/seo/competitor/walk/pause/'),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const mut = useMutation({
    mutationFn: (paused: boolean) =>
      api.post<PauseState>('/seo/competitor/walk/pause/', { paused }),
    onSuccess: (resp) => {
      qc.setQueryData(['competitor-walk-pause'], resp);
    },
  });
  const paused = data?.paused ?? false;
  const busy = isLoading || mut.isPending;
  return (
    <button
      type="button"
      onClick={() => mut.mutate(!paused)}
      disabled={busy}
      title={
        paused
          ? 'Competitor walk cron is paused — click to resume nightly runs'
          : 'Pause the 03:00 IST competitor walk cron until further notice'
      }
      style={{
        padding: '6px 12px',
        fontSize: 12,
        fontWeight: 600,
        background: paused ? '#FEF3C7' : '#FFFFFF',
        color: paused ? '#92400E' : 'var(--text, #111827)',
        border: `1px solid ${paused ? '#F59E0B' : 'var(--border, #D1D5DB)'}`,
        borderRadius: 6,
        cursor: busy ? 'progress' : 'pointer',
        whiteSpace: 'nowrap',
      }}
    >
      {busy
        ? 'Saving…'
        : paused
          ? '⏸ Walk paused — resume'
          : 'Pause competitor walk'}
    </button>
  );
}

export default function CrawledCompetitorsTab() {
  const { data, isLoading, isError, error } = useCompetitorCrawls();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const groups = useMemo(
    () => groupByBrand(data?.competitors || []),
    [data?.competitors],
  );

  if (isLoading) {
    return <div className="seo-empty">Loading crawled-competitors list…</div>;
  }
  if (isError) {
    return (
      <div className="seo-error">
        Failed to load crawled competitors:{' '}
        {error instanceof Error ? error.message : 'unknown error'}
      </div>
    );
  }
  if (groups.length === 0) {
    return (
      <div className="seo-empty">
        No competitor crawls yet. The daily Scrapy walk runs at 03:00 IST
        — or trigger one manually with{' '}
        <code>python manage.py crawl_competitor &lt;domain&gt;</code>.
      </div>
    );
  }

  const toggle = (parent: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(parent) ? next.delete(parent) : next.add(parent);
      return next;
    });
  };

  return (
    <div className="seo-card">
      <div className="seo-card-head">
        <h2>
          Crawled competitors ({groups.length} brands · {data?.count ?? 0} domains)
        </h2>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <span className="seo-card-sub" style={{ flex: 1 }}>
            Brands the Phase G Scrapy walk has visited. Subdomains roll up
            under their parent — click ▸ to expand. Polls every 30 s so an
            overnight run lights up rows as they finish.
          </span>
          <WalkPauseToggle />
        </div>
      </div>
      <table className="seo-table">
        <thead>
          <tr>
            <th>Domain / Brand</th>
            <th className="num">Pages in DB</th>
            <th className="num">OK / attempted</th>
            <th className="num">Change events</th>
            <th>Last crawl</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <BrandRow
              key={g.parent}
              group={g}
              expanded={expanded.has(g.parent)}
              onToggle={() => toggle(g.parent)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
