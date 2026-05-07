// _Placeholder.tsx — shared "coming soon" body for Day 0 route stubs.

interface PlaceholderProps {
  title: string;
  eta: string;
}

export default function Placeholder({ title, eta }: PlaceholderProps) {
  return (
    <div className="page-grid">
      <div className="row">
        <div className="card" style={{ padding: 'var(--pad)' }}>
          <div className="card-head">
            <h3>{title}</h3>
            <span className="muted-pill">{eta}</span>
          </div>
          <p className="text-muted">
            This screen is on the implementation plan. The shell, routing and
            design tokens are wired today; the page body lands when its
            backing API endpoints do. See
            <span className="mono"> docs/superpowers/specs/2026-05-06-lattice-seo-crawler-vertical-slice-design.md </span>
            §5.4 for the per-screen cut-list.
          </p>
        </div>
      </div>
    </div>
  );
}
