/**
 * IssuesPage — `/crawler/issues`.
 *
 * Triage inbox for the typed audit catalogue. Severity tabs (Errors /
 * Warnings / Notices) collapse the firehose into actionable slices. Each
 * issue row shows count + "why" + "how to fix" copy. Clicking a row
 * (Phase 4 enhancement) drills into affected URLs.
 *
 * Bajaj brand via shadcn primitives. Wrapped in `bajaj-ui` scope.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'wouter';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { crawlerApi } from '../api';

type Severity = 'error' | 'warning' | 'notice';

const SEVERITY_LABEL: Record<Severity, string> = {
  error: 'Errors',
  warning: 'Warnings',
  notice: 'Notices',
};

const SEVERITY_TONE: Record<Severity, 'error' | 'warning' | 'notice'> = {
  error: 'error',
  warning: 'warning',
  notice: 'notice',
};

export default function IssuesPage() {
  const [activeSeverity, setActiveSeverity] = useState<Severity>('error');

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['crawler', 'issues'],
    queryFn: () => crawlerApi.issues(),
    staleTime: 60_000,
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.issues.filter((i) => i.severity === activeSeverity);
  }, [data, activeSeverity]);

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-brand-text">Issues</h1>
        <p className="mt-1 text-sm text-brand-text-3">
          Typed SEO issues detected in the latest crawl. Click a row to see
          the affected URLs and fix instructions.
        </p>
      </header>

      <SeverityTabs
        active={activeSeverity}
        counts={data?.issue_type_counts}
        onChange={setActiveSeverity}
      />

      {isLoading && (
        <div className="text-sm text-brand-text-3">Running audit detectors…</div>
      )}

      {isError && (
        <Card className="border-severity-error">
          <CardContent className="py-4 text-sm text-severity-error">
            Failed to load issues:{' '}
            {error instanceof Error ? error.message : 'unknown error'}
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && filtered.length === 0 && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-brand-text-3">
            No {SEVERITY_LABEL[activeSeverity].toLowerCase()} detected.
          </CardContent>
        </Card>
      )}

      {filtered.length > 0 && (
        <div className="space-y-3">
          {filtered.map((issue) => (
            <Card key={issue.slug} className="shadow-e1">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <CardTitle className="text-base">{issue.title}</CardTitle>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Badge variant={SEVERITY_TONE[issue.severity]}>
                        {SEVERITY_LABEL[issue.severity].slice(0, -1)}
                      </Badge>
                      <Badge variant="outline">{issue.category}</Badge>
                      <span className="text-xs text-brand-text-3">
                        {issue.count.toLocaleString()} affected URL
                        {issue.count === 1 ? '' : 's'}
                      </span>
                    </div>
                  </div>
                  <Link href={`/crawler/issues/${issue.slug}`}>
                    <Button variant="outline" size="sm">
                      View URLs
                    </Button>
                  </Link>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                <p className="text-sm text-brand-text-2">{issue.why}</p>
                <div className="mt-3 rounded-md bg-brand-surface-2 px-3 py-2">
                  <div className="text-xs font-semibold uppercase tracking-wide text-brand-text-3">
                    How to fix
                  </div>
                  <p className="mt-1 text-sm text-brand-text">
                    {issue.how_to_fix}
                  </p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function SeverityTabs({
  active,
  counts,
  onChange,
}: {
  active: Severity;
  counts: { error: number; warning: number; notice: number } | undefined;
  onChange: (s: Severity) => void;
}) {
  const tabs: Severity[] = ['error', 'warning', 'notice'];
  return (
    <div className="mb-5 flex gap-2 border-b border-brand-border">
      {tabs.map((s) => {
        const isActive = s === active;
        const count = counts?.[s] ?? 0;
        return (
          <button
            key={s}
            type="button"
            onClick={() => onChange(s)}
            className={
              'relative -mb-px flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium transition-colors ' +
              (isActive
                ? 'border-brand-accent text-brand-text'
                : 'border-transparent text-brand-text-3 hover:text-brand-text')
            }
          >
            {SEVERITY_LABEL[s]}
            <span className="rounded-full bg-brand-surface-2 px-2 py-0.5 text-xs">
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
