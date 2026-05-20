/**
 * PageExplorerPage — `/crawler/pages`.
 *
 * Ahrefs-style sortable/filterable URL inventory built on TanStack
 * Table over the crawler's existing CSV (server-side cached). Lets the
 * operator find pages by status, subdomain, page-type, indexed status,
 * PSI presence, or substring search across URL + title.
 *
 * Designed to be the workhorse view — Phase 3 swaps the data source
 * from CSV to Postgres without changing this page.
 *
 * No emojis. Bajaj brand via shadcn primitives + tailwind tokens.
 */
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { ColumnDef, PaginationState, SortingState } from '@tanstack/react-table';
import { crawlerApi } from '../api';
import { Card, CardContent } from '../../components/ui/card';
import { DataTable } from '../../components/ui/data-table';
import { Input } from '../../components/ui/input';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';

type Row = Record<string, string>;

const ALL = '__all__';

export default function PageExplorerPage() {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'url', desc: false }]);
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 50,
  });
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>(ALL);
  const [subdomainFilter, setSubdomainFilter] = useState<string>(ALL);
  const [pageTypeFilter, setPageTypeFilter] = useState<string>(ALL);
  const [indexedFilter, setIndexedFilter] = useState<string>(ALL);

  // Debounce the substring search 300 ms so each keystroke doesn't
  // hammer the endpoint.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Reset to page 1 on every filter or sort change.
  useEffect(() => {
    setPagination((p) => ({ ...p, pageIndex: 0 }));
  }, [
    debouncedSearch, statusFilter, subdomainFilter, pageTypeFilter,
    indexedFilter, sorting,
  ]);

  const sortParam = useMemo(() => {
    if (sorting.length === 0) return 'url';
    const s = sorting[0];
    return s.desc ? `-${s.id}` : s.id;
  }, [sorting]);

  const facets = useQuery({
    queryKey: ['crawler', 'pages-facets'],
    queryFn: () => crawlerApi.pagesFacets(),
    staleTime: 10 * 60_000,
  });

  const queryParams = {
    sort: sortParam,
    limit: pagination.pageSize,
    offset: pagination.pageIndex * pagination.pageSize,
    q: debouncedSearch || undefined,
    status: statusFilter === ALL ? undefined : statusFilter,
    subdomain: subdomainFilter === ALL ? undefined : subdomainFilter,
    page_type: pageTypeFilter === ALL ? undefined : pageTypeFilter,
    indexed: indexedFilter === ALL ? undefined : indexedFilter,
  };

  const pages = useQuery({
    queryKey: ['crawler', 'pages', queryParams],
    queryFn: () => crawlerApi.pages(queryParams),
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });

  const columns: ColumnDef<Row>[] = useMemo(
    () => [
      {
        accessorKey: 'url',
        header: 'URL',
        cell: ({ row }) => (
          <div>
            <div className="font-medium text-brand-text">
              {row.original.title || (
                <span className="italic text-brand-text-3">— no title —</span>
              )}
            </div>
            <a
              href={row.original.url}
              target="_blank"
              rel="noreferrer"
              className="block break-all font-mono text-xs text-brand-accent hover:underline"
            >
              {row.original.url}
            </a>
          </div>
        ),
      },
      {
        accessorKey: 'status_code',
        header: 'Status',
        cell: ({ row }) => <StatusBadge code={row.original.status_code} />,
      },
      {
        accessorKey: 'subdomain',
        header: 'Subdomain',
        cell: ({ row }) => row.original.subdomain || '—',
      },
      {
        accessorKey: 'page_type',
        header: 'Type',
        cell: ({ row }) => row.original.page_type || '—',
      },
      {
        accessorKey: 'word_count',
        header: 'Words',
        cell: ({ row }) => (
          <span className="tabular-nums">
            {Number(row.original.word_count || 0).toLocaleString()}
          </span>
        ),
      },
      {
        accessorKey: 'response_time_ms',
        header: 'Response',
        cell: ({ row }) => (
          <span className="tabular-nums">
            {Number(row.original.response_time_ms || 0).toLocaleString()} ms
          </span>
        ),
      },
      {
        accessorKey: 'indexed_status',
        header: 'Indexed',
        cell: ({ row }) => <IndexedBadge value={row.original.indexed_status || 'unknown'} />,
      },
      {
        accessorKey: 'pagespeed_score',
        header: 'PageSpeed',
        cell: ({ row }) =>
          row.original.pagespeed_score ? (
            <span className="tabular-nums">{row.original.pagespeed_score}</span>
          ) : (
            <span className="text-brand-text-3">—</span>
          ),
      },
      {
        accessorKey: 'lcp_ms',
        header: 'LCP',
        cell: ({ row }) =>
          row.original.lcp_ms ? (
            <span className="tabular-nums">
              {Number(row.original.lcp_ms).toLocaleString()} ms
            </span>
          ) : (
            <span className="text-brand-text-3">—</span>
          ),
      },
    ],
    [],
  );

  const data = pages.data?.rows || [];
  const pageCount = pages.data
    ? Math.max(1, Math.ceil(pages.data.total / pagination.pageSize))
    : 1;

  return (
    <div className="bajaj-ui p-6">
      <header className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-brand-text">Page Explorer</h1>
          <p className="mt-1 text-sm text-brand-text-3">
            Sortable, filterable inventory of every URL the crawler saw.
            Click a column header to sort. Use the filters to narrow.
          </p>
        </div>
        <a href="/crawler-api/download/results" download>
          <Button variant="outline" size="sm">Download CSV</Button>
        </a>
      </header>

      <Card className="mb-4">
        <CardContent className="grid grid-cols-1 gap-3 py-4 md:grid-cols-5">
          <div className="md:col-span-2">
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-brand-text-3">
              Search URL or title
            </label>
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="e.g. term-insurance"
            />
          </div>
          <FacetSelect
            label="Status"
            value={statusFilter}
            onChange={setStatusFilter}
            options={facets.data?.status_code || []}
          />
          <FacetSelect
            label="Subdomain"
            value={subdomainFilter}
            onChange={setSubdomainFilter}
            options={facets.data?.subdomain || []}
          />
          <FacetSelect
            label="Page type"
            value={pageTypeFilter}
            onChange={setPageTypeFilter}
            options={facets.data?.page_type || []}
          />
        </CardContent>
      </Card>

      <div className="mb-3 text-xs text-brand-text-3">
        {pages.data
          ? `${pages.data.total.toLocaleString()} matched · showing ${pages.data.returned}`
          : 'Loading…'}
      </div>

      <DataTable
        columns={columns}
        data={data}
        pageCount={pageCount}
        sorting={sorting}
        onSortingChange={setSorting}
        pagination={pagination}
        onPaginationChange={setPagination}
        isLoading={pages.isLoading}
      />
    </div>
  );
}

function FacetSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-brand-text-3">
        {label}
      </label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger>
          <SelectValue placeholder="All" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All</SelectItem>
          {options.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function StatusBadge({ code }: { code: string }) {
  if (!code) return <span className="text-brand-text-3">—</span>;
  const c = String(code);
  if (c === '200') return <Badge variant="success">{c}</Badge>;
  if (c.startsWith('3')) return <Badge variant="notice">{c}</Badge>;
  if (c.startsWith('4') || c === '0') return <Badge variant="warning">{c}</Badge>;
  return <Badge variant="error">{c}</Badge>;
}

function IndexedBadge({ value }: { value: string }) {
  if (value === 'indexed') return <Badge variant="success">indexed</Badge>;
  if (value === 'excluded') return <Badge variant="error">excluded</Badge>;
  if (value === 'not_indexed') return <Badge variant="warning">not indexed</Badge>;
  return <Badge variant="outline">unknown</Badge>;
}
