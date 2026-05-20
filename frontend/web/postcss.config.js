/** PostCSS config — wires Tailwind into the Vite build.
 *
 * Tailwind generates the utility CSS during build. autoprefixer adds
 * vendor prefixes for the small number of CSS properties that still
 * need them (`appearance`, `mask-image`, etc.). Vite picks this file
 * up automatically — no Vite config change required.
 */
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
