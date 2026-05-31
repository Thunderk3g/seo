/**
 * Client-side export of a Content Writer v2 revamp draft.
 *
 * Dependency-free on purpose — no html-to-docx / jspdf / file-saver.
 * That keeps the Vite bundle small and avoids npm-install friction on
 * the corporate network:
 *   • HTML     — full standalone document (title/meta/JSON-LD + body).
 *   • Markdown — the body converted + structured FAQ/links/tech appendix.
 *   • Word     — an MS-Word-readable HTML .doc (Word opens HTML natively).
 *   • PDF      — opens a print window; the browser's "Save as PDF" yields
 *                a high-fidelity PDF rendered from the same HTML.
 */
import type { CWV2Revamp } from '../api/hooks/useContentWriter';

function escapeHtml(s: string): string {
  return (s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeAttr(s: string): string {
  return escapeHtml(s).replace(/"/g, '&quot;');
}

const PAGE_STYLE = `
body{font-family:Arial,Helvetica,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;line-height:1.65;color:#1a1a1a}
h1,h2,h3,h4{color:#0b3d91;line-height:1.3}
h1{font-size:30px}h2{font-size:23px;margin-top:32px}h3{font-size:18px}
table{border-collapse:collapse;width:100%;margin:16px 0}
th,td{border:1px solid #cbd5e1;padding:8px;text-align:left;vertical-align:top}
th{background:#eef2ff}
header{border-bottom:3px solid #0b3d91;padding-bottom:12px;margin-bottom:20px}
header nav a{margin-right:14px;color:#0b3d91;text-decoration:none;font-weight:600}
footer{border-top:1px solid #cbd5e1;margin-top:36px;padding-top:12px;font-size:12px;color:#64748b}
a{color:#0b3d91}
ul,ol{padding-left:22px}
`.trim();

/** A complete, standalone HTML document built from the revamp draft. */
export function buildFullHtml(revamp: CWV2Revamp, ourUrl: string): string {
  const title = revamp.title?.text || revamp.h1?.text || 'Bajaj Life Insurance';
  const meta = revamp.meta_description?.text || '';
  const body = revamp.body_html || '';
  const ld = (revamp.json_ld_blocks || [])
    .map(
      (b) =>
        `<script type="application/ld+json">${JSON.stringify(
          b.json_ld,
        )}</script>`,
    )
    .join('\n');
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<meta name="description" content="${escapeAttr(meta)}">
${ourUrl ? `<link rel="canonical" href="${escapeAttr(ourUrl)}">` : ''}
<style>${PAGE_STYLE}</style>
${ld}
</head>
<body>
${body}
</body>
</html>`;
}

/** Lightweight HTML → Markdown for the body. Not a full parser — covers
 * the tags the writer emits (headings, paragraphs, lists, links, tables,
 * emphasis) and strips the rest. */
function htmlToMarkdown(html: string): string {
  let s = html || '';
  s = s.replace(/<\s*br\s*\/?>/gi, '\n');
  s = s.replace(/<h1[^>]*>/gi, '\n\n# ');
  s = s.replace(/<h2[^>]*>/gi, '\n\n## ');
  s = s.replace(/<h3[^>]*>/gi, '\n\n### ');
  s = s.replace(/<h4[^>]*>/gi, '\n\n#### ');
  s = s.replace(/<li[^>]*>/gi, '\n- ');
  s = s.replace(
    /<a [^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi,
    (_m, href, txt) => `[${txt.replace(/<[^>]+>/g, '').trim()}](${href})`,
  );
  s = s.replace(/<\/(strong|b)>/gi, '**').replace(/<(strong|b)>/gi, '**');
  s = s.replace(/<\/(em|i)>/gi, '_').replace(/<(em|i)>/gi, '_');
  s = s.replace(/<\/(p|div|section|tr|ul|ol|h[1-6]|header|footer|table)>/gi, '\n\n');
  s = s.replace(/<[^>]+>/g, '');
  s = s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ');
  return s.replace(/\n{3,}/g, '\n\n').trim();
}

/** Markdown of the full revamp: body + FAQ + internal-link + tech appendix. */
export function buildMarkdown(revamp: CWV2Revamp): string {
  const out: string[] = [];
  if (revamp.title?.text) out.push(`# ${revamp.title.text}`);
  if (revamp.meta_description?.text)
    out.push(`> ${revamp.meta_description.text}`);
  out.push('');
  out.push(htmlToMarkdown(revamp.body_html || ''));
  if (revamp.faqs?.length) {
    out.push('\n## Frequently Asked Questions\n');
    for (const f of revamp.faqs) {
      out.push(`### ${f.question}`);
      out.push(f.answer);
      out.push('');
    }
  }
  if (revamp.internal_links_plan?.length) {
    out.push('\n## Internal Linking Plan\n');
    for (const l of revamp.internal_links_plan) {
      out.push(`- [${l.anchor}](${l.target_url}) — ${l.section}${l.rationale ? ` — ${l.rationale}` : ''}`);
    }
  }
  if (revamp.tech_recommendations?.length) {
    out.push('\n## Technical SEO Recommendations\n');
    for (const r of revamp.tech_recommendations) out.push(`- ${r}`);
  }
  return out.join('\n');
}

function saveBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function slugFromUrl(url: string): string {
  try {
    const u = new URL(url);
    const last = u.pathname.split('/').filter(Boolean).pop() || u.hostname;
    return (last.replace(/\.[a-z]+$/i, '') || 'revamp').slice(0, 60);
  } catch {
    return 'revamp';
  }
}

export function downloadHtml(revamp: CWV2Revamp, ourUrl: string): void {
  const name = `${slugFromUrl(ourUrl)}-revamp.html`;
  saveBlob(name, new Blob([buildFullHtml(revamp, ourUrl)], { type: 'text/html' }));
}

export function downloadMarkdown(revamp: CWV2Revamp, ourUrl: string): void {
  const name = `${slugFromUrl(ourUrl)}-revamp.md`;
  saveBlob(name, new Blob([buildMarkdown(revamp)], { type: 'text/markdown' }));
}

export function downloadDoc(revamp: CWV2Revamp, ourUrl: string): void {
  // Word opens HTML-based .doc files natively, preserving headings,
  // tables and lists — a robust zero-dependency path to a .doc.
  const header =
    '<html xmlns:o="urn:schemas-microsoft-com:office:office" ' +
    'xmlns:w="urn:schemas-microsoft-com:office:word" ' +
    'xmlns="http://www.w3.org/TR/REC-html40"><head><meta charset="utf-8">' +
    `<style>${PAGE_STYLE}</style></head><body>`;
  const doc = header + (revamp.body_html || '') + '</body></html>';
  const name = `${slugFromUrl(ourUrl)}-revamp.doc`;
  saveBlob(name, new Blob(['﻿', doc], { type: 'application/msword' }));
}

export function exportPdf(revamp: CWV2Revamp, ourUrl: string): void {
  // Open the full HTML in a new window and trigger the print dialog —
  // "Save as PDF" produces a high-fidelity PDF with zero dependencies.
  const html = buildFullHtml(revamp, ourUrl);
  const w = window.open('', '_blank');
  if (!w) {
    alert('Please allow pop-ups to export the PDF.');
    return;
  }
  w.document.open();
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => {
    try {
      w.print();
    } catch {
      /* user can print manually */
    }
  }, 500);
}
