/**
 * HealthScoreCard — single-KPI overview rendered at the top of the
 * crawler dashboard.
 *
 * Reads /api/v1/crawler/health-score and shows:
 *   * The Health Score (0-100) + tier badge (Excellent/Good/Fair/Weak)
 *   * Error / Warning / Notice counts
 *   * Top-5 error-severity issue types
 *   * A link to the full Issues page for drill-in
 *
 * All styling via shadcn primitives so the look matches the Phase 1
 * design system (Bajaj brand from tailwind.config.js). Wrapped in
 * `<div className="bajaj-ui">` so the Tailwind cascade is scoped and
 * doesn't leak onto legacy pages.
 */
import { useQuery } from '@tanstack/react-query';
import { Link } from 'wouter';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { crawlerApi } from '../api';

type Tier = 'Excellent' | 'Good' | 'Fair' | 'Weak';

const TIER_TONE: Record<Tier, 'success' | 'notice' | 'warning' | 'error'> = {
  Excellent: 'success',
  Good: 'notice',
  Fair: 'warning',
  Weak: 'error',
};

const TIER_TEXT_CLASS: Record<Tier, string> = {
  Excellent: 'text-severity-success',
  Good: 'text-severity-notice',
  Fair: 'text-severity-warning',
  Weak: 'text-severity-error',
};

export default function HealthScoreCard() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['crawler', 'health-score'],
    queryFn: () => crawlerApi.healthScore(),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="bajaj-ui">
        <Card className="mb-4">
          <CardContent className="py-6">
            <div className="text-sm text-brand-text-3">Computing Health Score…</div>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="bajaj-ui">
        <Card className="mb-4 border-severity-error">
          <CardContent className="py-6">
            <div className="text-sm text-severity-error">
              Health Score unavailable: {error instanceof Error ? error.message : 'unknown error'}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const tier = data.tier as Tier;
  const tierTone = TIER_TONE[tier];
  const tierTextClass = TIER_TEXT_CLASS[tier];

  return (
    <div className="bajaj-ui">
      <Card className="mb-4 shadow-e2">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle>Health Score</CardTitle>
            <Link href="/crawler/issues">
              <Button variant="outline" size="sm">
                View all issues
              </Button>
            </Link>
          </div>
        </CardHeader>

        <CardContent>
          <div className="flex flex-wrap items-baseline gap-6">
            <div>
              <div className={`text-5xl font-bold leading-none ${tierTextClass}`}>
                {data.score}
                <span className="ml-1 text-2xl text-brand-text-3">/ 100</span>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Badge variant={tierTone}>{tier}</Badge>
                <span className="text-xs text-brand-text-3">
                  {data.urls_without_error.toLocaleString()} of{' '}
                  {data.total_urls.toLocaleString()} URLs without errors
                </span>
              </div>
            </div>

            <div className="flex flex-wrap gap-4">
              <SeverityStat
                label="Errors"
                count={data.severity_counts.error}
                types={data.issue_type_counts.error}
                tone="error"
              />
              <SeverityStat
                label="Warnings"
                count={data.severity_counts.warning}
                types={data.issue_type_counts.warning}
                tone="warning"
              />
              <SeverityStat
                label="Notices"
                count={data.severity_counts.notice}
                types={data.issue_type_counts.notice}
                tone="notice"
              />
            </div>
          </div>

          {data.top_errors.length > 0 && (
            <div className="mt-6">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                Top errors by affected URLs
              </div>
              <ul className="space-y-1.5">
                {data.top_errors.map((e) => (
                  <li
                    key={e.slug}
                    className="flex items-center justify-between rounded-md bg-brand-surface-2 px-3 py-2 text-sm"
                  >
                    <Link href={`/crawler/issues/${e.slug}`}>
                      <span className="cursor-pointer text-brand-text hover:underline">
                        {e.title}
                      </span>
                    </Link>
                    <Badge variant="error">{e.count.toLocaleString()}</Badge>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-4 text-xs text-brand-text-4">
            Formula: <span className="font-mono">{data.formula}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function SeverityStat({
  label,
  count,
  types,
  tone,
}: {
  label: string;
  count: number;
  types: number;
  tone: 'error' | 'warning' | 'notice';
}) {
  const textClass =
    tone === 'error'
      ? 'text-severity-error'
      : tone === 'warning'
        ? 'text-severity-warning'
        : 'text-severity-notice';

  return (
    <div>
      <div className={`text-2xl font-semibold leading-none ${textClass}`}>
        {count.toLocaleString()}
      </div>
      <div className="mt-1 text-xs text-brand-text-3">
        {label} <span className="text-brand-text-4">({types} types)</span>
      </div>
    </div>
  );
}
