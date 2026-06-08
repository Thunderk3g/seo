# Term Insurance Page — Prioritized Lighthouse Fix List

**Page:** https://www.bajajlifeinsurance.com/term-insurance-plans.html
**Audited:** 2026-06-08 · **Source verified** against live `view-source` (980 KB HTML, 671 `<img>`, 662 `<a>`, 142 `<input>`, 49 scripts)
**Lighthouse scores:** Performance 85 · Accessibility 55 · Best Practices 77 · SEO (2 hard fails)

> All counts below are confirmed from the raw HTML, not the Lighthouse summary. Where the Lighthouse copy was misleading, the **Reality** note explains the real defect.

---

## Priority Legend
| Tier | Meaning | Owner |
|------|---------|-------|
| 🔴 P0 | Highest score + effort ratio. Template/HTML only, no backend. | Frontend / AEM authors |
| 🟠 P1 | Real defect, moderate effort or needs component change. | Frontend / Component dev |
| 🟡 P2 | Build / infra / design sign-off needed. | DevOps / Build / Design |

---

## 🔴 P0 — Do First (HTML/template only, no backend)

### 1. Render-blocking scripts — biggest performance lever
- **Confirmed:** 40 of 49 external scripts load synchronously (no `async`/`defer`); 54 `<link rel="stylesheet">`.
- **Impact:** Directly causes the 290 ms TBT + 3.3 s main-thread work. Fixing this alone can push Performance into the 90s.
- **Fix:** Add `defer` to all non-critical `<script src>`; `async` only for independent analytics/pixels. Audit the 54 stylesheets — inline critical CSS, lazy-load the rest.
```html
<!-- Before -->
<script src="/etc.clientlibs/.../chatbot.js"></script>
<!-- After -->
<script src="/etc.clientlibs/.../chatbot.js" defer></script>
```

### 2. Icon links have no accessible name
- **Confirmed:** 0 `aria-label` attributes across all 662 anchors. Every icon-only link (social, arrows, nav chevrons) is nameless to screen readers — the most accurate a11y finding.
- **Fix:** Add `aria-label` to every icon-only link.
```html
<!-- Before -->
<a href="/buy/term"><img src="arrow.svg" alt=""></a>
<!-- After -->
<a href="/buy/term" aria-label="Buy term insurance online">
  <img src="arrow.svg" alt="">
</a>
```

### 3. Duplicate IDs on real form fields
- **Confirmed:** `id="mobile"` ×3, `id="email"` ×3, `id="dob"` ×3, `id="calendarIcon"` ×4 — same quote-form fields repeated across multiple form instances on the page.
- **Impact:** Breaks `<label for>` association, autofill, and analytics. More serious than the FAQ-accordion guess.
- **Fix:** Suffix each form instance: `id="mobile-hero"`, `id="mobile-sticky"`, etc. Update matching `<label for>`.

### 4. Empty-ID language radios (cannot be labeled)
- **Confirmed:** 7 `<input>` with `id=""` — the language selector radios: `<input type="radio" name="English" id="">`.
- **Fix:** Give each a unique `id` and a `<label>` (or `aria-label`).
```html
<input type="radio" name="language" id="lang-en" value="en">
<label for="lang-en">English</label>
```

### 5. Search box has no label
- **Confirmed:** `id="searchtermsuggest"` uses placeholder only, no `<label>`.
- **Fix:** Add a visually-hidden label (`.sr-only`) tied via `for="searchtermsuggest"`. Placeholders do not count as labels.

---

## 🟠 P1 — Next (component / moderate effort)

### 6. Lazy-load images render without `alt`
- **Reality check:** Only 11 of 671 images truly lack `alt`; 52 correctly use `alt=""` (decorative). The "every image needs alt" claim was **overstated**.
- **Confirmed defect:** JS-injected placeholders render as bare `<img loading="lazy"/>` (no `alt`, no `src`) at audit time, before Angular/AEM hydrates them.
- **Fix:** Stamp `alt` in the template at render time, not after hydration. Decorative icons → `alt=""`; meaningful product/banner images → descriptive alt including product name + benefit.
- Verbatim offender: `<img loading="lazy" class="dots" src="/content/dam/balic-web/images/icon-4.png">` → add `alt=""`.

### 7. Uncrawlable / dead links
- **Reality check:** Real but small — 4 × `href="#"`, 1 × `href="javascript:void(0)"`, 2 anchors with no `href`. Out of 662 anchors (~7 total), **not** template-wide.
- **Fix:** Replace with real URLs (use AEM page paths / `routerLink`-equivalent so a real `href` renders in the DOM).

### 8. Non-descriptive link text
- **Fix:** Replace "click here" / "read more" / icon-only anchors with keyword-relevant text (e.g. "Compare all term insurance plans"). Doubles as internal-linking SEO signal.

### 9. Duplicate inline-SVG IDs
- **Confirmed:** `id="path-1-inside-1_1198_12070"` ×6, `id="paint0_linear_1198_12070"` ×6 — same SVG gradient/filter IDs stamped repeatedly. This is the actual "non-unique ARIA ID" trigger.
- **Fix:** Namespace SVG `<defs>` IDs per instance, or define once and reference via `<use href="#...">`.

---

## 🟡 P2 — Needs build / infra / design sign-off

### 10. Unused & legacy JavaScript
- 55 KiB unused JS + 6 KiB legacy polyfills (from Lighthouse).
- **Fix:** Tree-shake (import only used functions), `ng build --stats-json` + bundle analyzer, set `tsconfig target: ES2017`, trim `.browserslistrc` (drop IE11).

### 11. Network payload — 2.99 MB
- **Fix:** Serve WebP/AVIF + `srcset` (~75 KiB), add explicit `width`/`height` to prevent CLS, set long `Cache-Control` on static assets (~132 KiB) via dispatcher/CDN.

### 12. Color contrast (WCAG AA)
- Cannot verify from source — needs design audit with WebAIM Contrast Checker. Target 4.5:1 normal text, 3:1 large text.
- **Note:** Per brand guideline, palette stays Bajaj blue — adjust only the failing grays/secondary shades, not brand blue.

### 13. Security headers (Best Practices 77)
- Missing CSP, HSTS, COOP. Configure at CDN/load-balancer, not AEM content. Low SEO impact; DevOps ticket.

---

## Effort vs Impact Summary
| # | Fix | Effort | Score impact | Owner |
|---|-----|--------|-------------|-------|
| 1 | Defer/async 40 scripts | Med | ⬆⬆ Performance | Frontend |
| 2 | aria-label on icon links | Low | ⬆⬆ Accessibility | Frontend |
| 3 | Unique form-field IDs | Low | ⬆ Accessibility | Component dev |
| 4 | Fix empty-ID radios | Low | ⬆ Accessibility | Component dev |
| 5 | Label search box | Low | ⬆ Accessibility | Frontend |
| 6 | alt on lazy images | Low-Med | ⬆ A11y + SEO | Component dev |
| 7 | Fix ~7 dead links | Low | ⬆ SEO crawl | Frontend |
| 8 | Descriptive link text | Low | ⬆ SEO | Content |
| 9 | Namespace SVG IDs | Low-Med | ⬆ Accessibility | Component dev |
| 10 | Tree-shake JS | High | ⬆ Performance | Build |
| 11 | Image delivery + cache | Med | ⬆ Performance | DevOps |
| 12 | Contrast fixes | Med | ⬆ Accessibility | Design |
| 13 | Security headers | Low | Best Practices | DevOps |

## Recommended PR sequencing
1. **PR-1 (a11y + SEO quick wins):** items 2, 3, 4, 5, 7, 8 — pure template/HTML, no backend, biggest score jump per hour.
2. **PR-2 (performance):** item 1 (defer scripts) + item 6 (lazy alt) — needs regression testing.
3. **PR-3 (build/infra):** items 10, 11, 13 — build config + DevOps tickets.
4. **PR-4 (design):** item 12 — after design sign-off on failing shades.
