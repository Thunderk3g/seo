// Lightweight markdown renderer.
//
// We don't pull in react-markdown to keep the bundle small. This
// covers what the chat assistant actually emits: headings, bullet /
// numbered lists, bold / italic, inline code, fenced code blocks, and
// links. Everything else falls through as text. All input is HTML-
// escaped first; the parser only re-introduces the explicitly handled
// tags.

import { type ReactNode } from 'react';

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function inlineFmt(s: string): string {
  // Order matters: code first so its content isn't re-interpreted.
  let out = s.replace(
    /`([^`]+)`/g,
    (_, c) => `<code>${c}</code>`
  );
  out = out.replace(
    /\*\*([^*]+)\*\*/g,
    '<strong>$1</strong>'
  );
  out = out.replace(
    /(^|[^*])\*([^*\s][^*]*?)\*/g,
    '$1<em>$2</em>'
  );
  out = out.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_, label, href) =>
      `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`
  );
  return out;
}

interface Block {
  kind: 'h1' | 'h2' | 'h3' | 'p' | 'ul' | 'ol' | 'pre' | 'hr';
  text?: string;
  items?: string[];
  lang?: string;
}

function parseBlocks(src: string): Block[] {
  const escaped = escapeHtml(src);
  const lines = escaped.split(/\r?\n/);
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    // Fenced code block.
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      const lang = fence[1] || '';
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      i++; // consume closing fence
      blocks.push({ kind: 'pre', text: buf.join('\n'), lang });
      continue;
    }
    // Horizontal rule.
    if (/^---+\s*$/.test(line)) {
      blocks.push({ kind: 'hr' });
      i++;
      continue;
    }
    // Headings.
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      const kind = (level === 1 ? 'h1' : level === 2 ? 'h2' : 'h3') as
        | 'h1' | 'h2' | 'h3';
      blocks.push({ kind, text: h[2] });
      i++;
      continue;
    }
    // Bullet list.
    if (/^[*-]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[*-]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[*-]\s+/, ''));
        i++;
      }
      blocks.push({ kind: 'ul', items });
      continue;
    }
    // Numbered list.
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ''));
        i++;
      }
      blocks.push({ kind: 'ol', items });
      continue;
    }
    // Paragraph: gather until blank line.
    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,3}\s|[*-]\s|\d+\.\s|---+\s*$|```)/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push({ kind: 'p', text: buf.join(' ') });
  }
  return blocks;
}

export function Markdown({ source }: { source: string }): ReactNode {
  const blocks = parseBlocks(source || '');
  return (
    <div className="chat-md">
      {blocks.map((b, idx) => {
        switch (b.kind) {
          case 'h1':
            return (
              <h1
                key={idx}
                dangerouslySetInnerHTML={{ __html: inlineFmt(b.text || '') }}
              />
            );
          case 'h2':
            return (
              <h2
                key={idx}
                dangerouslySetInnerHTML={{ __html: inlineFmt(b.text || '') }}
              />
            );
          case 'h3':
            return (
              <h3
                key={idx}
                dangerouslySetInnerHTML={{ __html: inlineFmt(b.text || '') }}
              />
            );
          case 'p':
            return (
              <p
                key={idx}
                dangerouslySetInnerHTML={{ __html: inlineFmt(b.text || '') }}
              />
            );
          case 'ul':
            return (
              <ul key={idx}>
                {(b.items || []).map((item, j) => (
                  <li
                    key={j}
                    dangerouslySetInnerHTML={{ __html: inlineFmt(item) }}
                  />
                ))}
              </ul>
            );
          case 'ol':
            return (
              <ol key={idx}>
                {(b.items || []).map((item, j) => (
                  <li
                    key={j}
                    dangerouslySetInnerHTML={{ __html: inlineFmt(item) }}
                  />
                ))}
              </ol>
            );
          case 'pre':
            return (
              <pre key={idx} data-lang={b.lang || undefined}>
                <code>{(b.text || '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')}</code>
              </pre>
            );
          case 'hr':
            return <hr key={idx} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
