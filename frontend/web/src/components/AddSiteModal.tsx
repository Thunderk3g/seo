// AddSiteModal — small form to register a new website.
//
// Styling fallback: lattice.css does NOT define any modal/dialog/overlay
// classes, and .design-ref/project/styles.css has none either. Per the
// Stream E spec, when no suitable modal styling exists we render the form
// inline (as an expanded panel) instead of inventing new CSS. The host
// (Topbar or Sidebar) controls when this component is mounted, and on
// success it auto-closes via the `onClose` callback.
//
// We re-use the existing `.proj-menu` panel + `.url-field` input + `.btn`
// classes already shipped by lattice.css so the look matches the shell.

import { useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../api/client';
import type { DrfFieldErrors } from '../api/types';
import { useCreateWebsite } from '../api/hooks/useCreateWebsite';
import Icon from './icons/Icon';

interface AddSiteModalProps {
  onClose: () => void;
}

function extractFieldErrors(err: unknown): DrfFieldErrors | null {
  if (!(err instanceof ApiError) || err.status !== 400) return null;
  const body = err.body;
  if (!body || typeof body !== 'object') return null;
  // DRF sometimes returns { detail: "..." } even with 400; treat that as
  // a non-field error so the caller can show it under the form.
  return body as DrfFieldErrors;
}

export default function AddSiteModal({ onClose }: AddSiteModalProps) {
  const [domain, setDomain] = useState('');
  const [name, setName] = useState('');
  const create = useCreateWebsite();

  const fieldErrors = extractFieldErrors(create.error);
  const domainError = fieldErrors?.domain?.[0];
  const nameError = fieldErrors?.name?.[0];
  const detailError =
    fieldErrors && Array.isArray((fieldErrors as Record<string, unknown>).detail)
      ? ((fieldErrors as unknown as { detail: string[] }).detail[0] ?? null)
      : create.error instanceof ApiError && !fieldErrors
        ? create.error.message
        : null;

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = domain.trim();
    if (!trimmed) return;
    create.mutate(
      { domain: trimmed, name: name.trim() || undefined },
      { onSuccess: () => onClose() }
    );
  }

  return (
    <div
      className="proj-menu"
      style={{ padding: 10, gap: 8, display: 'flex', flexDirection: 'column' }}
    >
      <div className="sidebar-section-title" style={{ padding: 0 }}>
        Register a site
      </div>
      <form
        onSubmit={handleSubmit}
        style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
      >
        <div>
          <div className="url-field">
            <Icon name="globe" size={14} />
            <input
              autoFocus
              type="text"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="https://example.com"
              aria-label="Domain"
              aria-invalid={Boolean(domainError) || undefined}
            />
          </div>
          {domainError && (
            <div
              role="alert"
              style={{
                color: 'var(--error, #f87171)',
                fontSize: 11,
                marginTop: 4,
                paddingLeft: 4,
              }}
            >
              {domainError}
            </div>
          )}
        </div>
        <div>
          <div className="url-field">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Display name (optional)"
              aria-label="Name"
              aria-invalid={Boolean(nameError) || undefined}
            />
          </div>
          {nameError && (
            <div
              role="alert"
              style={{
                color: 'var(--error, #f87171)',
                fontSize: 11,
                marginTop: 4,
                paddingLeft: 4,
              }}
            >
              {nameError}
            </div>
          )}
        </div>
        {detailError && (
          <div
            role="alert"
            style={{
              color: 'var(--error, #f87171)',
              fontSize: 11,
              paddingLeft: 4,
            }}
          >
            {detailError}
          </div>
        )}
        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button
            type="button"
            className="btn ghost"
            onClick={onClose}
            disabled={create.isPending}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn primary"
            disabled={create.isPending || !domain.trim()}
          >
            <Icon name="plus" size={11} />
            <span>{create.isPending ? 'Adding…' : 'Add site'}</span>
          </button>
        </div>
      </form>
    </div>
  );
}
