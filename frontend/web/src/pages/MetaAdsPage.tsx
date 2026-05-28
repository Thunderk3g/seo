/**
 * MetaAdsPage — Bajaj Life Insurance's OWN Meta ad library.
 *
 * Separate surface from competitor pages. Bajaj ads pulled here in
 * isolation so they don't get mixed into kotaklife.com / hdfclife.com /
 * etc. detail pages (which used to happen because the backend's
 * meta_ads_dashboard view prepends "Bajaj Life Insurance" when
 * include_ours=true).
 *
 * Calls /api/v1/seo/meta-ads/?competitor=Bajaj+Life+Insurance&include_ours=false
 * — same backend, but explicitly asks for ONE entity, no Bajaj
 * auto-prepend. Reuses the existing card / KPI / chip components for
 * styling consistency.
 */
import { useState } from 'react';
import {
  useMetaAds,
  type CompetitorAdsSummary,
  type MetaAd,
} from '../api/hooks/useMetaAds';
import { Button } from '../components/ui/button';

const OUR_BRAND = 'Bajaj Life Insurance';
const COUNT_OPTIONS = [10, 25, 50, 100];

export default function MetaAdsPage() {
  const [count, setCount] = useState(50);
  const { data, isLoading, isError, error, refetch, isFetching } = useMetaAds(
    [OUR_BRAND],
    { count, country: 'IN', includeOurs: false },
  );

  // Same belt-and-braces filter as the competitor section uses — if
  // any future change re-introduces Bajaj into a non-Bajaj request, at
  // least pick the right entry here too.
  const summary =
    (data?.competitors ?? []).find(
      (c) => (c.competitor || '').toLowerCase() === OUR_BRAND.toLowerCase(),
    ) ?? data?.competitors?.[0];

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <div className="text-xs text-brand-text-3">Data Sources / Meta Ads</div>
          <h1 className="mt-1 text-2xl font-semibold text-brand-text">
            Our Meta Ads
          </h1>
          <p className="mt-1 text-sm text-brand-text-3">
            Live Facebook + Instagram ads under{' '}
            <span className="font-medium text-brand-text">{OUR_BRAND}</span> in
            the Indian Ad Library. Separate from each competitor's section
            so the comparison stays clean.
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
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="h-8 rounded-md border border-brand-border bg-white px-3 text-xs font-medium text-brand-text outline-none transition-colors hover:border-brand-border-2 focus:border-brand-accent"
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
          >
            {COUNT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                Top {n}
              </option>
            ))}
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
        </div>
      </header>

      {isLoading && (
        <EmptyState>
          Fetching Bajaj Life ads via Apify… first run may take ~30–60
          seconds.
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
              to the backend <code>.env</code> and reload.
            </>
          ) : (
            <>The source could not be reached: {data.error}</>
          )}
        </EmptyState>
      )}

      {summary?.error && (
        <EmptyState tone="warning">
          Could not pull Bajaj ads: {summary.error}
        </EmptyState>
      )}

      {summary && !summary.error && summary.total_ads === 0 && (
        <EmptyState>
          No active Bajaj ads found in the Indian Ad Library window.
          {' '}This is unusual — try the Refresh button or check that the
          Apify actor is configured with the right country.
        </EmptyState>
      )}

      {summary && summary.total_ads > 0 && <Body summary={summary} />}
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

function Body({ summary }: { summary: CompetitorAdsSummary }) {
  return (
    <div className="space-y-7">
      <KpiRow summary={summary} />
      <ChipsRow summary={summary} />
      <AdGallery ads={summary.ads} />
    </div>
  );
}

function KpiRow({ summary }: { summary: CompetitorAdsSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <KpiCell label="Total ads" value={summary.total_ads.toLocaleString()} />
      <KpiCell label="Active" value={summary.active_ads.toLocaleString()} />
      <KpiCell
        label="New · 7 days"
        value={summary.new_ads_last_7d.toLocaleString()}
      />
      <KpiCell label="Page" value={summary.page_name || '—'} truncate />
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
  // Fallback chain matches CompetitorMetaAdsSection: image_url (image
  // ads) → thumbnail_url (FB video_preview_image_url poster for video
  // ads, or watermarked_resized_image_url) → page profile pic. Without
  // thumbnail_url every video ad rendered as the small profile dot in
  // a big "No image" tile.
  const img = card?.image_url || card?.thumbnail_url || ad.page_profile_picture_url;
  const isVideoAd = Boolean(card?.video_url);
  const dateRange =
    ad.start_date_iso && ad.end_date_iso
      ? `${ad.start_date_iso} → ${ad.end_date_iso}`
      : ad.start_date_iso
        ? ad.is_active
          ? `Running since ${ad.start_date_iso}`
          : `From ${ad.start_date_iso}`
        : ad.is_active
          ? 'Currently active'
          : '';
  const detailHref = ad.ad_archive_id
    ? `https://www.facebook.com/ads/library/?id=${encodeURIComponent(ad.ad_archive_id)}`
    : null;

  const cardBody = (
    <div className="group flex h-full flex-col overflow-hidden rounded-xl border border-brand-border bg-white transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-accent hover:shadow-[0_10px_24px_-12px_rgba(0,114,206,0.25)]">
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
        {isVideoAd && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-black/55 text-white shadow-lg">
              <svg viewBox="0 0 24 24" fill="currentColor" className="h-6 w-6">
                <path d="M8 5v14l11-7z" />
              </svg>
            </span>
          </div>
        )}
        {ad.is_active && (
          <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full bg-white/95 px-2 py-0.5 text-[10px] font-semibold text-severity-success shadow-sm">
            <span className="block h-1.5 w-1.5 rounded-full bg-severity-success" />
            Active
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2.5 px-4 py-3">
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
        {card?.title && (
          <div className="line-clamp-2 text-sm font-semibold leading-snug text-brand-text">
            {card.title}
          </div>
        )}
        {card?.body && (
          <p className="line-clamp-3 text-[12.5px] leading-snug text-brand-text-2">
            {card.body}
          </p>
        )}
        {ad.primary_link_url && ad.primary_link_url.startsWith('http') && (
          <div
            className="truncate rounded-md bg-brand-surface-2 px-2 py-1 font-mono text-[10.5px] text-brand-text-3"
            title={ad.primary_link_url}
          >
            {prettyUrl(ad.primary_link_url)}
          </div>
        )}
        <div className="flex-1" />
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          {ad.publisher_platforms?.map((p) => (
            <span
              key={p}
              className="inline-flex items-center rounded-full border border-brand-border bg-white px-2 py-0.5 text-[10px] font-medium text-brand-text-2"
            >
              {p === 'FACEBOOK'
                ? 'Facebook'
                : p === 'INSTAGRAM'
                  ? 'Instagram'
                  : p === 'MESSENGER'
                    ? 'Messenger'
                    : p === 'AUDIENCE_NETWORK'
                      ? 'Audience Net.'
                      : p}
            </span>
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
