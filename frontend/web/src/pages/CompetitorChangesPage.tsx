/**
 * CompetitorChangesPage — `/competitor-changes`.
 *
 * Daily feed of ChangeWatcher events. One row per detected event:
 * new URL, title flip, body-content shift, structural rearrangement,
 * URL drop. Filterable by competitor + event kind.
 *
 * The list is empty until the 03:00 IST competitor walks fire and
 * the ChangeWatcher post-processes the snapshots. After that the
 * feed populates daily.
 */
import { useState } from 'react';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { useCompetitorChanges } from '../api/hooks/useBriefings';

const KINDS = ['', 'new', 'title', 'content', 'structure', 'removed'] as const;
type Kind = (typeof KINDS)[number];

export default function CompetitorChangesPage() {
  const [domain, setDomain] = useState('');
  const [kind, setKind] = useState<Kind>('');
  const [limit, setLimit] = useState(100);

  const { data, isLoading, isError, error } = useCompetitorChanges({
    domain: domain || undefined,
    kind: kind || undefined,
    limit,
  });

  return (
    <div className="bajaj-ui p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-brand-text">
          Competitor Changes
        </h1>
        <p className="mt-1 text-sm text-brand-text-3">
          Cross-snapshot ChangeWatcher events for every competitor in the
          roster. Updates after each 03:00 IST walk. Empty rows mean no
          flips that day.
        </p>
      </header>

      {/* Filters */}
      <Card>
        <CardContent className="py-4">
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-brand-text-3">
                Competitor (apex host)
              </label>
              <input
                type="text"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="iciciprulife.com"
                className="rounded border border-brand-line bg-white px-3 py-1.5 text-sm font-mono"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-brand-text-3">
                Event kind
              </label>
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as Kind)}
                className="rounded border border-brand-line bg-white px-3 py-1.5 text-sm"
              >
                <option value="">all kinds</option>
                <option value="new">new URLs</option>
                <option value="title">title changes</option>
                <option value="content">content changes</option>
                <option value="structure">structure changes</option>
                <option value="removed">removed URLs</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-brand-text-3">
                Show
              </label>
              <select
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="rounded border border-brand-line bg-white px-3 py-1.5 text-sm"
              >
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={250}>250</option>
                <option value={500}>500</option>
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Feed */}
      <Card>
        <CardHeader>
          <CardTitle>
            {isLoading ? 'Loading…' : `${data?.count ?? 0} events`}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isError ? (
            <div className="text-severity-error">
              {error instanceof Error ? error.message : 'Failed to load'}
            </div>
          ) : isLoading ? (
            <div className="text-sm text-brand-text-3">Loading…</div>
          ) : (data?.events ?? []).length === 0 ? (
            <div className="text-sm text-brand-text-3 italic">
              No events match the current filter. Run a competitor
              walk via{' '}
              <code className="rounded bg-brand-tint-50 px-1">
                walk_competitor_task.delay('hdfclife.com')
              </code>{' '}
              and re-load.
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead className="text-brand-text-3">
                <tr>
                  <th className="px-2 py-1 text-left">When</th>
                  <th className="px-2 py-1 text-left">Competitor</th>
                  <th className="px-2 py-1 text-left">Kind</th>
                  <th className="px-2 py-1 text-left">URL</th>
                  <th className="px-2 py-1 text-left">Delta</th>
                </tr>
              </thead>
              <tbody>
                {(data?.events ?? []).map((ev) => (
                  <tr
                    key={ev.id}
                    className="border-t border-brand-line hover:bg-brand-tint-50"
                  >
                    <td className="px-2 py-1 text-brand-text-3 whitespace-nowrap">
                      {new Date(ev.detected_at).toLocaleString()}
                    </td>
                    <td className="px-2 py-1 font-medium">
                      {ev.competitor_domain}
                    </td>
                    <td className="px-2 py-1">
                      <Badge variant="notice">{ev.kind}</Badge>
                    </td>
                    <td className="px-2 py-1 break-all">
                      <a
                        href={ev.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-brand-accent hover:underline"
                      >
                        {ev.url}
                      </a>
                    </td>
                    <td className="px-2 py-1 text-brand-text-3 font-mono">
                      <DeltaCell delta={ev.delta} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function DeltaCell({ delta }: { delta: Record<string, unknown> }) {
  if (!delta || Object.keys(delta).length === 0) {
    return <span>—</span>;
  }
  // Render the most useful 2-3 keys compactly. The full payload is
  // available via the API; this is just the summary cell.
  const entries = Object.entries(delta).slice(0, 3);
  return (
    <span>
      {entries.map(([k, v]) => (
        <span key={k} className="mr-2">
          <span className="text-brand-text-3">{k}=</span>
          <span>
            {typeof v === 'object' ? JSON.stringify(v).slice(0, 60) : String(v).slice(0, 60)}
          </span>
        </span>
      ))}
    </span>
  );
}
