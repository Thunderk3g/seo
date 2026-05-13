import { useState } from 'react';
import type { TreeNodeData } from '../api';
import type { BadgeTone } from '../format';

function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname + u.search;
    return path === '/' ? u.hostname : path;
  } catch {
    return url;
  }
}

function badgeTone(code: string): BadgeTone {
  if (!code) return 'muted';
  if (code.startsWith('2')) return 'ok';
  if (code.startsWith('3')) return 'info';
  if (code.startsWith('4') || code.startsWith('5')) return 'err';
  return 'muted';
}

export default function TreeNode({
  node,
  root = false,
  defaultOpen = false,
}: {
  node: TreeNodeData;
  root?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(root || defaultOpen);
  const hasChildren = !!node.children && node.children.length > 0;
  const more = node.total_children > (node.children?.length ?? 0);

  return (
    <div className={`tree-node ${root ? 'is-root' : ''}`}>
      <div className="tree-row">
        <button
          type="button"
          className="tree-toggle"
          onClick={() => hasChildren && setOpen(!open)}
          aria-label={open ? 'Collapse' : 'Expand'}
        >
          <span className="material-icons-outlined">
            {hasChildren ? (open ? 'expand_more' : 'chevron_right') : 'remove'}
          </span>
        </button>
        <span className={`badge ${badgeTone(node.status_code)}`}>{node.status_code || '—'}</span>
        <a className="tree-url mono" href={node.url} target="_blank" rel="noreferrer" title={node.url}>
          {root ? node.url : shortUrl(node.url)}
        </a>
        {node.title ? <span className="tree-title">{node.title}</span> : null}
        {node.total_children > 0 && (
          <span className="tree-count">
            {node.total_children}
            {more ? '+' : ''}
          </span>
        )}
      </div>
      {open && hasChildren && (
        <div className="tree-children">
          {node.children.map((c, i) => (
            <TreeNode key={`${c.url}-${i}`} node={c} />
          ))}
        </div>
      )}
    </div>
  );
}
