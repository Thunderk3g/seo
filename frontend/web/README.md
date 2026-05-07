# Lattice Web (frontend/web)

Vite + React 18 + TypeScript scaffold for the Lattice SEO Crawler dashboard.

## Setup

```bash
npm install
npm run dev        # starts Vite on http://localhost:5173, proxies /api -> :8000
npm run typecheck  # tsc --noEmit
npm run build      # tsc && vite build (outputs dist/)
npm run preview    # serve built dist/
```

`npm run generate-types` is wired but stubbed; the DRF schema endpoint will be
exposed in a later stream — see `scripts/generate-types.mjs`.
