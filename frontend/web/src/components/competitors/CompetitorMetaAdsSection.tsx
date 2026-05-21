/**
 * CompetitorMetaAdsSection — Meta Ad Library widget for one competitor.
 *
 * Rendered inside CompetitorDetailPage below the "Sample pages" section.
 * Pulls from /api/v1/seo/meta-ads/?competitor=<name>. Backend caches
 * per-competitor responses on disk for 24h so re-renders are free.
 *
 * Styling: clean Bajaj blue + white, premium card layout, no anchor
 * underlines anywhere, soft elevation on hover. Lives under .bajaj-ui
 * so shadcn primitives + Tailwind brand-* tokens apply.
 */
import { useMemo, useState } from 'react';
import {
  useMetaAds,
  type CompetitorAdsSummary,
  type MetaAd,
} from '../../api/hooks/useMetaAds';
import { Button } from '../ui/button';

interface Props {
  /** Competitor lookup term — domain or company name. */
  competitor: string;
  displayName?: string;
}

export default function CompetitorMetaAdsSection({
  competitor,
  displayName,
}: Props) {
  const [count, setCount] = useState(25);
  const { data, isLoading, isError, error, refetch, isFetching } = useMetaAds(
    [competitor],
    { count, country: 'IN' },
  );

  const summary = data?.competitors?.[0];

  return (
    <section className="mt-10">
      <SectionHeader
        title="Meta Ad Library"
        subtitle={
          <>
            Active and recent Facebook + Instagram ads for{' '}
            <span className="font-medium text-brand-text">
              {displayName || competitor}
            </span>{' '}
            · IN
            {data?.refreshed_at && (
              <>
                {' '}· refreshed{' '}
                {new Date(data.refreshed_at).toLocaleString(undefined, {
                  month: 'short',
                  day: 'numeric',
                  hour: 'numeric',
                  minute: '2-digit',
                })}
              </>
            )}
          </>
        }
        controls={
          <>
            <select
              className="h-8 rounded-md border border-brand-border bg-white px-3 text-xs font-medium text-brand-text outline-none transition-colors hover:border-brand-border-2 focus:border-brand-accent"
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            >
              <option value={10}>Top 10</option>
              <option value={25}>Top 25</option>
              <option value={50}>Top 50</option>
            </select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
              className="h-8"
            >
              {isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
          </>
        }
      />

      {isLoading && (
        <EmptyState>
          Fetching Meta ads via Apify… first run may take ~30–60 seconds.
        </EmptyState>
      )}

      {isError && (
        <EmptyState tone="error">
          {error instanceof Error ? error.message : 'Failed to load Meta ads'}
        </EmptyState>
      )}

      {data && !data.available && (
        <EmptyState>
          {data.reason === 'not_configured' ? (
            <>
              Meta Ads source is not configured. Add{' '}
              <code className="rounded bg-brand-surface-2 px-1.5 py-0.5 text-[11px]">
                APIFY_API_TOKEN
              </code>{' '}
              to{' '}
              <code className="rounded bg-brand-surface-2 px-1.5 py-0.5 text-[11px]">
                .env
              </code>{' '}
              on the backend and reload.
            </>
          ) : (
            <>The source could not be reached: {data.error}</>
          )}
        </EmptyState>
      )}

      {summary?.error && (
        <EmptyState tone="warning">
          Could not pull ads for this competitor: {summary.error}
        </EmptyState>
      )}

      {summary && !summary.error && summary.total_ads === 0 && (
        <EmptyState>
          No active ads found for &ldquo;{competitor}&rdquo; in the Indian Ad
          Library. Try the Refresh button or widen the count.
        </EmptyState>
      )}

      {summary && summary.total_ads > 0 && <Body summary={summary} />}
    </section>
  );
}

// ── Section chrome ─────────────────────────────────────────────────────

function SectionHeader({
  title,
  subtitle,
  controls,
}: {
  title: string;
  subtitle: React.ReactNode;
  controls: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-brand-border pb-3">
      <div className="flex items-center gap-3">
        <span className="block h-6 w-1 rounded-full bg-brand-accent" />
        <div>
          <h2 className="text-base font-semibold tracking-tight text-brand-text">
            {title}
          </h2>
          <div className="mt-0.5 text-[12px] text-brand-text-3">{subtitle}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">{controls}</div>
    </div>
  );
}

function EmptyState({
  children,
  tone = 'default',
}: {
  children: React.ReactNode;
  tone?: 'default' | 'warning' | 'error';
}) {
  const cls =
    tone === 'error'
      ? 'border-severity-error/40 bg-severity-error-soft text-severity-error'
      : tone === 'warning'
      ? 'border-severity-warning/40 bg-severity-warning-soft text-brand-text'
      : 'border-brand-border bg-white text-brand-text-3';
  return (
    <div className={`rounded-lg border px-5 py-6 text-sm ${cls}`}>
      {children}
    </div>
  );
}

// ── Body — KPI row + chip panels + ad gallery ──────────────────────────

function Body({ summary }: { summary: CompetitorAdsSummary }) {
  return (
    <div className="space-y-7">
      <KpiRow summary={summary} />
      <ChipsRow summary={summary} />
      <AdGallery ads={summary.ads} />
    </div>
  );
}

// ── KPI row ────────────────────────────────────────────────────────────

function KpiRow({ summary }: { summary: CompetitorAdsSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <KpiCell label="Total ads" value={summary.total_ads.toLocaleString()} />
      <KpiCell label="Active" value={summary.active_ads.toLocaleString()} />
      <KpiCell
        label="New · 7 days"
        value={summary.new_ads_last_7d.toLocaleString()}
      />
      <KpiCell
        label="Facebook page"
        value={summary.page_name || '—'}
        truncate
      />
      <KpiCell
        label="Top CTA"
        value={summary.top_ctas?.[0]?.cta || '—'}
        truncate
      />
    </div>
  );
}

function KpiCell({
  label,
  value,
  truncate,
}: {
  label: string;
  value: string;
  truncate?: boolean;
}) {
  return (
    <div className="rounded-lg border border-brand-border bg-white px-4 py-3 transition-colors hover:border-brand-border-2">
      <div className="text-[10px] font-medium uppercase tracking-wider text-brand-text-3">
        {label}
      </div>
      <div
        className={
          'mt-1.5 text-lg font-semibold leading-tight text-brand-text' +
          (truncate ? ' truncate' : '')
        }
        title={truncate ? value : undefined}
      >
        {value}
      </div>
    </div>
  );
}

// ── Chips: themes / landing domains / CTAs ─────────────────────────────

function ChipsRow({ summary }: { summary: CompetitorAdsSummary }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      <ChipPanel
        title="Creative themes"
        items={summary.common_themes?.map((t) => ({
          label: t.theme,
          count: t.count,
        }))}
        emptyMsg="No common themes detected."
      />
      <ChipPanel
        title="Landing domains"
        items={summary.top_landing_domains?.map((d) => ({
          label: d.domain,
          count: d.count,
        }))}
        emptyMsg="No landing-page links extracted."
      />
      <ChipPanel
        title="CTAs used"
        items={summary.top_ctas?.map((c) => ({
          label: c.cta,
          count: c.count,
        }))}
        emptyMsg="No CTAs detected."
      />
    </div>
  );
}

function ChipPanel({
  title,
  items,
  emptyMsg,
}: {
  title: string;
  items?: { label: string; count: number }[];
  emptyMsg: string;
}) {
  const list = items ?? [];
  return (
    <div className="rounded-lg border border-brand-border bg-white px-4 py-3">
      <div className="mb-2 text-[10px] font-medium uppercase tracking-wider text-brand-text-3">
        {title}
      </div>
      {list.length === 0 ? (
        <div className="py-1 text-xs text-brand-text-3">{emptyMsg}</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {list.map((it) => (
            <span
              key={it.label}
              className="inline-flex items-center gap-1.5 rounded-full border border-brand-border bg-brand-accent-soft px-2.5 py-1 text-[11px] font-medium text-brand-text"
            >
              <span className="truncate max-w-[180px]">{it.label}</span>
              <span className="rounded-full bg-white px-1.5 text-[10px] font-semibold text-brand-text-3">
                {it.count}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Ad gallery ─────────────────────────────────────────────────────────

function AdGallery({ ads }: { ads: MetaAd[] }) {
  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-brand-text">Ad creatives</h3>
        <span className="text-[11px] text-brand-text-3">
          {ads.length} ad{ads.length === 1 ? '' : 's'}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {ads.map((ad) => (
          <AdCard key={ad.ad_archive_id} ad={ad} />
        ))}
      </div>
    </div>
  );
}

function AdCard({ ad }: { ad: MetaAd }) {
  const card = ad.cards?.[0];
  const img = card?.image_url || ad.page_profile_picture_url;
  const dateRange = useMemo(() => {
    if (ad.start_date_iso && ad.end_date_iso) {
      return `${ad.start_date_iso} → ${ad.end_date_iso}`;
    }
    if (ad.start_date_iso) {
      return ad.is_active
        ? `Running since ${ad.start_date_iso}`
        : `From ${ad.start_date_iso}`;
    }
    return ad.is_active ? 'Currently active' : '';
  }, [ad.start_date_iso, ad.end_date_iso, ad.is_active]);

  // Each ad card is itself a click target — opens the Meta Ad Library
  // detail page in a new tab, which is the canonical "view this ad"
  // surface and lets the operator click through to the live post.
  const detailHref = ad.ad_archive_id
    ? `https://www.facebook.com/ads/library/?id=${encodeURIComponent(ad.ad_archive_id)}`
    : null;

  const cardBody = (
    <div className="group flex h-full flex-col overflow-hidden rounded-xl border border-brand-border bg-white transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-accent hover:shadow-[0_10px_24px_-12px_rgba(0,114,206,0.25)]">
      {/* Image */}
      <div className="relative aspect-[16/10] w-full overflow-hidden bg-brand-surface-2">
        {img ? (
          <img
            src={img}
            alt={card?.title || ad.page_name}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = 'none';
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-brand-text-3">
            No image
          </div>
        )}
        {ad.is_active && (
          <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full bg-white/95 px-2 py-0.5 text-[10px] font-semibold text-severity-success shadow-sm">
            <span className="block h-1.5 w-1.5 rounded-full bg-severity-success" />
            Active
          </span>
        )}
      </div>

      {/* Body */}
      <div className="flex flex-1 flex-col gap-2.5 px-4 py-3">
        {/* Header: page + date */}
        <div className="flex items-center gap-2">
          {ad.page_profile_picture_url && (
            <img
              src={ad.page_profile_picture_url}
              alt={ad.page_name}
              className="h-6 w-6 shrink-0 rounded-full border border-brand-border object-cover"
              loading="lazy"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = 'none';
              }}
            />
          )}
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12px] font-semibold text-brand-text">
              {ad.page_name}
            </div>
            <div className="truncate text-[10.5px] text-brand-text-3">
              {dateRange}
            </div>
          </div>
        </div>

        {/* Headline */}
        {card?.title && (
          <div className="line-clamp-2 text-sm font-semibold leading-snug text-brand-text">
            {card.title}
          </div>
        )}

        {/* Body */}
        {card?.body && (
          <p className="line-clamp-3 text-[12.5px] leading-snug text-brand-text-2">
            {card.body}
          </p>
        )}

        {/* Landing URL */}
        {ad.primary_link_url && ad.primary_link_url.startsWith('http') && (
          <div
            className="truncate rounded-md bg-brand-surface-2 px-2 py-1 font-mono text-[10.5px] text-brand-text-3"
            title={ad.primary_link_url}
          >
            {prettyUrl(ad.primary_link_url)}
          </div>
        )}

        {/* Spacer pushes platform chips to the bottom */}
        <div className="flex-1" />

        {/* Footer chips */}
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          {ad.publisher_platforms?.map((p) => (
            <PlatformChip
              key={p}
              platform={p}
              adArchiveId={ad.ad_archive_id}
            />
          ))}
          {ad.cta_text && (
            <span className="inline-flex items-center rounded-full bg-brand-accent px-2 py-0.5 text-[10px] font-semibold text-white">
              {ad.cta_text}
            </span>
          )}
        </div>
      </div>
    </div>
  );

  if (!detailHref) return cardBody;
  return (
    <a
      href={detailHref}
      target="_blank"
      rel="noreferrer"
      className="block no-underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent rounded-xl"
      title="Open in Meta Ad Library"
    >
      {cardBody}
    </a>
  );
}

// ── Platform chip — clickable, no underline ────────────────────────────

const PLATFORM_LABELS: Record<string, string> = {
  FACEBOOK: 'Facebook',
  INSTAGRAM: 'Instagram',
  MESSENGER: 'Messenger',
  AUDIENCE_NETWORK: 'Audience Net.',
  THREADS: 'Threads',
  OCULUS: 'Oculus',
  WHATSAPP: 'WhatsApp',
};

function PlatformChip({
  platform,
  adArchiveId,
}: {
  platform: string;
  adArchiveId: string;
}) {
  const label = PLATFORM_LABELS[platform] || platform;
  const href = adArchiveId
    ? `https://www.facebook.com/ads/library/?id=${encodeURIComponent(adArchiveId)}`
    : null;
  const baseCls =
    'inline-flex items-center rounded-full border border-brand-border bg-white px-2 py-0.5 text-[10px] font-medium text-brand-text-2';
  if (!href) return <span className={baseCls}>{label}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      onClick={(e) => e.stopPropagation()}
      title={`Open ${label} ad in Meta Ad Library`}
      className={`${baseCls} no-underline transition-colors hover:border-brand-accent hover:bg-brand-accent-soft hover:text-brand-accent`}
    >
      {label}
    </a>
  );
}

// ── helpers ────────────────────────────────────────────────────────────

function prettyUrl(url: string): string {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, '');
    const path = u.pathname.replace(/\/+$/, '');
    return path ? `${host}${path}` : host;
  } catch {
    return url;
  }
}
