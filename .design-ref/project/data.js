// data.js — mock SEO crawler data for lumen.travel
// Pure data + tiny helpers, no JSX. Loaded as a plain script before React.

const SITE = 'lumen.travel';
const SITE_URL = 'https://lumen.travel';

const URL_PATHS = [
  '/', '/destinations', '/destinations/japan', '/destinations/iceland',
  '/destinations/portugal', '/destinations/peru', '/destinations/morocco',
  '/destinations/vietnam', '/destinations/norway', '/destinations/new-zealand',
  '/experiences', '/experiences/hot-air-balloon', '/experiences/safari',
  '/experiences/northern-lights', '/experiences/cooking-classes',
  '/experiences/hiking', '/experiences/scuba-diving',
  '/journal', '/journal/best-time-to-visit-japan',
  '/journal/iceland-ring-road-7-days', '/journal/portugal-coastal-drive',
  '/journal/packing-light-for-30-days', '/journal/solo-travel-safety-guide',
  '/journal/budget-vs-luxury-travel', '/journal/cherry-blossom-forecast-2026',
  '/about', '/about/team', '/about/sustainability', '/about/press',
  '/contact', '/help', '/help/booking', '/help/cancellations',
  '/help/visas', '/help/insurance',
  '/login', '/signup', '/account', '/account/trips', '/account/wishlist',
  '/search', '/search?q=patagonia',
  '/legal/terms', '/legal/privacy', '/legal/cookies',
  '/old/winter-2024', '/old/promo', '/blog/2019/welcome',
];

const TITLES = {
  '/': 'Lumen — Curated travel experiences for slow explorers',
  '/destinations': 'All destinations | Lumen',
  '/destinations/japan': 'Japan travel guide — temples, ryokan, ramen | Lumen',
  '/destinations/iceland': 'Iceland — fire, ice, and the Ring Road | Lumen',
  '/destinations/portugal': 'Portugal — Atlantic light from Lisbon to the Algarve',
  '/destinations/peru': 'Peru — Andes, Amazon, ceviche | Lumen',
  '/destinations/morocco': 'Morocco — Marrakech, the Atlas, the Sahara | Lumen',
  '/destinations/vietnam': 'Vietnam — north to south in 14 days | Lumen',
  '/destinations/norway': '',
  '/destinations/new-zealand': 'New Zealand — South Island road trips',
  '/experiences': 'Experiences | Lumen',
  '/experiences/hot-air-balloon': 'Hot air balloon over Cappadocia',
  '/experiences/safari': 'Small-group safaris — Kenya, Tanzania, Botswana',
  '/experiences/northern-lights': 'Chasing the northern lights — Tromsø guide',
  '/experiences/cooking-classes': 'Cooking classes by destination | Lumen',
  '/experiences/hiking': 'Hiking experiences | Lumen',
  '/experiences/scuba-diving': 'Scuba diving | Lumen',
  '/journal': 'Journal | Lumen',
  '/journal/best-time-to-visit-japan': 'When to visit Japan — a month-by-month guide',
  '/journal/iceland-ring-road-7-days': 'Iceland\u2019s Ring Road in 7 days — full itinerary',
  '/journal/portugal-coastal-drive': 'Driving the Portuguese coast — Lisbon to Lagos',
  '/journal/packing-light-for-30-days': 'Packing light for 30 days of travel',
  '/journal/solo-travel-safety-guide': 'Solo travel safety — what we tell our team',
  '/journal/budget-vs-luxury-travel': 'Budget vs. luxury — where the money really goes',
  '/journal/cherry-blossom-forecast-2026': 'Cherry blossom forecast 2026',
  '/about': 'About Lumen',
  '/about/team': 'The team',
  '/about/sustainability': 'Sustainability at Lumen',
  '/about/press': 'Press',
  '/contact': 'Contact us',
  '/help': 'Help center | Lumen',
  '/help/booking': 'Booking help',
  '/help/cancellations': 'Cancellations & refunds',
  '/help/visas': 'Visa information',
  '/help/insurance': 'Travel insurance',
  '/login': 'Sign in',
  '/signup': 'Create your account',
  '/account': 'Your account',
  '/account/trips': 'Your trips',
  '/account/wishlist': 'Wishlist',
  '/search': 'Search',
  '/search?q=patagonia': 'Search results for "patagonia"',
  '/legal/terms': 'Terms of service',
  '/legal/privacy': 'Privacy policy',
  '/legal/cookies': 'Cookie policy',
  '/old/winter-2024': '',
  '/old/promo': 'Promo (old)',
  '/blog/2019/welcome': 'Welcome to our new blog (2019)',
};

const META = {
  '/': 'Hand-picked destinations, slow itineraries, and stories worth the trip. Built by travellers, for travellers.',
  '/destinations': 'Browse 38 destinations across six continents. From slow weekends to month-long expeditions.',
  '/destinations/japan': 'Plan a trip to Japan with Lumen — temples, ryokan, food, and the seasons that shape the country.',
  '/destinations/iceland': 'Self-drive itineraries, glacier hikes, hot springs, and the best months for the aurora.',
  '/destinations/portugal': '',
  '/destinations/peru': 'Machu Picchu, the Sacred Valley, the Amazon, and Lima\u2019s food scene.',
  '/destinations/morocco': 'Souks, kasbahs, and dunes. Our Morocco trips run small and slow.',
  '/destinations/vietnam': '',
  '/destinations/norway': 'Fjords, lofoten, and the slow train from Oslo to Bergen.',
  '/destinations/new-zealand': 'South Island in two weeks — Queenstown, Milford, the West Coast.',
  '/experiences': 'Hand-picked experiences across our destinations.',
  '/experiences/hot-air-balloon': 'Sunrise over Cappadocia\u2019s fairy chimneys, included in our Türkiye itinerary.',
  '/experiences/safari': 'Small-group safaris with the guides we trust most.',
  '/experiences/northern-lights': '',
  '/experiences/cooking-classes': 'Learn to cook the food you eat on the trip — pasta in Bologna, ceviche in Lima.',
  '/experiences/hiking': '',
  '/experiences/scuba-diving': 'Reef trips in Indonesia, Belize, and the Red Sea.',
  '/journal': 'Field notes, itineraries, and the occasional rant. Updated weekly.',
  '/journal/best-time-to-visit-japan': '',
  '/journal/iceland-ring-road-7-days': 'A real, drivable 7-day loop with the stops we actually like — and the ones to skip.',
  '/journal/portugal-coastal-drive': 'Three weeks down the coast, distilled into ten stops.',
  '/journal/packing-light-for-30-days': 'The exact list we travel with — one carry-on, all seasons.',
  '/journal/solo-travel-safety-guide': '',
  '/journal/budget-vs-luxury-travel': 'Where it\u2019s worth spending and where it really isn\u2019t.',
  '/journal/cherry-blossom-forecast-2026': 'Our best estimate for peak bloom in Tokyo, Kyoto, and Hirosaki.',
  '/about': 'A small studio of travellers, writers, and trip planners. Based in Lisbon.',
  '/about/team': 'The eleven people who make Lumen run.',
  '/about/sustainability': 'How we offset, who we partner with, and what we still get wrong.',
  '/about/press': 'Press kit and recent coverage.',
  '/contact': 'Get in touch — we read everything.',
};

// Status code → frequency. 200 dominant; small tail of 3xx/4xx.
function pickStatus(i) {
  const r = ((i * 7919) % 1000) / 1000;
  if (r < 0.84) return 200;
  if (r < 0.91) return 301;
  if (r < 0.94) return 302;
  if (r < 0.97) return 404;
  if (r < 0.985) return 410;
  if (r < 0.992) return 500;
  return 503;
}

// Build a deterministic table of ~1,200 URLs (we'll show a slice).
function buildUrls() {
  const out = [];
  let id = 1;
  // Real-feeling primary URLs.
  for (const path of URL_PATHS) {
    const status = path.startsWith('/old/') || path.startsWith('/blog/2019')
      ? 404 : path === '/destinations/norway' ? 301 : pickStatus(id);
    out.push(makeRow(id++, path, status));
  }
  // Synthetic deeper URLs to fill out the table — destination listings,
  // journal archive pages, paginated search.
  const dests = ['japan', 'iceland', 'portugal', 'peru', 'morocco', 'vietnam',
    'norway', 'new-zealand', 'turkey', 'kenya', 'tanzania', 'mexico', 'spain',
    'italy', 'france', 'colombia', 'argentina', 'chile', 'thailand', 'indonesia'];
  const months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  for (const d of dests) {
    for (const m of months) {
      out.push(makeRow(id++, `/destinations/${d}/best-time/${m}`, pickStatus(id)));
    }
  }
  for (let p = 1; p <= 40; p++) {
    out.push(makeRow(id++, `/journal/page/${p}`, pickStatus(id)));
  }
  for (let p = 1; p <= 60; p++) {
    out.push(makeRow(id++, `/destinations/page/${p}`, pickStatus(id)));
  }
  // Image and asset URLs (different content type).
  const imgs = ['hero', 'card', 'thumb', 'og'];
  for (const d of dests) {
    for (const v of imgs) {
      out.push({
        ...makeRow(id++, `/img/destinations/${d}-${v}.jpg`, 200),
        contentType: 'image',
        title: '',
        meta: '',
        h1: '',
      });
    }
  }
  return out;
}

function makeRow(id, path, status) {
  const url = SITE_URL + path;
  const title = TITLES[path] !== undefined ? TITLES[path] :
    path.split('/').filter(Boolean).slice(-1)[0]?.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) + ' | Lumen' || 'Lumen';
  const meta = META[path] !== undefined ? META[path] :
    `Lumen — ${path.split('/').filter(Boolean).join(' · ') || 'home'}`;
  const depth = path === '/' ? 0 : path.split('/').filter(Boolean).length;
  const seed = id * 2654435761 % 2147483647;
  const inlinks = status >= 400 ? Math.max(0, (seed % 6)) : 1 + (seed % 80);
  const outlinks = status >= 400 ? 0 : 4 + (seed % 60);
  const responseTime = status >= 500 ? 1800 + (seed % 1500) :
                       status >= 400 ? 80 + (seed % 60) :
                       status >= 300 ? 40 + (seed % 60) :
                       80 + (seed % 600);
  const size = status >= 400 ? 1.8 + ((seed % 30) / 10) :
               14 + ((seed % 280) / 10);
  return {
    id,
    url,
    path,
    status,
    title,
    meta,
    h1: title.split(' | ')[0] || title,
    depth,
    inlinks,
    outlinks,
    responseTime,
    size, // KB
    contentType: 'html',
    crawledAt: '2026-05-06 14:23:11',
  };
}

const URLS = buildUrls();

// ── Issues ──────────────────────────────────────────────────────────────────
// Derive issue lists from the URL table so counts are consistent everywhere.
function deriveIssues() {
  const issues = [
    { id: 'broken-4xx', name: 'Broken links (4xx)', severity: 'error',
      description: 'URLs returning a 4xx response. These hurt crawl efficiency and user trust.',
      match: (u) => u.status >= 400 && u.status < 500 },
    { id: 'server-5xx', name: 'Server errors (5xx)', severity: 'error',
      description: 'URLs returning a 5xx response — investigate before they cascade.',
      match: (u) => u.status >= 500 },
    { id: 'missing-title', name: 'Missing title', severity: 'error',
      description: 'Pages without a <title> tag. Critical for ranking and SERP appearance.',
      match: (u) => u.contentType === 'html' && u.status === 200 && !u.title },
    { id: 'missing-meta', name: 'Missing meta description', severity: 'warning',
      description: 'Pages without a meta description. Search engines may auto-generate a snippet.',
      match: (u) => u.contentType === 'html' && u.status === 200 && !u.meta },
    { id: 'duplicate-title', name: 'Duplicate titles', severity: 'warning',
      description: 'More than one page sharing the same <title>.',
      match: null /* set below */ },
    { id: 'long-title', name: 'Title too long', severity: 'notice',
      description: 'Titles over 60 characters may be truncated in search results.',
      match: (u) => u.title && u.title.length > 60 },
    { id: 'short-meta', name: 'Meta description too short', severity: 'notice',
      description: 'Meta descriptions under 70 characters may be flagged as thin.',
      match: (u) => u.meta && u.meta.length > 0 && u.meta.length < 70 },
    { id: 'redirect-3xx', name: 'Redirects (3xx)', severity: 'notice',
      description: 'URLs redirecting elsewhere. Long chains hurt crawl budget.',
      match: (u) => u.status >= 300 && u.status < 400 },
    { id: 'slow-response', name: 'Slow response (>1s)', severity: 'warning',
      description: 'URLs taking longer than a second to respond.',
      match: (u) => u.responseTime > 1000 },
    { id: 'orphan-pages', name: 'Orphan pages', severity: 'warning',
      description: 'Reachable pages with zero internal inlinks.',
      match: (u) => u.contentType === 'html' && u.status < 400 && u.inlinks === 0 },
    { id: 'deep-pages', name: 'Pages at depth ≥ 5', severity: 'notice',
      description: 'Pages buried more than 5 clicks from the homepage.',
      match: (u) => u.depth >= 5 },
    { id: 'large-pages', name: 'Pages over 200 KB', severity: 'notice',
      description: 'HTML payloads larger than 200 KB. Consider trimming.',
      match: (u) => u.contentType === 'html' && u.size > 200 },
  ];

  // Duplicate titles — group html 200s by exact title.
  const titleMap = {};
  for (const u of URLS) {
    if (u.contentType !== 'html' || u.status !== 200 || !u.title) continue;
    (titleMap[u.title] = titleMap[u.title] || []).push(u);
  }
  const dupTitles = Object.values(titleMap).filter((arr) => arr.length > 1).flat();
  const dupIds = new Set(dupTitles.map((u) => u.id));
  issues.find((i) => i.id === 'duplicate-title').match = (u) => dupIds.has(u.id);

  return issues.map((i) => {
    const urls = URLS.filter(i.match);
    return { ...i, count: urls.length, urls };
  });
}

const ISSUES = deriveIssues();

// ── Live activity feed templates ────────────────────────────────────────────
const ACTIVITY_TEMPLATES = [
  { kind: 'crawl', verb: 'Crawling' },
  { kind: 'ok', verb: '200 OK' },
  { kind: 'meta', verb: 'Extracted metadata' },
  { kind: 'links', verb: 'Found {n} links' },
  { kind: 'image', verb: 'Indexed image' },
  { kind: 'redirect', verb: '301 redirect' },
  { kind: '404', verb: '404 Not Found' },
  { kind: 'meta', verb: 'Extracted metadata' },
  { kind: 'crawl', verb: 'Crawling' },
  { kind: 'ok', verb: '200 OK' },
];

// ── Sparkline data ──────────────────────────────────────────────────────────
function sparkline(seed, n = 24, base = 50, range = 30, trend = 0) {
  const out = [];
  let s = seed;
  for (let i = 0; i < n; i++) {
    s = (s * 9301 + 49297) % 233280;
    const noise = (s / 233280 - 0.5) * range;
    out.push(base + noise + trend * i);
  }
  return out;
}

// ── Site structure tree ─────────────────────────────────────────────────────
function buildTree() {
  const root = { name: SITE, children: {}, count: 0 };
  for (const u of URLS) {
    if (u.path === '/') { root.count++; continue; }
    const parts = u.path.split('/').filter(Boolean);
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const p = parts[i];
      node.children[p] = node.children[p] || { name: p, children: {}, count: 0 };
      node = node.children[p];
    }
    node.count++;
  }
  // Convert to nested arrays.
  const toArr = (n) => ({
    name: n.name,
    count: n.count + Object.values(n.children).reduce((s, c) => s + countAll(c), 0),
    children: Object.values(n.children).map(toArr),
  });
  const countAll = (n) => n.count + Object.values(n.children).reduce((s, c) => s + countAll(c), 0);
  return toArr(root);
}

const TREE = buildTree();

// ── Crawl sessions history ──────────────────────────────────────────────────
const SESSIONS = [
  { id: 'sess_2641', started: '2026-05-06 13:30', status: 'running',
    urls: 1842, total: 2310, errors: 47, warnings: 312, duration: '12:45',
    site: SITE_URL, type: 'Deep crawl' },
  { id: 'sess_2598', started: '2026-04-29 09:14', status: 'completed',
    urls: 2287, total: 2287, errors: 31, warnings: 298, duration: '18:22',
    site: SITE_URL, type: 'Deep crawl' },
  { id: 'sess_2574', started: '2026-04-22 09:00', status: 'completed',
    urls: 2241, total: 2241, errors: 28, warnings: 304, duration: '17:11',
    site: SITE_URL, type: 'Weekly scheduled' },
  { id: 'sess_2511', started: '2026-04-15 09:00', status: 'completed',
    urls: 2198, total: 2198, errors: 26, warnings: 287, duration: '17:48',
    site: SITE_URL, type: 'Weekly scheduled' },
  { id: 'sess_2478', started: '2026-04-08 09:00', status: 'completed',
    urls: 2156, total: 2156, errors: 22, warnings: 281, duration: '16:34',
    site: SITE_URL, type: 'Weekly scheduled' },
  { id: 'sess_2454', started: '2026-04-04 22:11', status: 'failed',
    urls: 412, total: 2150, errors: 1, warnings: 12, duration: '03:21',
    site: SITE_URL, type: 'Manual', failureReason: 'Connection timeout' },
  { id: 'sess_2430', started: '2026-04-01 09:00', status: 'completed',
    urls: 2098, total: 2098, errors: 19, warnings: 274, duration: '15:55',
    site: SITE_URL, type: 'Weekly scheduled' },
];

// ── Projects ────────────────────────────────────────────────────────────────
const PROJECTS = [
  { id: 'lumen', name: 'lumen.travel', site: SITE_URL, urls: 2310 },
  { id: 'lumen-staging', name: 'staging.lumen.travel', site: 'https://staging.lumen.travel', urls: 2104 },
  { id: 'helio-magazine', name: 'helio-magazine.com', site: 'https://helio-magazine.com', urls: 4821 },
];

// Export to global scope.
Object.assign(window, {
  SITE, SITE_URL, URLS, ISSUES, ACTIVITY_TEMPLATES, sparkline, TREE,
  SESSIONS, PROJECTS,
});
