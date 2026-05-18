# llms.txt — Reference + Sample

Reference dump of competitor `llms.txt` files (the ones the gap pipeline flagged as having one), plus a sample `llms.txt` drafted for **bajajlifeinsurance.com**.

This folder contains **reference data only**. No code changes. Nothing here is auto-served — to actually publish, the sample file needs to be uploaded to the web root so it's reachable at `https://www.bajajlifeinsurance.com/llms.txt`.

## What's an llms.txt?

A plain-text markdown file at the site root that tells AI assistants (ChatGPT, Claude, Perplexity, Gemini, Bing Copilot) what the site is and which pages summarize its products. It's the "robots.txt for LLMs" — emerging standard since 2024, proposed by Jeremy Howard at llmstxt.org.

Two common styles in the wild:
1. **Markdown navigation tree** — H1 brand name + blockquote tagline + categorized link lists with descriptions (what tataaia.com and axismaxlife.com use; what we drafted for Bajaj).
2. **Robots-style directives** — `User-Agent`, `Allow-Training`, `Attribution-Format`, `Disallow:` rules (what policyx.com uses).

Style #1 is the more widely adopted format and what most large LLM crawlers actually consume.

## Contents

```
llms_txt/
├── README.md                              (this file)
├── bajajlifeinsurance.com.sample.txt      ← proposed sample for our site
└── competitors/
    ├── policyx.com.txt                    (style 2 — robots-style directives)
    ├── axismaxlife.com.txt                (style 1 — markdown nav tree, ~190 links)
    ├── tataaia.com.txt                    (style 1 — markdown nav tree, ~13 links)
    └── _not_found.md                      (which competitors don't have one / couldn't fetch)
```

## Source of truth

- Competitor files were fetched directly from `https://{domain}/llms.txt` on 2026-05-17.
- The Bajaj sample uses real URLs pulled from `backend/data/crawl_results.csv` (HTTP 200 only) — no fabricated paths.
- Brand name is **Bajaj Life Insurance** (not Bajaj Allianz Life — the company rebranded).

## How to publish

1. Marketing reviews `bajajlifeinsurance.com.sample.txt`, edits descriptions/tone if needed.
2. Upload via AEM (or whatever web-root mechanism the team uses) so it's served at `https://www.bajajlifeinsurance.com/llms.txt` with `Content-Type: text/plain`.
3. Add the URL to `robots.txt` as a courtesy: `# LLM directives: https://www.bajajlifeinsurance.com/llms.txt`.
4. Re-run the gap pipeline — the "missing llms.txt" notice should drop off.
