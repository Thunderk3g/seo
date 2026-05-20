/** Tailwind config — Bajaj SEO dashboard (CommonJS).
 *
 * Uses .cjs to bypass jiti's ESM dynamic-import transpilation bug.
 * package.json has "type": "module" so plain .js files are ESM, but
 * Tailwind's loader can't handle top-level await in ESM configs.
 * CommonJS sidesteps the issue.
 *
 * Co-exists with the existing hand-rolled styles/lattice.css palette:
 *
 *   corePlugins.preflight: false
 *     Disables Tailwind's global CSS reset. lattice.css and all existing
 *     pages keep their current cascade. Tailwind utility classes only
 *     apply to elements that explicitly opt in (every new shadcn primitive
 *     does, every legacy page does not).
 *
 *   content: scoped to the src tree
 *     Vite picks up class names from this glob and only generates utilities
 *     that are referenced — keeps the production CSS small.
 *
 *   theme.extend.colors.brand
 *     Sourced verbatim from lattice.css :root --vars so new shadcn
 *     components inherit Bajaj brand without per-component overrides.
 *
 *   shadcn CSS variables
 *     `--background`, `--foreground`, `--primary`, etc. are also defined
 *     in `src/styles/tailwind.css` (the HSL forms shadcn expects) and
 *     mapped to the same Bajaj tokens.
 */
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{ts,tsx,js,jsx}',
  ],
  corePlugins: {
    preflight: false,
  },
  theme: {
    container: {
      center: true,
      padding: '1rem',
    },
    extend: {
      colors: {
        // Bajaj brand tokens (verified from src/styles/lattice.css :root)
        brand: {
          text: '#002c6e',
          'text-2': 'rgba(0, 44, 110, 0.78)',
          'text-3': 'rgba(0, 44, 110, 0.55)',
          'text-4': 'rgba(0, 44, 110, 0.35)',
          accent: '#0072ce',
          'accent-hover': '#005ba1',
          'accent-soft': 'rgba(0, 114, 206, 0.06)',
          'accent-glow': 'rgba(0, 114, 206, 0.15)',
          bg: '#f4f7fb',
          'bg-2': '#ffffff',
          'bg-3': '#eaf1fb',
          surface: '#ffffff',
          'surface-2': '#f4f7fb',
          'surface-3': '#e6eef9',
          border: 'rgba(0, 44, 110, 0.08)',
          'border-2': 'rgba(0, 44, 110, 0.16)',
        },
        severity: {
          error: '#d32f2f',
          'error-soft': 'rgba(211, 47, 47, 0.10)',
          warning: '#f59e0b',
          'warning-soft': 'rgba(245, 158, 11, 0.12)',
          notice: '#0072ce',
          success: '#1f8e3a',
          'success-soft': 'rgba(31, 142, 58, 0.10)',
        },

        // shadcn CSS-var bindings — values live in tailwind.css :root.
        // Components written for shadcn expect this exact key set.
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
      },
      borderRadius: {
        md: '10px',
        lg: '14px',
        xl: '18px',
      },
      boxShadow: {
        // Material-style elevation tier sourced from lattice.css
        e1: '0 1px 2px rgba(0, 44, 110, 0.04), 0 1px 3px rgba(0, 44, 110, 0.05)',
        e2: '0 2px 4px rgba(0, 44, 110, 0.06), 0 4px 12px rgba(0, 44, 110, 0.06)',
        e3: '0 4px 12px rgba(0, 44, 110, 0.07), 0 16px 32px rgba(0, 44, 110, 0.07)',
      },
      fontFamily: {
        sans: [
          'Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"',
          'Roboto', 'Helvetica', 'Arial', 'sans-serif',
        ],
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  plugins: [
    // tailwindcss-animate provides the keyframes shadcn primitives expect
    // for dropdown/popover open/close animations. Synchronous require()
    // works because this file is .cjs (CommonJS).
    require('tailwindcss-animate'),
  ],
};
