// NotFoundPage — catch-all 404 for unmatched routes. Uses the Bajaj
// error illustration at public/error-banner-img.svg. Brand palette stays
// Bajaj blue; branding stays "Bajaj Life Insurance".
import { Link } from 'wouter';

const BAJAJ_BLUE = '#005EAC';
const BAJAJ_NAVY = '#002c6e';

export default function NotFoundPage() {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        minHeight: '70vh',
        padding: 32,
      }}
    >
      <img
        src="/error-banner-img.svg"
        alt="Page not found"
        style={{ width: '100%', maxWidth: 480, height: 'auto', marginBottom: 24 }}
      />
      <div style={{ fontSize: 56, fontWeight: 800, color: BAJAJ_BLUE, lineHeight: 1 }}>
        404
      </div>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: BAJAJ_NAVY, margin: '12px 0 6px' }}>
        Page not found
      </h1>
      <p style={{ fontSize: 14, color: '#475569', maxWidth: 420, margin: '0 0 22px' }}>
        The page you’re looking for doesn’t exist or may have moved. Let’s get
        you back to the SEO Assistant.
      </p>
      <Link
        href="/"
        style={{
          display: 'inline-block',
          background: BAJAJ_BLUE,
          color: '#fff',
          fontSize: 14,
          fontWeight: 700,
          padding: '10px 22px',
          borderRadius: 8,
          textDecoration: 'none',
        }}
      >
        ← Back to Assistant
      </Link>
    </div>
  );
}
