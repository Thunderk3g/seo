/**
 * ContentDendrogram — phylogenetic-tree-style view of the cluster data
 * returned by `/api/v1/crawler/content/clusters`.
 *
 *     All content ─┬─ Term Insurance ─┬─ Product landing ─── /term-insurance
 *                  │                  ├─ Calculator     ─┬─ /term-premium-calc
 *                  │                  │                  └─ /term-iSelect-calc
 *                  │                  └─ Blog / Guide   ─── (12 pages, click to open)
 *                  ├─ ULIP            ─── …
 *
 * Three levels of nodes:
 *   col 0  Root                 (single node, snapshot label)
 *   col 1  Product              (10 max, coloured by brand palette)
 *   col 2  Page-type            (per product, click to expand leaves)
 *   col 3  Page leaves          (URL + title, only when its parent is open)
 *
 * Pure SVG — no D3, no extra deps. Orthogonal "elbow" connectors keep
 * it readable at any zoom. Total height grows linearly with the number
 * of visible leaves (page-type rows count as 1 leaf when collapsed; a
 * page-type row counts as N leaves when expanded).
 */
import { useMemo, useState } from 'react';

const PRODUCT_COLOURS: Record<string, string> = {
  term:         '#003DA5',
  ulip:         '#8B5CF6',
  endowment:    '#0EA5E9',
  retirement:   '#10B981',
  child:        '#F59E0B',
  group:        '#EC4899',
  wellness:     '#14B8A6',
  tax:          '#EF4444',
  nri:          '#FDB913',
  general_life: '#64748B',
};

// Layout constants — kept here so visual tweaks are one-stop.
const COL_ROOT = 24;
const COL_PRODUCT = 220;
const COL_PAGETYPE = 460;
const COL_PAGE = 760;
const ROW_HEIGHT = 28;          // pixels per visible leaf row
const PAGE_ROW_HEIGHT = 20;     // tighter for individual page leaves
const FONT_PRODUCT = 14;
const FONT_PAGETYPE = 13;
const FONT_PAGE = 12;
const TOP_PAD = 24;
const BOTTOM_PAD = 24;

type Page = {
  url: string;
  title: string;
  confidence: number;
  tier: number;
  products: string[];
  page_type: string;
};

type PageType = {
  page_type: string;
  label: string;
  count: number;
  pages: Page[];
};

type Product = {
  product: string;
  label: string;
  count: number;
  page_types: PageType[];
};

interface Props {
  /** From `/content/clusters` — same shape as ContentClustersPage. */
  products: Product[];
  /** Optional title shown at the root node. */
  rootLabel?: string;
}

// Internal type after layout computation — every node carries an absolute y.
type LayoutPageType = PageType & {
  y: number;          // y of the page-type label itself
  yTop: number;       // y of first child (for connector start)
  yBot: number;       // y of last child (for connector end)
  expanded: boolean;
};

type LayoutProduct = Product & {
  y: number;
  yTop: number;
  yBot: number;
  page_types: LayoutPageType[];
};

export default function ContentDendrogram({ products, rootLabel = 'All content' }: Props) {
  // Track which page-type nodes are expanded (key = "product:page_type").
  const [open, setOpen] = useState<Set<string>>(new Set());

  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  // Compute every node's y-coordinate in one pass. We walk depth-first,
  // assigning leaf rows first, then back-propagating parent midpoints.
  const layout = useMemo(() => {
    let cursor = TOP_PAD;
    const laidOut: LayoutProduct[] = products.map((prod) => {
      const productTop = cursor;

      const ptLaidOut: LayoutPageType[] = prod.page_types.map((pt) => {
        const key = `${prod.product}:${pt.page_type}`;
        const isOpen = open.has(key);

        const ptStart = cursor;
        if (isOpen && pt.pages.length > 0) {
          // Each page = one row of PAGE_ROW_HEIGHT
          cursor += pt.pages.length * PAGE_ROW_HEIGHT;
          // The page-type label sits in the vertical centre of its children
          const yLabel = ptStart + (pt.pages.length * PAGE_ROW_HEIGHT) / 2 - PAGE_ROW_HEIGHT / 2;
          return {
            ...pt,
            expanded: true,
            y: yLabel,
            yTop: ptStart + PAGE_ROW_HEIGHT / 2 - PAGE_ROW_HEIGHT / 2,
            yBot: ptStart + (pt.pages.length - 1) * PAGE_ROW_HEIGHT + PAGE_ROW_HEIGHT / 2 - PAGE_ROW_HEIGHT / 2,
          };
        }
        // Collapsed: page-type itself is one row
        const y = cursor + ROW_HEIGHT / 2 - ROW_HEIGHT / 2;
        cursor += ROW_HEIGHT;
        return {
          ...pt,
          expanded: false,
          y,
          yTop: y,
          yBot: y,
        };
      });

      const productBot = cursor - ROW_HEIGHT;
      const productY = ptLaidOut.length > 0
        ? (ptLaidOut[0].y + ptLaidOut[ptLaidOut.length - 1].y) / 2
        : productTop;

      return {
        ...prod,
        y: productY,
        yTop: ptLaidOut[0]?.y ?? productTop,
        yBot: ptLaidOut[ptLaidOut.length - 1]?.y ?? productTop,
        page_types: ptLaidOut,
      };
    });

    const totalHeight = cursor + BOTTOM_PAD;
    const rootY = laidOut.length > 0
      ? (laidOut[0].y + laidOut[laidOut.length - 1].y) / 2
      : TOP_PAD;
    return { products: laidOut, totalHeight, rootY };
  }, [products, open]);

  // Width must accommodate the longest page URL — cap at 1100 and let it scroll.
  const width = 1100;
  const height = Math.max(400, layout.totalHeight);

  if (products.length === 0) {
    return (
      <div style={{ padding: 24, color: '#6B7280', textAlign: 'center' }}>
        No products to plot — run the classifier first.
      </div>
    );
  }

  return (
    <div style={{
      border: '1px solid #E5E7EB', borderRadius: 8, background: '#FFFFFF',
      overflow: 'auto', maxHeight: 720,
    }}>
      <svg
        width={width}
        height={height}
        style={{ display: 'block', minWidth: '100%' }}
        role="img"
        aria-label="Content cluster dendrogram"
      >
        {/* Root node */}
        <g>
          <circle cx={COL_ROOT} cy={layout.rootY} r={5} fill="#003DA5" />
          <text
            x={COL_ROOT + 10}
            y={layout.rootY - 8}
            fontSize={13}
            fontWeight={700}
            fill="#003DA5"
          >
            {rootLabel}
          </text>
          <text
            x={COL_ROOT + 10}
            y={layout.rootY + 8}
            fontSize={11}
            fill="#6B7280"
          >
            {products.length} product{products.length === 1 ? '' : 's'}
          </text>
        </g>

        {/* Root → product connectors (one orthogonal elbow per product) */}
        {layout.products.length > 1 && (
          <line
            x1={COL_ROOT + 60}
            y1={layout.products[0].y}
            x2={COL_ROOT + 60}
            y2={layout.products[layout.products.length - 1].y}
            stroke="#CBD5E1"
            strokeWidth={1.5}
          />
        )}
        {layout.products.map((prod) => (
          <line
            key={`root-${prod.product}`}
            x1={COL_ROOT + 60}
            y1={prod.y}
            x2={COL_PRODUCT - 8}
            y2={prod.y}
            stroke="#CBD5E1"
            strokeWidth={1.5}
          />
        ))}
        {/* Stub from root circle to the vertical trunk */}
        <line
          x1={COL_ROOT + 6}
          y1={layout.rootY}
          x2={COL_ROOT + 60}
          y2={layout.rootY}
          stroke="#CBD5E1"
          strokeWidth={1.5}
        />

        {/* Products */}
        {layout.products.map((prod) => {
          const colour = PRODUCT_COLOURS[prod.product] || '#64748B';
          return (
            <g key={prod.product}>
              {/* Product node */}
              <circle cx={COL_PRODUCT} cy={prod.y} r={5} fill={colour} />
              <text
                x={COL_PRODUCT + 10}
                y={prod.y - 4}
                fontSize={FONT_PRODUCT}
                fontWeight={700}
                fill={colour}
              >
                {prod.label}
              </text>
              <text
                x={COL_PRODUCT + 10}
                y={prod.y + 12}
                fontSize={10}
                fill="#6B7280"
              >
                {prod.count} pages · {prod.page_types.length} page type
                {prod.page_types.length === 1 ? '' : 's'}
              </text>

              {/* Product → page-type connectors */}
              {prod.page_types.length > 1 && (
                <line
                  x1={COL_PRODUCT + 60}
                  y1={prod.page_types[0].y}
                  x2={COL_PRODUCT + 60}
                  y2={prod.page_types[prod.page_types.length - 1].y}
                  stroke={colour}
                  strokeOpacity={0.35}
                  strokeWidth={1.25}
                />
              )}
              <line
                x1={COL_PRODUCT + 6}
                y1={prod.y}
                x2={COL_PRODUCT + 60}
                y2={prod.y}
                stroke={colour}
                strokeOpacity={0.5}
                strokeWidth={1.5}
              />

              {prod.page_types.map((pt) => {
                const key = `${prod.product}:${pt.page_type}`;
                return (
                  <g key={key}>
                    {/* Horizontal stub into the page-type label */}
                    <line
                      x1={COL_PRODUCT + 60}
                      y1={pt.y}
                      x2={COL_PAGETYPE - 8}
                      y2={pt.y}
                      stroke={colour}
                      strokeOpacity={0.35}
                      strokeWidth={1.25}
                    />
                    {/* Page-type node — clickable to expand/collapse */}
                    <circle
                      cx={COL_PAGETYPE}
                      cy={pt.y}
                      r={4}
                      fill="#FFFFFF"
                      stroke={colour}
                      strokeWidth={1.5}
                      style={{ cursor: 'pointer' }}
                      onClick={() => toggle(key)}
                    />
                    <text
                      x={COL_PAGETYPE + 8}
                      y={pt.y - 2}
                      fontSize={FONT_PAGETYPE}
                      fontWeight={600}
                      fill="#1F2937"
                      style={{ cursor: 'pointer' }}
                      onClick={() => toggle(key)}
                    >
                      {pt.expanded ? '▾ ' : '▸ '}{pt.label}
                    </text>
                    <text
                      x={COL_PAGETYPE + 8}
                      y={pt.y + 11}
                      fontSize={10}
                      fill="#6B7280"
                      style={{ cursor: 'pointer' }}
                      onClick={() => toggle(key)}
                    >
                      {pt.count} page{pt.count === 1 ? '' : 's'}
                    </text>

                    {/* If expanded — draw page leaves */}
                    {pt.expanded && pt.pages.length > 0 && (
                      <>
                        {/* Vertical trunk through the children */}
                        {pt.pages.length > 1 && (
                          <line
                            x1={COL_PAGETYPE + 60}
                            y1={pt.yTop}
                            x2={COL_PAGETYPE + 60}
                            y2={pt.yBot}
                            stroke={colour}
                            strokeOpacity={0.25}
                            strokeWidth={1}
                          />
                        )}
                        {/* Stub from page-type into the trunk */}
                        <line
                          x1={COL_PAGETYPE + 5}
                          y1={pt.y}
                          x2={COL_PAGETYPE + 60}
                          y2={pt.y}
                          stroke={colour}
                          strokeOpacity={0.35}
                          strokeWidth={1}
                        />
                        {pt.pages.map((page, idx) => {
                          // Y of leaf row idx within this group
                          const leafY = pt.yTop + idx * PAGE_ROW_HEIGHT;
                          return (
                            <g key={page.url}>
                              <line
                                x1={COL_PAGETYPE + 60}
                                y1={leafY}
                                x2={COL_PAGE - 6}
                                y2={leafY}
                                stroke={colour}
                                strokeOpacity={0.25}
                                strokeWidth={1}
                              />
                              <circle
                                cx={COL_PAGE - 4}
                                cy={leafY}
                                r={2.5}
                                fill={colour}
                                opacity={0.7}
                              />
                              <a
                                href={page.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                <text
                                  x={COL_PAGE + 4}
                                  y={leafY + 4}
                                  fontSize={FONT_PAGE}
                                  fill="#003DA5"
                                  style={{ cursor: 'pointer' }}
                                >
                                  {(page.title || page.url).slice(0, 70)}
                                  {(page.title || page.url).length > 70 ? '…' : ''}
                                </text>
                              </a>
                              {/* Confidence pill at far right */}
                              <text
                                x={COL_PAGE + 4 + 460}
                                y={leafY + 4}
                                fontSize={10}
                                fill={confColour(page.confidence)}
                                fontWeight={600}
                              >
                                {Math.round(page.confidence * 100)}%
                              </text>
                            </g>
                          );
                        })}
                      </>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function confColour(value: number): string {
  if (value >= 0.85) return '#15803D';
  if (value >= 0.70) return '#854D0E';
  if (value >= 0.60) return '#9A3412';
  return '#6B7280';
}
