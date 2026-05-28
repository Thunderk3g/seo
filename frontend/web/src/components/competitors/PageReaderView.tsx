/**
 * PageReaderView — reconstruct the captured competitor/Bajaj/ad-hoc page
 * as a flowing reader-mode article using our own typography.
 *
 * The crawler captures the page in three separate fields that don't
 * preserve relative order:
 *   - headings_json   ordered list of {level, text, idx}
 *   - images_json     each image has a `section` field with the
 *                     nearest preceding heading text
 *   - body_text       flat visible-text dump, no markup positions
 *
 * Reconstruction strategy:
 *   1. Show H1 + meta description as the lede.
 *   2. Walk every heading in order, rendering at its real level.
 *   3. Under each heading, slot in any images whose `section` matches.
 *   4. Try to split body_text at every H2/H3 string we find (best-
 *      effort — heading text may have been rephrased in body). When a
 *      match is found, the body chunk goes under that heading.
 *      Unattached body text falls to a final "Continued" block.
 *
 * Operator gets the page roughly as a reader would see it. Not pixel-
 * perfect — we don't capture CSS, exact images-vs-text positions, or
 * embedded video — but close enough to compare structure side-by-side
 * with their live page in another tab.
 */
import { useMemo } from 'react';

type Heading = { level: number; text: string; idx: number };
type ImageRec = {
  src: string;
  alt?: string;
  section?: string;
  width?: number | string;
  height?: number | string;
};

interface ReaderData {
  title?: string;
  meta_description?: string;
  headings?: Heading[];
  h1_texts?: string[];
  images?: ImageRec[];
  body_text?: string;
  url?: string;
}

// Returns a stable key that survives the slicing.
function imgKey(img: ImageRec, idx: number): string {
  return `${idx}-${img.src}`;
}

interface Section {
  heading: Heading | null; // null = pre-heading lede
  bodyChunk: string;
  images: ImageRec[];
}

function splitBodyByHeadings(
  body: string,
  headings: Heading[],
): Map<number, string> {
  // Returns a map: heading idx → body chunk text. Heading idx -1 is the
  // intro chunk (before the first heading). Best-effort: walks the body
  // looking for each heading's text; everything between match N and
  // match N+1 belongs to heading N. Brittle if the page restates the
  // heading inside body paragraphs — we use the FIRST occurrence only.
  const result = new Map<number, string>();
  if (!body) return result;

  // Build (positionInBody, heading) pairs for headings that exist in body.
  const matches: Array<{ pos: number; heading: Heading }> = [];
  const used = new Set<number>(); // positions already consumed
  const lowerBody = body.toLowerCase();
  for (const h of headings) {
    const needle = (h.text || '').trim().toLowerCase();
    if (!needle || needle.length < 3) continue;
    // Find first occurrence not already consumed
    let from = 0;
    while (from < lowerBody.length) {
      const p = lowerBody.indexOf(needle, from);
      if (p === -1) break;
      if (!used.has(p)) {
        matches.push({ pos: p, heading: h });
        used.add(p);
        break;
      }
      from = p + 1;
    }
  }
  matches.sort((a, b) => a.pos - b.pos);

  // Pre-heading chunk (intro)
  if (matches.length > 0 && matches[0].pos > 0) {
    result.set(-1, body.slice(0, matches[0].pos).trim());
  } else if (matches.length === 0) {
    // No headings found in body — put everything into intro
    result.set(-1, body.trim());
    return result;
  }

  // Chunks per heading
  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].pos + matches[i].heading.text.length;
    const end = i + 1 < matches.length ? matches[i + 1].pos : body.length;
    const chunk = body.slice(start, end).trim();
    result.set(matches[i].heading.idx, chunk);
  }
  return result;
}

export default function PageReaderView({ data }: { data: ReaderData }) {
  const headings = useMemo<Heading[]>(
    () => (data.headings || []).filter((h) => h && (h.text || '').trim()),
    [data.headings],
  );

  const bodyChunks = useMemo(
    () => splitBodyByHeadings(data.body_text || '', headings),
    [data.body_text, headings],
  );

  // Index images by section text (lowercased + trimmed).
  const imagesBySection = useMemo(() => {
    const map = new Map<string, ImageRec[]>();
    for (const img of data.images || []) {
      const key = (img.section || '').trim().toLowerCase();
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(img);
    }
    return map;
  }, [data.images]);

  // Title block — prefer the explicit title; fall back to first H1.
  const title =
    (data.title || '').trim() ||
    (data.h1_texts && data.h1_texts[0]) ||
    '(no title)';

  const intro = bodyChunks.get(-1) || '';

  // Track which images we've used so a section's images don't reprint
  // under each subsequent heading.
  const usedImages = new Set<string>();
  const claimImages = (sectionText: string): ImageRec[] => {
    const matches = imagesBySection.get(sectionText.trim().toLowerCase()) || [];
    const out: ImageRec[] = [];
    for (let i = 0; i < matches.length; i++) {
      const k = imgKey(matches[i], i);
      if (usedImages.has(k)) continue;
      usedImages.add(k);
      out.push(matches[i]);
    }
    return out;
  };

  return (
    <article className="prose prose-sm max-w-none rounded-md border border-brand-border bg-card p-6 shadow-e1">
      {/* Title + meta */}
      <header className="mb-4 border-b border-brand-border pb-3">
        <h1 className="m-0 text-2xl font-bold text-brand-text">{title}</h1>
        {data.meta_description && (
          <p className="m-0 mt-2 italic text-brand-text-2">
            {data.meta_description}
          </p>
        )}
        {data.url && (
          <a
            href={data.url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 block break-all text-xs text-brand-text-3 hover:underline"
          >
            {data.url}
          </a>
        )}
      </header>

      {/* Intro / lede */}
      {intro && (
        <p className="mt-0 whitespace-pre-line text-sm leading-relaxed text-brand-text">
          {intro.slice(0, 1500)}
          {intro.length > 1500 ? '…' : ''}
        </p>
      )}

      {/* Walk headings in document order */}
      {headings.map((h) => {
        const tag = `h${Math.min(Math.max(h.level, 2), 6)}` as
          | 'h2'
          | 'h3'
          | 'h4'
          | 'h5'
          | 'h6';
        const sizeCls =
          h.level === 1
            ? 'text-xl font-bold mt-6'
            : h.level === 2
              ? 'text-lg font-semibold mt-5 border-b border-brand-border pb-1'
              : h.level === 3
                ? 'text-base font-semibold mt-4'
                : 'text-sm font-semibold mt-3 text-brand-text-2';
        const chunk = bodyChunks.get(h.idx) || '';
        const imgs = claimImages(h.text);
        const HTag = tag as keyof JSX.IntrinsicElements;
        return (
          <section key={h.idx} className="mt-2">
            <HTag className={`${sizeCls} text-brand-text`}>{h.text}</HTag>
            {chunk && (
              <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-brand-text">
                {chunk.slice(0, 1200)}
                {chunk.length > 1200 ? '…' : ''}
              </p>
            )}
            {imgs.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-3">
                {imgs.slice(0, 4).map((img, i) => (
                  <figure
                    key={imgKey(img, i)}
                    className="max-w-xs rounded border border-brand-border bg-brand-surface-2 p-1"
                  >
                    <img
                      src={img.src}
                      alt={img.alt || ''}
                      loading="lazy"
                      className="block max-h-40 w-auto rounded"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                    {img.alt && (
                      <figcaption className="mt-1 truncate text-[10px] text-brand-text-3">
                        {img.alt}
                      </figcaption>
                    )}
                  </figure>
                ))}
              </div>
            )}
          </section>
        );
      })}

      {/* Orphan images — captured under sections we couldn't map back
          (e.g. images whose nearest heading was filtered out). Render
          at the end as a thumbnail strip so the operator can still see
          the visual surface area. */}
      {(() => {
        const orphans: ImageRec[] = [];
        let idx = 0;
        for (const img of data.images || []) {
          const k = imgKey(img, idx++);
          if (!usedImages.has(k)) orphans.push(img);
        }
        if (orphans.length === 0) return null;
        return (
          <section className="mt-6 border-t border-brand-border pt-3">
            <h3 className="text-sm font-semibold text-brand-text-2">
              Other images on this page ({orphans.length})
            </h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {orphans.slice(0, 30).map((img, i) => (
                <figure
                  key={imgKey(img, i)}
                  className="w-32 rounded border border-brand-border bg-brand-surface-2 p-1"
                >
                  <img
                    src={img.src}
                    alt={img.alt || ''}
                    loading="lazy"
                    className="block h-20 w-full rounded object-cover"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none';
                    }}
                  />
                  {img.alt && (
                    <figcaption className="mt-1 truncate text-[10px] text-brand-text-3">
                      {img.alt}
                    </figcaption>
                  )}
                </figure>
              ))}
            </div>
          </section>
        );
      })()}
    </article>
  );
}
