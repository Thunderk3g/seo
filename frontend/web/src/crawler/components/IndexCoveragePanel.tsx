/**
 * IndexCoveragePanel — "is it actually indexed?" coverage buckets.
 *
 * Reads /api/v1/crawler/summary/breakdown (by_indexed_status). The crawler
 * tells us what's *indexable* (200, no noindex, self-canonical); GSC tells
 * us what Google *actually* indexed. The definitive verdict comes from the
 * URL Inspection API (live), which converts "unknown" URLs into
 * indexed / not_indexed / excluded — kick it off with the button here.
 *
 * "Not indexed" here = Google crawled it but chose not to index (the
 * crawled-but-not-indexed problem set).
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { crawlerApi } from '../api';

export default function IndexCoveragePanel() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['crawler', 'breakdown'],
    queryFn: () => crawlerApi.breakdown(),
    staleTime: 60_000,
  });

  const [inspecting, setInspecting] = useState(false);
  const [inspectMsg, setInspectMsg] = useState<string | null>(null);

  const runInspection = async () => {
    setInspecting(true);
    setInspectMsg(null);
    try {
      const r = await crawlerApi.inspectGscUnknowns({ max: 200 });
      if (r.ok) {
        setInspectMsg(
          `Inspected ${r.inspected ?? 0} URL(s)` +
            (r.remaining !== undefined ? ` · ${r.remaining} unknown remaining` : ''),
        );
        refetch();
      } else {
        setInspectMsg(r.error || r.msg || 'URL Inspection failed');
      }
    } catch (e) {
      setInspectMsg(e instanceof Error ? e.message : 'URL Inspection failed');
    } finally {
      setInspecting(false);
    }
  };

  const idx = data?.by_indexed_status;

  return (
    <div className="bajaj-ui">
      <Card className="mb-4 shadow-e2">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle>
              Index Coverage
              <span className="ml-2 text-xs font-normal text-brand-text-4">
                what Google actually indexed
              </span>
            </CardTitle>
            <Button variant="outline" size="sm" disabled={inspecting} onClick={runInspection}>
              {inspecting ? 'Inspecting…' : 'Run URL Inspection'}
            </Button>
          </div>
        </CardHeader>

        <CardContent>
          {isLoading && <div className="text-sm text-brand-text-3">Loading coverage…</div>}

          {isError && (
            <div className="text-sm text-severity-error">
              Coverage unavailable: {error instanceof Error ? error.message : 'unknown error'}
            </div>
          )}

          {idx && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Bucket label="Indexed" value={idx.indexed} tone="success" />
              <Bucket
                label="Crawled, not indexed"
                value={idx.not_indexed}
                tone="error"
                hint="Google crawled but chose not to index"
              />
              <Bucket
                label="Excluded"
                value={idx.excluded}
                tone="warning"
                hint="noindex / canonical / redirect / 404"
              />
              <Bucket
                label="Unknown"
                value={idx.unknown}
                tone="muted"
                hint="run URL Inspection for a verdict"
              />
            </div>
          )}

          {inspectMsg && <div className="mt-3 text-xs text-brand-text-3">{inspectMsg}</div>}

          <div className="mt-3 text-xs text-brand-text-4">
            Definitive verdicts come from the GSC URL Inspection API (live, 2,000 URLs/day).
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

const TONE_TEXT: Record<string, string> = {
  success: 'text-severity-success',
  error: 'text-severity-error',
  warning: 'text-severity-warning',
  muted: 'text-brand-text-3',
};

function Bucket({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: number;
  tone: 'success' | 'error' | 'warning' | 'muted';
  hint?: string;
}) {
  return (
    <div className="rounded-md bg-brand-surface-2 px-3 py-3">
      <div className={`text-2xl font-bold leading-none ${TONE_TEXT[tone]}`}>
        {value.toLocaleString()}
      </div>
      <div className="mt-1 text-xs font-medium text-brand-text">{label}</div>
      {hint && <div className="mt-0.5 text-[11px] leading-tight text-brand-text-4">{hint}</div>}
    </div>
  );
}
