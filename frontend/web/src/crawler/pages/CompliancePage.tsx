/**
 * CompliancePage — `/crawler/compliance`.
 *
 * Manager-facing compliance report. Aggregates the WCAG 2.1
 * accessibility, GDPR/DPDPA cookie, and OWASP security-header
 * detectors into one purpose-built dashboard with per-URL evidence.
 *
 * Designed for show-and-tell: KPI strip up top, each section
 * expandable, each rule with formal standard references and the
 * specific URLs hit. CSV download for handing to the engineering
 * team. Bajaj blue/white palette per the brand memory.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { crawlerApi } from '../api';

type Severity = 'error' | 'warning' | 'notice';

const SEVERITY_TONE: Record<Severity, 'error' | 'warning' | 'notice'> = {
  error: 'error',
  warning: 'warning',
  notice: 'notice',
};

// API base — same convention used by other crawler pages.
const API_BASE = '/api/v1/crawler';

export default function CompliancePage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['crawler', 'compliance'],
    queryFn: () => crawlerApi.compliance(),
    staleTime: 60_000,
  });

  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    wcag: true,
    privacy: true,
    security_headers: true,
  });
  const [openRules, setOpenRules] = useState<Record<string, boolean>>({});

  const toggleSection = (key: string) =>
    setOpenSections((s) => ({ ...s, [key]: !s[key] }));
  const toggleRule = (slug: string) =>
    setOpenRules((s) => ({ ...s, [slug]: !s[slug] }));

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-brand-text">
            Compliance Dashboard
          </h1>
          <p className="mt-1 text-sm text-brand-text-3">
            WCAG 2.1 accessibility, GDPR / DPDPA cookie consent, and OWASP
            security-header findings across the crawled site, with the
            exact URLs and evidence behind each rule.
          </p>
        </div>
        <a
          href={`${API_BASE}/compliance.csv`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex"
        >
          <Button variant="outline" size="sm">
            Download CSV
          </Button>
        </a>
      </header>

      {isLoading && (
        <div className="text-sm text-brand-text-3">Running compliance audit…</div>
      )}

      {isError && (
        <Card className="border-severity-error">
          <CardContent className="py-4 text-sm text-severity-error">
            Failed to load compliance report:{' '}
            {error instanceof Error ? error.message : 'unknown error'}
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          <KpiStrip summary={data.summary} />

          <div className="mt-6 space-y-4">
            {data.sections.map((section) => {
              const isOpen = openSections[section.key] ?? true;
              return (
                <Card key={section.key} className="shadow-e1">
                  <button
                    type="button"
                    onClick={() => toggleSection(section.key)}
                    className="flex w-full items-center justify-between gap-4 px-6 py-4 text-left"
                  >
                    <div>
                      <div className="text-base font-semibold text-brand-text">
                        {section.title}
                      </div>
                      <div className="mt-1 text-sm text-brand-text-3">
                        {section.rules.filter((r) => r.count > 0).length} of{' '}
                        {section.rules.length} rules failing &middot;{' '}
                        {section.total_violations.toLocaleString()} total
                        violations
                      </div>
                    </div>
                    <span className="text-sm text-brand-accent">
                      {isOpen ? 'Collapse' : 'Expand'}
                    </span>
                  </button>

                  {isOpen && (
                    <CardContent className="pt-0">
                      <div className="space-y-3">
                        {section.rules.length === 0 && (
                          <div className="text-sm text-brand-text-3">
                            No rules in this section.
                          </div>
                        )}
                        {section.rules.map((rule) => (
                          <RuleRow
                            key={rule.slug}
                            rule={rule}
                            open={Boolean(openRules[rule.slug])}
                            onToggle={() => toggleRule(rule.slug)}
                          />
                        ))}
                      </div>
                    </CardContent>
                  )}
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function KpiStrip({
  summary,
}: {
  summary: {
    total_violations: number;
    unique_rules_failed: number;
    pages_with_any_violation: number;
    by_severity: { error: number; warning: number; notice: number };
  };
}) {
  const tiles = [
    { label: 'Total violations', value: summary.total_violations },
    { label: 'Unique rules failed', value: summary.unique_rules_failed },
    { label: 'Pages affected', value: summary.pages_with_any_violation },
    { label: 'Errors', value: summary.by_severity.error, tone: 'error' as const },
    {
      label: 'Warnings',
      value: summary.by_severity.warning,
      tone: 'warning' as const,
    },
    {
      label: 'Notices',
      value: summary.by_severity.notice,
      tone: 'notice' as const,
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      {tiles.map((t) => (
        <Card key={t.label} className="shadow-e1">
          <CardContent className="px-4 py-3">
            <div className="text-xs font-medium uppercase tracking-wide text-brand-text-3">
              {t.label}
            </div>
            <div
              className={
                'mt-1 text-2xl font-semibold ' +
                (t.tone === 'error'
                  ? 'text-severity-error'
                  : t.tone === 'warning'
                  ? 'text-severity-warning'
                  : t.tone === 'notice'
                  ? 'text-severity-notice'
                  : 'text-brand-text')
              }
            >
              {t.value.toLocaleString()}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function RuleRow({
  rule,
  open,
  onToggle,
}: {
  rule: {
    slug: string;
    title: string;
    severity: Severity;
    why: string;
    how_to_fix: string;
    references: Array<{ standard: string; ref: string; level?: string; name: string }>;
    count: number;
    affected_urls: Array<{
      url: string;
      title: string;
      page_type: string;
      evidence: string;
    }>;
  };
  open: boolean;
  onToggle: () => void;
}) {
  const hasFindings = rule.count > 0;
  return (
    <div
      className={
        'rounded-md border ' +
        (hasFindings
          ? 'border-brand-border bg-brand-surface'
          : 'border-brand-border-2 bg-brand-surface-2 opacity-70')
      }
    >
      <button
        type="button"
        onClick={onToggle}
        disabled={!hasFindings}
        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={SEVERITY_TONE[rule.severity]}>
              {rule.severity}
            </Badge>
            {rule.references.map((r, i) => (
              <Badge key={`${r.standard}-${r.ref}-${i}`} variant="outline">
                {r.standard} {r.ref}
                {r.level ? ` (${r.level})` : ''}
              </Badge>
            ))}
            <span className="text-xs text-brand-text-3">
              {rule.count.toLocaleString()} page
              {rule.count === 1 ? '' : 's'}
            </span>
          </div>
          <div className="mt-1 text-sm font-medium text-brand-text">
            {rule.title}
          </div>
          <div className="mt-1 text-xs text-brand-text-3">{rule.why}</div>
        </div>
        {hasFindings && (
          <span className="text-xs text-brand-accent">
            {open ? 'Hide URLs' : 'Show URLs'}
          </span>
        )}
      </button>

      {open && hasFindings && (
        <div className="border-t border-brand-border px-4 py-3">
          <div className="mb-2 rounded-md bg-brand-surface-2 px-3 py-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-brand-text-3">
              How to fix
            </div>
            <p className="mt-1 text-sm text-brand-text">{rule.how_to_fix}</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-brand-border text-left text-xs uppercase tracking-wide text-brand-text-3">
                  <th className="py-2 pr-3">URL</th>
                  <th className="py-2 pr-3">Page type</th>
                  <th className="py-2">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {rule.affected_urls.map((u, i) => (
                  <tr
                    key={`${u.url}-${i}`}
                    className="border-b border-brand-border-2 last:border-b-0"
                  >
                    <td className="py-2 pr-3">
                      <a
                        href={u.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-brand-accent hover:underline"
                      >
                        {u.url}
                      </a>
                      {u.title && (
                        <div className="text-xs text-brand-text-3">
                          {u.title}
                        </div>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-brand-text-2">
                      {u.page_type || '—'}
                    </td>
                    <td className="py-2 text-brand-text-2">{u.evidence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
