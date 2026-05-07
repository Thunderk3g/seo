// StatusBar.tsx — bottom status footer.
// Day 0: simple placeholder. The richer multi-segment version from
// .design-ref/project/app.jsx (last crawl time, crawl type, user agent…)
// arrives once those values are real (Day 1+).

export default function StatusBar() {
  return (
    <footer className="status-bar">
      <span>
        <span className="status-dot" /> Connected
      </span>
      <span className="text-muted">·</span>
      <span className="mono">v0.1.0-alpha</span>
      <span style={{ flex: 1 }} />
      <span className="status-online">
        <span className="status-dot" /> Shell ready
      </span>
    </footer>
  );
}
