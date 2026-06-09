# Own-Domain Backlinks — Plan (no paid Ahrefs key)

**Goal:** keep finding **every page on the web that links to `bajajlifeinsurance.com`**, store each link in our database, and keep that database growing and fresh on its own — without paying for Ahrefs/Semrush.

**Scope right now:** OUR backlinks only (not competitors). Competitor backlinks come later.

---

## 1. What is a backlink (one line)

A backlink is **a link on someone else's website that points to ours**. Google treats each one as a "vote" — more good votes = higher authority = better ranking. So we want to find and track all of them.

---

## 2. The trick we are using

Ahrefs is expensive because they **run a giant web crawler** that scans billions of pages all day just to see who links to whom. We can't afford that.

**Our trick: don't crawl the web — ask the systems that already crawled it, then double-check only the pages they point to.**

- Bing already crawled the web → ask Bing who links to us.
- Common Crawl already crawled the web → read its ready-made link list.
- Google/search already crawled it → our existing mention-monitor finds pages that talk about us.
- Our own analytics already logged who sends us visitors → those are real, live links.

Then we fetch just those few thousand pages (not the whole web) and confirm the link is real. That part is cheap.

**In short:** *we ask the web's existing librarians who is pointing at us, then walk to those few shelves to confirm.*

---

## 3. How it works — step by step

> The flow never stops: **FIND → CHECK → SAVE → RE-CHECK.**

**Step 1 — FIND (collect candidate pages from 4 free sources):**
- **Bing Webmaster API** — gives links to our site directly (best free source).
- **Common Crawl link-graph** — gives a big list of websites that link to us.
- **Website analytics referrers (Adobe)** — sites that actually send us traffic = confirmed live links.
- **Brand-mention monitor (already running)** — pages that mention us (news, blogs, forums).

**Step 2 — CHECK (verify each candidate):**
- Open each page's HTML and look for a real link to `bajajlifeinsurance.com`.
- If a link exists → it's a confirmed backlink. We record: who links us, which of our pages, the link text (anchor), whether it's "dofollow" (passes ranking value) or "nofollow", and where on the page it sits (main content vs menu/footer).
- If they mention us but **don't** link → we save it to an **"outreach list"** (people to ask for a link).

**Step 3 — SAVE (store cleanly):**
- Put each confirmed link in our `Backlink` database table.
- No duplicates: one link = one row (keyed by source page + our page). Re-running is always safe.
- The number that matters most = **unique referring domains** (50 links from one site = 1 vote).

**Step 4 — RE-CHECK (keep it honest, monthly):**
- Re-open known backlinks. Still there → keep it fresh. Gone → mark it "lost."
- This is what makes the database *alive*: you can see "gained 12, lost 3 this month."

**Step 5 — RUN FOREVER (automatic schedule):**
- Daily: Bing + analytics referrers + verify new mentions
- Weekly: search/mention sweep
- Monthly: Common Crawl refresh + re-check old links
- Runs on the schedulers we already have (Celery beat). No manual work, no babysitting.

**Step 6 — SHOW (dashboard):**
- Total backlinks, unique referring domains, dofollow vs nofollow, top link texts, top linked pages, new-vs-lost over time, and the outreach list.

---

## 4. How accurate will we be (vs Ahrefs)

Honest answer: it depends on **what you measure**. One number would be misleading, so here's the real breakdown (estimates for our own domain — varies a bit by domain):

| What we measure | How close to Ahrefs | Why |
|---|---|---|
| **High-value backlinks** (big sites, news, anything that drives traffic or is in Google/Bing) | **~70–85%** | These are exactly the links every free source can see. The good stuff is the easy stuff. |
| **Unique referring domains** (the metric that matters most) | **~55–75%** | Strong on real domains; we miss the obscure long tail. |
| **Raw total link count** (the vanity number) | **~30–50%** | Ahrefs lists millions of spam/auto links we skip on purpose. |
| **Freshness** | **As fast or faster** on the important links (daily); slower on the long tail (Common Crawl lags ~1 month). |

**Biggest swing factor = the Bing Webmaster API key:**
- **With Bing key → ~70–85%** of the backlinks that matter. Genuinely strong.
- **Without Bing key → ~40–60%** (Common Crawl + referrers + mentions only).

**Bottom line:** more than good enough for decisions ("is our authority growing, who are our best linkers, who mentions us without linking, did we lose links"). Not meant to match an Ahrefs total-link screenshot — we deliberately skip the spam tail and keep the links that actually move rankings, at ₹0/month, running on its own.

---

## 5. What this will NOT do (be clear)

- It will **not** equal Ahrefs' total count (we skip low-value spam links — on purpose).
- It will **not** cover competitors yet (own domain first).
- It is **not** 100% — no tool is, free or paid. The strength is the **combined, deduped, always-running** union of sources.

---

## 6. Implementation strategy (build order)

**Phase 0 — Confirm the inputs**
- Bing Webmaster domain is **verified** (confirmed — `msvalidate.01` token is live on the site). ✅
- Needed: a **Bing Webmaster API key** from that Bing account (free, instant). This is the one unlock.
- Read the existing `Backlink` model, Adobe adapter, mention-monitor, Common Crawl stub, and beat schedule so we build on what's already there.

**Phase 1 — Wire the loop on what already exists (data within a day)**
- Build the **CHECK (verify)** step, reusing the page extractor we already hardened.
- Connect the feeds we already have: **Adobe referrers + the running mention monitor** → verify → `Backlink` table.
- Add the **Bing feed** the moment the API key is available (this is the backbone).

**Phase 2 — Common Crawl backfill**
- Pull the Common Crawl link-graph monthly to catch the long tail of referring domains.

**Phase 3 — Keep-alive + dashboard**
- Add the monthly **re-check** (lost-link detection).
- Build the dashboard (totals, referring domains, dofollow split, new-vs-lost, outreach list).

**Dependencies / asks**
- ✅ Bing + Google verified (already true).
- ❓ **Bing Webmaster API key** — the single biggest lever (80% vs 50%).
- ✅ Schedulers, page extractor, analytics, mention monitor — already in the codebase.

---

*Plan only — no code changed yet. Accuracy figures are honest estimates for our own domain and vary by domain. The Bing API key decides whether we land near the top (~80%) or middle (~50%) of the range.*
