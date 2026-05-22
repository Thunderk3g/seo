// BrandMonitorPage — third-party brand mentions dashboard.
//
// Backend: /api/v1/seo/brand-mentions/. Surfaces every third-party
// site mentioning Bajaj, sentiment-graded, classified by source tier
// (news / forum / review / aggregator) and brand variant (new vs
// legacy "Bajaj Allianz Life"). Drives the rebrand-stickiness chart
// and the AI-search-readiness signal (since AI bots heavily weight
// third-party mentions in their citations).
//
// Sections (top to bottom):
//   1. Header + Refresh + filters (sentiment / tier / variant / search)
//   2. KPI strip (5 cells)
//   3. Sentiment trend chart (TimeSeriesChart, 90 days)
//   4. Source-tier breakdown table
//   5. Brand-variant breakdown (rebrand stickiness)
//   6. Top mentioning domains
//   7. Recent mentions feed (cards with snippet + badges + open link)

import { useMemo, useState } from 'react';
import {
  useBrandMentions,
  useRefreshBrandMentions,
  type BrandMention,
} from '../api/hooks/useBrandMentions';
import TimeSeriesChart from '../components/charts/TimeSeriesChart';

const SENTIMENT_LABEL: Record<string, string> = {
  positive: 'Positive',
  neutral: 'Neutral',
  negative: 'Negative',
  unscored: 'Unscored',
};

const TIER_LABEL: Record<string, string> = {
  news_tier_1: 'News (tier 1)',
  news_tier_2: 'News (tier 2)',
  forum: 'Forum / community',
  review: 'Review site',
  aggregator: 'Aggregator',
  regulatory: 'Regulatory',
  blog: 'Blog',
  other: 'Other',
};

const VARIANT_LABEL: Record<string, string> = {
  new: 'Bajaj Life Insurance',
  old: 'Bajaj Allianz Life (legacy)',
  parent: 'Bajaj Allianz (parent)',
  ambiguous: 'Ambiguous',
};

export default function BrandMonitorPage() {
  const [sentiment, setSentiment] = useState('');
  const [tier, setTier] = useState('');
  const [variant, setVariant] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);

  const filters = { sentiment, tier, variant, q: search, page, page_size: 50 };
  const { data, isLoading, isError, error } = useBrandMentions(filters);
  const refreshMutation = useRefreshBrandMentions();

  return (
    <div className="seo-page">
      <header className="seo-page-header">
        <div>
          <h1>Brand Mentions</h1>
          <div className="seo-page-sub">
            Third-party sites talking about Bajaj across news, forums,
            reviews, and search results. Sentiment-scored. Tracks
            rebrand stickiness (Bajaj Allianz Life → Bajaj Life Insurance)
            and AI-search-visible sources.
          </div>
        </div>
        <div className="seo-page-controls">
          <button
            className="seo-btn-primary"
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
            type="button"
          >
            {refreshMutation.isPending ? 'Refreshing…' : 'Refresh now'}
          </button>
        </div>
      </header>

      {isLoading && <div className="seo-empty">Loading brand mentions…</div>}

      {isError && (
        <div className="seo-error">
          Could not reach the brand-mentions backend.
          {error instanceof Error ? ` ${error.message}` : ''}
        </div>
      )}

      {refreshMutation.isError && (
        <div className="seo-error">
          Refresh failed.{' '}
          {refreshMutation.error instanceof Error
            ? refreshMutation.error.message
            : ''}
        </div>
      )}

      {refreshMutation.data && refreshMutation.data.ok && (
        <div className="seo-info">
          Pulled {refreshMutation.data.total_fetched} items —{' '}
          {refreshMutation.data.total_new} new,{' '}
          {refreshMutation.data.total_updated} updated,{' '}
          {refreshMutation.data.sentiment_scored} sentiment-scored.
        </div>
      )}

      {data && data.empty && (
        <div className="seo-empty">
          {data.message ||
            'No brand mentions captured yet. Click "Refresh now" to pull the first batch.'}
        </div>
      )}

      {data && !data.empty && (
        <>
          {/* KPI strip */}
          <div className="seo-card seo-perf-card">
            <div className="seo-card-head">
              <h2>Window summary</h2>
              <span className="seo-card-sub">
                All-time captured · {data.totals?.last_week ?? 0} new in last 7
                days
              </span>
            </div>
            <div className="seo-perf-totals">
              <Kpi
                label="Total mentions"
                value={data.totals?.total?.toLocaleString() ?? '—'}
              />
              <Kpi
                label="New (7d)"
                value={data.totals?.last_week?.toLocaleString() ?? '—'}
              />
              <Kpi
                label="Positive"
                value={`${data.totals?.pct_positive ?? 0}%`}
              />
              <Kpi
                label="Negative"
                value={`${data.totals?.pct_negative ?? 0}%`}
              />
              <Kpi
                label="Old-brand variant"
                value={`${data.totals?.pct_old_brand ?? 0}%`}
              />
              <Kpi
                label="AI-bot-visible sources"
                value={`${data.totals?.pct_ai_visible_sources ?? 0}%`}
              />
            </div>
          </div>

          {/* Sentiment trend */}
          <div className="seo-card">
            <div className="seo-card-head">
              <h2>Sentiment trend</h2>
              <span className="seo-card-sub">
                Last 90 days · daily bucket
              </span>
            </div>
            {(data.sentiment_trend?.length ?? 0) < 2 ? (
              <div className="seo-empty">
                Not enough data points yet for a trend. Run more pulls to
                build history.
              </div>
            ) : (
              <TimeSeriesChart
                data={(data.sentiment_trend ?? []).map((p) => ({
                  date: p.date,
                  Positive: p.positive,
                  Neutral: p.neutral,
                  Negative: p.negative,
                }))}
                series={[
                  { key: 'Positive', label: 'Positive', color: '#21a884' },
                  { key: 'Neutral', label: 'Neutral', color: 'var(--accent)' },
                  { key: 'Negative', label: 'Negative', color: '#c4392e' },
                ]}
                height={220}
              />
            )}
          </div>

          {/* Tier + variant breakdown — side by side */}
          <div className="seo-cards-row">
            <div className="seo-card">
              <div className="seo-card-head">
                <h2>Source tier</h2>
                <span className="seo-card-sub">
                  Where the mentions come from
                </span>
              </div>
              <BreakdownTable
                rows={data.tier_breakdown ?? []}
                labelKey="tier"
                labelMap={TIER_LABEL}
                onClick={(t) => {
                  setTier(t === tier ? '' : t);
                  setPage(0);
                }}
                activeKey={tier}
              />
            </div>
            <div className="seo-card">
              <div className="seo-card-head">
                <h2>Brand variant</h2>
                <span className="seo-card-sub">
                  Rebrand stickiness — old vs new name share
                </span>
              </div>
              <BreakdownTable
                rows={data.variant_breakdown ?? []}
                labelKey="variant"
                labelMap={VARIANT_LABEL}
                onClick={(v) => {
                  setVariant(v === variant ? '' : v);
                  setPage(0);
                }}
                activeKey={variant}
              />
            </div>
          </div>

          {/* Top domains */}
          <div className="seo-card">
            <div className="seo-card-head">
              <h2>Top mentioning domains</h2>
              <span className="seo-card-sub">
                Click any domain to filter the feed below
              </span>
            </div>
            <table className="seo-table seo-table-compact">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Domain</th>
                  <th style={{ textAlign: 'right' }}>Mentions</th>
                </tr>
              </thead>
              <tbody>
                {(data.top_domains ?? []).map((row, i) => (
                  <tr
                    key={row.source_domain}
                    onClick={() => {
                      setSearch(row.source_domain);
                      setPage(0);
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    <td className="seo-num">{i + 1}</td>
                    <td>{row.source_domain || '—'}</td>
                    <td className="seo-num">{row.count.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Filters + feed */}
          <div className="seo-card">
            <div className="seo-card-head" style={{ flexWrap: 'wrap', gap: 12 }}>
              <h2 style={{ flex: '1 0 200px' }}>Recent mentions</h2>
              <input
                type="search"
                className="seo-input"
                placeholder="Search title / snippet / domain"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(0);
                }}
                style={{ minWidth: 240 }}
              />
              <select
                className="seo-input"
                value={sentiment}
                onChange={(e) => {
                  setSentiment(e.target.value);
                  setPage(0);
                }}
              >
                <option value="">All sentiment</option>
                <option value="positive">Positive</option>
                <option value="neutral">Neutral</option>
                <option value="negative">Negative</option>
                <option value="unscored">Unscored</option>
              </select>
              <select
                className="seo-input"
                value={variant}
                onChange={(e) => {
                  setVariant(e.target.value);
                  setPage(0);
                }}
              >
                <option value="">All brand variants</option>
                {Object.entries(VARIANT_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
              <select
                className="seo-input"
                value={tier}
                onChange={(e) => {
                  setTier(e.target.value);
                  setPage(0);
                }}
              >
                <option value="">All source tiers</option>
                {Object.entries(TIER_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            {!data.mentions || data.mentions.length === 0 ? (
              <div className="seo-empty">No mentions match the filter.</div>
            ) : (
              <MentionsFeed mentions={data.mentions} />
            )}

            {(data.feed_total ?? 0) > (data.page_size ?? 50) && (
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginTop: 12,
                  fontSize: 12,
                  color: 'var(--text-3)',
                }}
              >
                <span>
                  Page {(data.page ?? 0) + 1} of{' '}
                  {Math.ceil((data.feed_total ?? 0) / (data.page_size ?? 50))} ·
                  Total {data.feed_total} matching
                </span>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    type="button"
                    className="seo-btn-outline"
                    disabled={(data.page ?? 0) <= 0}
                    onClick={() => setPage(Math.max(0, (data.page ?? 0) - 1))}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    className="seo-btn-outline"
                    onClick={() => setPage((data.page ?? 0) + 1)}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── components ────────────────────────────────────────────────────────

function Kpi({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="seo-kpi">
      <div className="seo-kpi-label">{label}</div>
      <div className="seo-kpi-value">{value}</div>
    </div>
  );
}

function BreakdownTable({
  rows,
  labelKey,
  labelMap,
  onClick,
  activeKey,
}: {
  rows: Array<Record<string, any>>;
  labelKey: string;
  labelMap: Record<string, string>;
  onClick?: (k: string) => void;
  activeKey?: string;
}) {
  const total = useMemo(
    () => rows.reduce((s, r) => s + (r.count || 0), 0) || 1,
    [rows],
  );
  return (
    <table className="seo-table seo-table-compact">
      <thead>
        <tr>
          <th>Label</th>
          <th style={{ textAlign: 'right' }}>Count</th>
          <th style={{ textAlign: 'right' }}>Share</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const k = row[labelKey] as string;
          const c = row.count as number;
          const isActive = activeKey === k;
          return (
            <tr
              key={k}
              onClick={onClick ? () => onClick(k) : undefined}
              style={{
                cursor: onClick ? 'pointer' : 'default',
                background: isActive ? 'var(--accent-soft)' : undefined,
              }}
            >
              <td>{labelMap[k] || k}</td>
              <td className="seo-num">{c.toLocaleString()}</td>
              <td className="seo-num">
                {((c / total) * 100).toFixed(1)}%
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function MentionsFeed({ mentions }: { mentions: BrandMention[] }) {
  return (
    <div className="seo-mention-feed">
      {mentions.map((m) => (
        <MentionCard key={m.id} m={m} />
      ))}
    </div>
  );
}

function MentionCard({ m }: { m: BrandMention }) {
  const date = m.published_at || m.last_seen_at;
  const dateLabel = date
    ? new Date(date).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
    : '';
  // Prefer the deep body_excerpt over the SERP snippet when available.
  const excerpt = m.body_excerpt || m.snippet || '';
  return (
    <a
      href={m.source_url}
      target="_blank"
      rel="noreferrer"
      className="seo-mention-card"
    >
      <div className="seo-mention-head">
        <span className="seo-mention-domain">{m.source_domain || '—'}</span>
        <SentimentBadge sentiment={m.sentiment} />
        <VariantBadge variant={m.brand_variant} />
        <TierBadge tier={m.source_tier} />
        {m.is_linked && (
          <span className="seo-badge seo-badge-ok" title="Contains an HTML link to bajajlifeinsurance.com">
            Linked
          </span>
        )}
        {m.language && m.language !== 'en' && (
          <span className="seo-badge seo-badge-neutral" title="Page language">
            {m.language.toUpperCase()}
          </span>
        )}
        {m.rating_value !== null && m.rating_value !== undefined && (
          <span className="seo-badge seo-badge-warn">
            ★ {m.rating_value}
            {m.rating_max ? ` / ${m.rating_max}` : ''}
          </span>
        )}
      </div>

      <div className="seo-mention-title">
        {m.source_title || '(no title)'}
      </div>

      {excerpt && <div className="seo-mention-snippet">{excerpt}</div>}

      {(m.author || m.publisher) && (
        <div className="seo-mention-byline">
          {m.publisher && <span>{m.publisher}</span>}
          {m.publisher && m.author && <span> · </span>}
          {m.author && <span>by {m.author}</span>}
        </div>
      )}

      {m.is_linked && m.anchor_texts.length > 0 && (
        <div className="seo-mention-anchors">
          <span className="seo-mention-anchors-label">Anchor:</span>
          {m.anchor_texts.slice(0, 3).map((a, i) => (
            <span key={i} className="seo-mention-anchor">
              &ldquo;{a}&rdquo;
            </span>
          ))}
          {m.anchor_texts.length > 3 && (
            <span className="seo-mention-anchor seo-mention-anchor-more">
              +{m.anchor_texts.length - 3} more
            </span>
          )}
        </div>
      )}

      {m.co_mentioned_brands.length > 0 && (
        <div className="seo-mention-comentions">
          <span className="seo-mention-comentions-label">
            Mentioned alongside:
          </span>
          {m.co_mentioned_brands.map((b) => (
            <span key={b} className="seo-badge">
              {b}
            </span>
          ))}
        </div>
      )}

      <div className="seo-mention-foot">
        <span>{dateLabel}</span>
        <span>via {m.discovered_via}{m.page_fetched ? ' + page-fetch' : ''}</span>
      </div>
    </a>
  );
}

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const cls =
    sentiment === 'positive'
      ? 'seo-badge seo-badge-ok'
      : sentiment === 'negative'
      ? 'seo-badge seo-badge-err'
      : sentiment === 'neutral'
      ? 'seo-badge seo-badge-neutral'
      : 'seo-badge';
  return <span className={cls}>{SENTIMENT_LABEL[sentiment] || sentiment}</span>;
}

function VariantBadge({ variant }: { variant: string }) {
  const cls =
    variant === 'old'
      ? 'seo-badge seo-badge-warn'
      : variant === 'new'
      ? 'seo-badge seo-badge-ok'
      : 'seo-badge';
  return <span className={cls}>{VARIANT_LABEL[variant] || variant}</span>;
}

function TierBadge({ tier }: { tier: string }) {
  return <span className="seo-badge">{TIER_LABEL[tier] || tier}</span>;
}
