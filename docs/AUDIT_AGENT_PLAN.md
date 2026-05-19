# Audit Agent — Plan & Specification

**Date:** 2026-05-20
**Companion docs:** `PRODUCTION_READINESS_AUDIT.md` (current state), `PROPOSED_CHANGES.md` (committed roadmap)
**Authored from chat with:** ai.marketing@bajajlife.com

---

## 1. Philosophy — Recommendations, Not Scores

This audit agent is deliberately **not** a scorecard generator.

A score like "67/100" tells the operator nothing they can act on. The agent is built to behave like a human SEO consultant who has spent hours reading every page of the site: it produces **specific, page-specific, actionable change requests** — not numbers.

**Bad output (what we are NOT building):**
> Content quality: 70/100. Schema coverage: 45/100. CWV: 54/100.

**Good output (what we ARE building):**
> On `https://www.bajajlifeinsurance.com/term-insurance-plans.html`, the first paragraph is 12 words and reads "Buy term insurance from Bajaj Life Insurance — get the best term plan online." This is marketing copy. AI search engines (Perplexity, ChatGPT, Gemini) lift the first dense paragraph as the answer summary. Replace with a 50-80 word definition: "Term insurance is the simplest form of life insurance: a pure-protection policy that pays a lump sum to your family if you die during the policy term…" Competitor `hdfclife.com/term-insurance-plans/` does exactly this and gets cited by Perplexity 73% of the time for `what is term insurance`.

Every finding the agent produces follows that shape: **location → current state → recommended change → why → competitor evidence**.

---

## 2. What the Agent Audits — Parameters

Five **audit lenses**. The agent looks at every page through each lens and emits findings only when something is materially actionable. No padding.

### Lens A — Content Quality

Does the content actually answer the search intent of the user typing the query?

| Audit parameter | What the agent checks | When it emits a finding |
|---|---|---|
| Lead paragraph definition | First `<p>` is 40-200 words and defines the topic | Missing or thin lead paragraph |
| Search intent match | Does the page resolve the user's actual question, or just sell? | Page is sales-led but query is informational |
| Topical depth | Word count vs competitor median for the same query | We're <70% of rival median |
| Freshness | Visible "last updated" date OR `dateModified` schema | Missing AND content is >6 months old |
| Entity coverage | Named entities (people, products, places) vs competitor | Competitor mentions key entities we don't |
| Statistics & sources | Numeric data with cited sources | <2 stats on a 1000+ word page |
| Internal authority cues | "X years in business", "Y crore claims paid", certifications | Missing where competitor has them |

### Lens B — Structural & Technical

Can search engines and AI assistants parse the page?

| Parameter | Check | Finding trigger |
|---|---|---|
| H1 presence + uniqueness | Exactly one H1, distinct from title | 0 or >1 H1; H1 == title verbatim |
| Heading hierarchy | H2/H3 nesting follows content flow | Skipped levels (H2 → H4) or no H2s on a long page |
| Query-style H2s | H2s phrased as the questions users type | <3 question-style H2s on knowledge pages |
| FAQ block | FAQPage schema OR ≥3 question-style H2/details | Missing on a high-intent page where competitors have it |
| Schema coverage | JSON-LD blocks present and relevant to page type | Product page without Product schema; FAQ-intent page without FAQPage |
| Schema diversity | Multiple linked types (Article + Person + BreadcrumbList) | Single bare type only |
| Image alt text | ≥70% of `<img>` have non-empty alt | Below threshold |
| Internal link density | ≥3 internal links to topic-related pages | Page is orphaned or under-linked |
| Canonical | Self-canonical OR clear cross-canonical | Canonical → 404 / external / inconsistent |

### Lens C — Performance & Core Web Vitals

Will users actually wait for this page to load? Google's CWV is a confirmed ranking factor since 2021.

| Parameter | Check | Finding trigger |
|---|---|---|
| Mobile LCP (CrUX p75) | ≤2500 ms | >4000 critical, >2500 warning |
| Mobile CLS (CrUX p75) | ≤0.1 | >0.25 critical, >0.1 warning |
| Mobile INP (CrUX p75) | ≤200 ms | >500 critical, >200 warning |
| Largest element identification | What's the LCP element? | Hero image >300KB; web font blocking render |
| Image format | WebP / AVIF for hero + above-fold | JPEG/PNG above-fold |
| Image lazy-loading | Below-fold images have `loading=lazy` | Missing |
| JS execution time | Lighthouse TBT | >300 ms |

### Lens D — AI / Generative Engine Optimization (GEO)

Will ChatGPT / Claude / Perplexity / Gemini cite this page when answering a relevant question?

| Parameter | Check | Finding trigger |
|---|---|---|
| Answer-extractable lead | First paragraph reads as a standalone answer | Marketing-led opener |
| Question-as-heading | H2/H3 phrased as queries | Generic "Features", "Benefits" |
| Self-contained answer blocks | H2 followed by 40-80 word paragraph | Long rambling sections without anchor answers |
| Definition presence | Topic defined within first 100 words | No clear definition |
| Source citations | Inline citations or "according to" with hyperlinks | Claims without sources |
| llms.txt published | site root has `/llms.txt` | Competitors have it, we don't |
| AI citation share | Brand mention rate across LLM probes (Gemini, Perplexity, etc.) | <33% citation rate for high-intent queries |
| Author / Person schema | E-E-A-T signal | Missing on long-form content |

### Lens E — Competitive Gap

Where do we lag the top 3 pages for the same query, and what specifically would we have to change to match them?

| Parameter | Check | Finding trigger |
|---|---|---|
| SERP position vs rivals | Where do we rank for the page's target keyword | Position ≥ 6 while competitor at position 1-3 |
| Featured snippet ownership | Are we the snippet for this query? | Competitor owns it; we don't |
| AI Overview citations | Are we cited in Google's AI Overview for this query? | Competitor cited; we're not |
| PAA presence | Are we surfaced in People Also Ask for adjacent questions? | Missing |
| Content depth gap | Word count delta vs top-3 average | <70% of top-3 average |
| Page-type coverage | Do competitors have a page-type we don't (comparison, calculator, FAQ)? | Two or more rivals have it |
| Internal link share | How many of our pages link here vs how many of theirs link to their equivalent | Significant gap |
| Backlink gap (when SEMrush backlinks wired) | Referring domains vs competitor | Significantly lower |

---

## 3. Suggestion Categories — Types of Changes the Agent Recommends

Every finding belongs to one of these 10 categories. The frontend can filter by category so the content team can batch similar fixes:

| Category | Example recommendation |
|---|---|
| `content_rewrite` | "Replace the first paragraph with a 60-word definition starting with 'Term insurance is…'" |
| `content_add` | "Add an FAQ section with these 5 questions extracted from People Also Ask: …" |
| `structural` | "Convert H2 'Plan Features' into a question: 'What does Bajaj Life Term Plan cover?'" |
| `schema` | "Add Product schema with `offers`, `aggregateRating`, and `brand` fields. Code: …" |
| `internal_link` | "Add internal links from this page to /term-insurance-tax-benefits and /claim-settlement-ratio" |
| `image` | "Hero image is 480KB JPEG. Convert to WebP, target <100KB. Add `loading=lazy` to all images below the fold." |
| `meta_tag` | "Meta description is 187 chars — Google will truncate. Shorten to ≤160 chars while keeping the keyword in the first 100 chars." |
| `freshness` | "Add visible 'Last updated: May 2026' below the title. Add `dateModified` in Article schema." |
| `ai_geo` | "Add llms.txt at /llms.txt. Add author byline + Person schema. Add inline source citations for the claim '99.33% claim settlement'." |
| `page_decision` | "This page cannibalises /term-insurance-plans.html. Recommend: 301 redirect to the parent OR rewrite as a deep-dive sub-topic page." |

---

## 4. Output Schema — What One Finding Looks Like

Every finding is a row in the `PageAuditFinding` table with this shape:

```python
class PageAuditFinding:
    audit_run_id: UUID          # which audit run produced it
    url: str                    # our page being audited
    lens: str                   # content_quality | structural | performance | ai_geo | competitive
    category: str               # content_rewrite | schema | image | ... (the 10 categories)
    location: str               # "first paragraph" | "H2 #3" | "Product schema block" | "meta description"
    current_state: str          # verbatim quote of what's there now
    recommended_change: str     # the drafted replacement
    reason: str                 # 2-3 sentence why
    competitor_evidence: dict   # {"url": "...", "excerpt": "...", "why_better": "..."}
    priority: str               # high | medium | low
    effort: str                 # minutes | hours | days
    status: str                 # open | implemented | skipped | superseded
    created_at: datetime
    implemented_at: datetime | null
```

The `status` field makes this a **monitor**, not just an auditor: when an operator marks `implemented`, the next audit run verifies the change is actually live on the page.

---

## 5. System Prompts — 6 Variations

Below are 6 system-prompt drafts the agent can use. Each tunes the agent to a different audit personality. **Recommended default: Prompt 1 (Strict Consultant)** — it produces the most actionable output. The others are alternates for specific use cases.

### Prompt 1 — The Strict Consultant (RECOMMENDED DEFAULT)

```
You are a senior SEO consultant performing a manual audit of one page of
the Bajaj Life Insurance website. You have full access to the page's
content, performance metrics, search-intent data from Google Search
Console, the top 3 ranking competitors for the page's primary keyword,
and AI-search visibility data.

Your job is to output a list of SPECIFIC, PAGE-SPECIFIC change
recommendations. Each recommendation must follow this schema exactly:

  - location: the precise element (e.g., "first paragraph", "H2 #3",
    "meta description", "Product schema block")
  - current_state: the verbatim current content, quoted
  - recommended_change: the drafted replacement, ready for the content
    team to paste
  - reason: 2-3 sentences explaining the SEO or GEO rationale, citing
    specific data signals
  - competitor_evidence: name a top-ranking competitor URL that already
    does this, and quote the relevant excerpt
  - category: one of {content_rewrite, content_add, structural, schema,
    internal_link, image, meta_tag, freshness, ai_geo, page_decision}
  - priority: high | medium | low
  - effort: minutes | hours | days

Rules of engagement:
1. NEVER recommend "improve the content" or other vague edits. Every
   recommendation must be concrete enough that a content writer could
   implement it without follow-up questions.
2. If the page is fundamentally healthy and only needs minor work,
   output at most 2 recommendations. Do not pad.
3. Prefer changes that move organic rank or AI citation share over
   cosmetic changes.
4. When drafting replacement content, match the existing voice — Bajaj
   Life Insurance is professional but approachable; avoid jargon.
5. Use real numbers from the dossier. If competitor X has FAQ coverage
   on 87% of pages while we have 32%, cite those numbers.
6. If a recommendation requires data you don't have, mark it as
   "needs verification" and skip it rather than guessing.
7. Output ONLY the JSON list. No preamble, no postscript.
```

### Prompt 2 — The Competitive Auditor

Leads every recommendation with "what the competitor does better". Use when the operator wants a competitive-pressure narrative.

```
You are an SEO competitive analyst. Your audit philosophy: for every
page on bajajlifeinsurance.com, study the top 3 ranking competitors
for that page's primary keyword, identify exactly what they do that we
don't, and write a recommendation that closes that specific gap.

Lead every recommendation with the competitor observation, then the
gap, then our specific fix. Schema as in Prompt 1 but with an extra
field: competitor_advantage (1 sentence stating what specifically
makes their version better).

Do not recommend anything our top-3 competitors don't already do.
Aspiration matters less than parity with proven winners.
```

### Prompt 3 — The GEO / AI-First Auditor

Prioritises citation-worthiness over traditional SEO. Use when the operator's goal is "be the source that ChatGPT cites".

```
You are an expert in Generative Engine Optimization. You audit pages
specifically for AI-search citation worthiness — how likely is this
page to be cited by ChatGPT, Claude, Perplexity, or Gemini when a user
asks about its topic?

Filter your recommendations to AI-search-relevant changes only:
  - Lead paragraph as a self-contained answer (40-200 words, defines
    the topic, includes price-anchors and proof-points)
  - Question-style H2s matching real user queries
  - Self-contained answer blocks (H2 + 40-80 word answer)
  - Inline source citations for any factual claim
  - Author byline + Person schema
  - Visible last-updated date + dateModified schema
  - FAQPage schema with question-style headings
  - llms.txt at site root

For each recommendation, cite the Princeton GEO research finding
(stats give +37% citation lift, etc.) where relevant. Same output
schema as Prompt 1.
```

### Prompt 4 — The Senior Strategist

Outputs FEWER findings, each high-impact, tied to business goals. Use for executive-level review.

```
You are a head of SEO presenting an audit to the CMO. For each page,
output AT MOST 3 recommendations — the three that will most move the
needle on (a) organic traffic, (b) lead conversion, or (c) brand
authority in AI search.

Each recommendation must include a fourth field: business_impact —
one sentence quantifying the expected effect ("This page receives
9800 impressions/month at position 14. Implementing this change is
likely to move it to page 1 based on the precedent of [competitor]
who made the equivalent change in Q3 2025.").

Skip pages that are healthy. Quality over volume.
```

### Prompt 5 — The Technical SEO Auditor

Focused on schema, indexability, CWV, structured data. Use when content is fine but engineering needs a checklist.

```
You are a technical SEO auditor. Your audit is restricted to
machine-readable signals: schema markup, canonicalisation, robots
directives, Core Web Vitals, indexability, structured data validity,
sitemap inclusion.

Skip content-quality and prose recommendations entirely — those are
out of scope. Focus exclusively on what an engineer would have to
implement in HTML, schema JSON-LD, server config, or asset
optimisation.

Same output schema as Prompt 1.
```

### Prompt 6 — The Content Architect

Focused on content depth, intent match, topical authority. Use when SEO infrastructure is solid but content is thin.

```
You are a content strategist for a life-insurance brand. Your audit
is restricted to content-level decisions: what to write, what to
remove, what to consolidate, how to phrase, what entities to cover.

Skip technical, schema, image-optimisation, and CWV findings entirely
— another audit covers those. Focus on:
  - Is the content depth right for the query intent?
  - Are the right entities covered (insurance terms, riders, tax
    sections, claim processes)?
  - Is the page's tone right for its audience (first-time buyer vs
    NRI vs HNI)?
  - Should this page exist at all, or is it cannibalising another?

Same output schema as Prompt 1, with one extra field: content_intent
(transactional | informational | navigational | comparison | thin).
```

---

## 6. Required API Keys

The audit agent needs different keys depending on which features you turn on. Costs are rough monthly estimates assuming 100 pages audited weekly (~400 pages/month).

### 6.1 Keys we already have set in `.env`

| Key | Status | Required for | Cost / quota |
|---|---|---|---|
| `GROQ_API_KEY` | ✅ Set | LLM batch grading (audit Prompt 1 across all pages) | Free tier sufficient for ~400 pages/month; 0.001 USD/page if paid |
| `SEMRUSH_API_KEY` | ✅ Set | Search intent data, competitor discovery, keyword data | 7-day cache reduces re-bills; ~10k SEMrush units/month |
| `SERPAPI_API_KEY` | ✅ Set | SERP top-3, AI Overview, PAA, featured snippet | 250 searches/month free tier — INSUFFICIENT for weekly audits; upgrade to Developer ($75/mo, 5k searches) |
| `GOOGLE_API_KEY` | ✅ Set | Gemini AI-visibility probe | Free tier; ~$0.10/month at our usage |
| `PSI_SERVICE_ACCOUNT_JSON` | ✅ Set | Core Web Vitals lab + field data | 25k calls/day free |

### 6.2 Keys empty in `.env` — needed for cross-LLM AI-visibility comparison

These directly affect Lens D (AI/GEO) findings. With only Gemini active today, we can't tell you "your page is cited by ChatGPT but not Claude" — we only have 1/5 of the signal.

| Key | What it unlocks | Cost / month for our usage |
|---|---|---|
| `OPENAI_API_KEY` | ChatGPT brand-citation probe + premium audit grading (GPT-4o on top-20 pages) | ~$5-15/month |
| `ANTHROPIC_API_KEY` | Claude brand-citation probe + premium audit grading (Sonnet 4.6) | ~$3-10/month |
| `PERPLEXITY_API_KEY` | Perplexity brand-citation probe (free signal, paid query model) | ~$3/month |
| `XAI_API_KEY` | Grok brand-citation probe | ~$3/month |

**Recommendation:** Start with `ANTHROPIC_API_KEY` (best signal-to-cost ratio for cross-checking Groq's batch audits) and `OPENAI_API_KEY` (largest user base for ChatGPT citation tracking). Defer Perplexity and xAI to phase 2.

### 6.3 New keys to consider for richer audit findings

These are NOT wired yet. Each enables a new dimension of the audit and costs separately.

| Key | Purpose | Why we'd want it | Rough cost |
|---|---|---|---|
| `SEMRUSH_BACKLINKS` (enable backlinks endpoint on existing key) | Referring-domain count per page, anchor-text distribution, toxic backlink flags | Lens E currently has a backlink gap row stubbed but no data. Backlinks are still a top-5 Google ranking factor. | Already covered under existing SEMrush key — separate units (~5k/audit run) |
| `GA4_PROPERTY_ID` + GA4 Data API (service-account auth, reuse `geoseo-496810`) | Bounce rate, average session duration, scroll depth, conversion rate per landing page | Lens A (content quality) can flag "this page has 8200 visits/mo but 87% bounce — content doesn't match intent" | Free under GA4 standard |
| `MEDIASTACK_API_KEY` or `BRANDWATCH_API_KEY` | Brand mentions on news / blogs / forums | Off-page authority signal not currently captured. Useful for executive-level reporting. | $25-100/month |
| `MOZ_API_KEY` or `AHREFS_API_KEY` | Domain Authority / Page Authority scores (third-party, not Google's official) | Industry-standard benchmark numbers; useful for board reporting | $99+/month — probably skip unless explicit ask |
| `SCREAMINGFROG_LICENCE` (file, not API) | Heavy-duty technical-SEO crawler license to drive a side audit | Cross-check our in-house crawler's findings | $209/year |

### 6.4 Keys to add for the audit agent specifically

Beyond the LLM provider keys above, the audit agent itself doesn't need new keys. It runs entirely on data sources already wired:

| Audit data source | Comes from | Already wired? |
|---|---|---|
| Our page HTML + structured metrics | Crawler engine output | ✅ |
| Our PSI / CWV | PSI service account | ✅ |
| Competitor HTML + structure | Competitor crawler + PSI | ✅ |
| Search intent (keyword, position, volume) | SEMrush adapter | ✅ |
| GSC clicks/impressions/queries | GSC integration | ✅ |
| SERP top-3 / AI Overview / PAA | SerpAPI adapter | ✅ |
| AI citation rates | AI visibility probes (Gemini today, others when keys set) | Partial |
| **LLM that does the actual grading** | Groq today, optional premium (Claude/GPT-4o) | ✅ + optional |

So the audit agent is buildable **today** with the keys we have. Adding `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` upgrades the quality (premium model audits the top-20 priority pages); adding GA4 and SEMrush backlinks unlocks 2 new audit lenses (bounce-driven content findings + backlink-gap findings).

---

## 7. Implementation Flow

### Stage 1 — Page selection (deterministic, no LLM)

Three selection modes the operator can pick:

| Mode | Logic | Use case |
|---|---|---|
| **Top traffic** (default) | Top 100 by GSC clicks last 30 days | Quarterly routine audit |
| **High opportunity** | High impressions, low CTR, position 4-15 | Quick-win hunting |
| **Custom URL list** | Paste a list | Targeted audit ("audit all term-insurance pages") |

### Stage 2 — Dossier assembly per page (deterministic)

For each selected page, build a structured ~4KB record from existing data sources. No LLM. Pure DB + cache reads.

```
{
  "url": "...",
  "our_content": { title, meta_description, h1, h2, h3_count, body_text, word_count, schema_types, internal_link_count, image_alt_pct, canonical, last_modified },
  "performance": { lcp_ms, cls, inp_ms, pagespeed_score },
  "search_intent": { primary_keyword, search_volume, current_position, clicks_last_30d, impressions_last_30d, ctr, queries_driving_traffic },
  "competitive_context": { serp_top_3, best_match_competitor_content, featured_snippet_owner, people_also_ask, ai_overview_citations },
  "ai_visibility": { queries_where_cited, queries_where_competitor_cited, citing_engines, missing_from_engines }
}
```

### Stage 3 — LLM audit per page

Pass dossier + system prompt (Prompt 1 by default) to the LLM. Receive structured JSON list of findings. Validate schema. Persist as `PageAuditFinding` rows.

Cheap pass: Groq gpt-oss-120b for all 100 pages (~$0.10/audit).
Optional premium pass: Claude Sonnet 4.6 on the top 20 priority pages (~$0.50-1/audit) for cross-check.

### Stage 4 — Surfacing

Two UI views, same DB rows:

| View | When operator uses it |
|---|---|
| **Per-page** | Picking one page to fix today |
| **Per-category** | Batched fixes ("schema all 47 product pages") |

Both filterable by lens, priority, effort, status.

### Stage 5 — Re-audit & diff

When the operator marks a finding `implemented` and triggers re-audit:

- Agent re-verifies the change on the live page
- If change is live → mark `superseded`
- If not → mark `still_open`
- New findings get `status=open`
- Diff view: "Since last audit — fixed 12, new 4, unchanged 78"

This turns the agent from a one-shot auditor into a **continuous monitor**.

---

## 8. Open Questions to Resolve Before Build

Before I start writing the agent code, these decisions need operator sign-off:

1. **Page-selection default** — top 100 by clicks (recommended), top 50, all pages, or a different rule?

2. **System prompt default** — Prompt 1 (Strict Consultant, recommended), or one of the alternates? Multi-prompt support is fine; we just need to pick a default.

3. **Lens activation** — enable all 5 lenses (recommended), or start with a narrower set? Some shops start with just Lenses A + D (content + AI/GEO) and add the others later.

4. **Per-page or per-section findings** — page-level findings with `location` pointing to a section (recommended) vs section-level rows. Page-level keeps the row count manageable.

5. **Implementation tracking** — keep the `status` field (recommended, makes it a monitor) or skip it (simpler one-shot audit)?

6. **First domain** — only audit `bajajlifeinsurance.com` (simpler) or generalise so we can audit any domain including competitors (more work, more value)?

7. **Markdown export** — DB rows + UI is the default. Do you ALSO want a single markdown report exportable per run (one big `audit_2026_05_20.md` file for sharing with the content team)?

8. **LLM mix for v1** — Groq-only (free, ships today) or Groq + Claude/GPT-4o on top-20 priority pages (needs LLM billing)?

9. **New API keys to prioritise** — section 6 lists 4 LLM keys to consider (Anthropic, OpenAI, Perplexity, xAI) plus 4 data keys (SEMrush backlinks, GA4, Mediastack, Moz/Ahrefs). Which are in scope for this build?

10. **Audit cadence in prod** — manual trigger only, weekly auto-run, or both?

---

## 9. Acceptance Criteria

When the audit agent ships, it should satisfy:

- [ ] Operator clicks "Run audit" on the Competitors / Insights tab; ~30 min later 100 pages have been audited
- [ ] Each audited page has 0-10 findings, structured per the schema in §4
- [ ] Each finding has a quoted current state, a drafted recommended change, a reason citing data signals, and a competitor reference where applicable
- [ ] Operator can filter the findings UI by URL, lens, category, priority, effort, status
- [ ] Operator can export findings to CSV / Markdown
- [ ] Operator can mark findings `implemented`; subsequent audit run verifies the change
- [ ] Re-audit produces a diff view (fixed / new / unchanged counts)
- [ ] The agent gracefully degrades when LLM keys missing — Groq carries the load; premium LLMs upgrade quality when available

---

## 10. What This Plan Deliberately Does NOT Include

- **Numerical scores per page or per dimension** — operator explicitly does not want this
- **Auto-implementation of recommendations** — agent recommends, humans (or a separate write-back tool) execute
- **Backlink building** — auditing only flags backlink gaps; outreach is a separate workflow
- **Off-page content (press, social, partnerships)** — out of scope for this audit; needs a different data layer

---

## 11. Next Step

Operator answers Section 8 questions; I write the implementation tickets and start with Stage 1 (page selection) since it's deterministic and unblocks everything downstream.

---

*Doc author: Claude Opus 4.7 (1M context). Captures decisions made in chat with the operator on 2026-05-20.*
