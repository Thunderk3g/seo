/**
 * Bajaj-branded DataTable — thin TanStack Table wrapper.
 *
 * Used by the Phase 2 Page Explorer and (later) the Compare Crawls
 * snapshot diff. Designed so a caller passes columns + data + a
 * pagination + sort handler, and gets back a Bajaj-themed table with
 * sortable headers, alternating zebra rows, and bottom pagination.
 *
 * Server-side mode is the default: callers pass `pageCount` so we
 * don't try to slice the data array client-side. Sort + filter state
 * lives in the parent so React Query can refetch on change.
 */
import * as React from 'react';
import {
  type ColumnDef,
  type OnChangeFn,
  type PaginationState,
  type SortingState,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react';
import { cn } from '../../lib/utils';
import { Button } from './button';

export interface DataTableProps<TData> {
  columns: ColumnDef<TData, unknown>[];
  data: TData[];
  pageCount: number;
  sorting: SortingState;
  onSortingChange: OnChangeFn<SortingState>;
  pagination: PaginationState;
  onPaginationChange: OnChangeFn<PaginationState>;
  isLoading?: boolean;
  emptyMessage?: string;
}

export function DataTable<TData>({
  columns,
  data,
  pageCount,
  sorting,
  onSortingChange,
  pagination,
  onPaginationChange,
  isLoading,
  emptyMessage = 'No rows match the current filters.',
}: DataTableProps<TData>): React.JSX.Element {
  const table = useReactTable({
    data,
    columns,
    pageCount,
    state: { sorting, pagination },
    manualSorting: true,
    manualPagination: true,
    onSortingChange,
    onPaginationChange,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="bajaj-ui">
      <div className="overflow-hidden rounded-md border border-brand-border bg-card shadow-e1">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-brand-border bg-brand-surface-2 text-left">
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id}>
                  {group.headers.map((header) => {
                    const canSort = header.column.getCanSort();
                    const sortDir = header.column.getIsSorted();
                    return (
                      <th
                        key={header.id}
                        scope="col"
                        className={cn(
                          'px-3 py-2 text-xs font-semibold uppercase tracking-wide text-brand-text-3',
                          canSort && 'cursor-pointer select-none hover:text-brand-text',
                        )}
                        onClick={
                          canSort
                            ? header.column.getToggleSortingHandler()
                            : undefined
                        }
                      >
                        <span className="inline-flex items-center gap-1">
                          {header.isPlaceholder
                            ? null
                            : flexRender(header.column.columnDef.header, header.getContext())}
                          {canSort && (
                            <SortIndicator dir={sortDir} />
                          )}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={columns.length} className="px-3 py-8 text-center text-brand-text-3">
                    Loading…
                  </td>
                </tr>
              ) : table.getRowModel().rows.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="px-3 py-8 text-center text-brand-text-3">
                    {emptyMessage}
                  </td>
                </tr>
              ) : (
                table.getRowModel().rows.map((row, idx) => (
                  <tr
                    key={row.id}
                    className={cn(
                      'border-t border-brand-border align-top',
                      idx % 2 === 1 && 'bg-brand-surface-2/50',
                      'hover:bg-brand-accent-soft',
                    )}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-3 py-2 text-brand-text">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-brand-text-3">
        <div>
          Page <span className="font-semibold text-brand-text">{pagination.pageIndex + 1}</span>{' '}
          of <span className="font-semibold text-brand-text">{Math.max(pageCount, 1)}</span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

function SortIndicator({ dir }: { dir: false | 'asc' | 'desc' }) {
  if (dir === 'asc') return <ChevronUp className="h-3 w-3" />;
  if (dir === 'desc') return <ChevronDown className="h-3 w-3" />;
  return <ChevronsUpDown className="h-3 w-3 opacity-40" />;
}
