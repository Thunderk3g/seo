import { Route, Switch } from 'wouter';
import Sidebar from './components/Sidebar';
// StatusBar removed per request — file kept at components/StatusBar.tsx.
import ChatPage from './pages/ChatPage';
import GscPage from './pages/GscPage';
import SemrushPage from './pages/SemrushPage';
import AdobePage from './pages/AdobePage';
import AdobeSeoJoinPage from './pages/AdobeSeoJoinPage';
import BrandMonitorPage from './pages/BrandMonitorPage';
import SitemapContentPage from './pages/SitemapContentPage';
import CompetitorsPage from './pages/CompetitorsPage';
// Embedded Crawler Engine (v2) pages — see src/crawler/* and crawler-engine/.
import CrawlerDashboard from './crawler/pages/CrawlerDashboard';
import SiteTreePage from './crawler/pages/SiteTreePage';
import CrawlerLogs from './crawler/pages/CrawlerLogs';
import CrawlerReports from './crawler/pages/CrawlerReports';
import CrawlerReportDetail from './crawler/pages/CrawlerReportDetail';
import IssuesPage from './crawler/pages/IssuesPage';
import PageExplorerPage from './crawler/pages/PageExplorerPage';
import HealthDashboard from './crawler/pages/HealthDashboard';
import TrendsPage from './crawler/pages/TrendsPage';
import CompareCrawlsPage from './crawler/pages/CompareCrawlsPage';
import GeoDashboard from './crawler/pages/GeoDashboard';
import CompetitorDetailPage from './pages/CompetitorDetailPage';
import CompetitorPageDetailPage from './pages/CompetitorPageDetailPage';

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <main className="content-scroll">
          <Switch>
            {/* ── Bajaj SEO Assistant (primary surface) ──────── */}
            <Route path="/" component={ChatPage} />

            {/* ── Data Sources ─────────────────────────────────── */}
            <Route path="/gsc" component={GscPage} />
            <Route path="/semrush" component={SemrushPage} />
            <Route path="/adobe" component={AdobePage} />
            <Route path="/adobe/seo-join" component={AdobeSeoJoinPage} />
            <Route path="/brand-monitor" component={BrandMonitorPage} />
            <Route path="/sitemap" component={SitemapContentPage} />
            <Route path="/competitors" component={CompetitorsPage} />
            {/* Phase 2 — per-competitor + per-URL detail. Replaces
                the DeepCrawlPanel "dropdown" pattern. */}
            <Route
              path="/competitors/:domain/pages/:b64"
              component={CompetitorPageDetailPage}
            />
            <Route path="/competitors/:domain" component={CompetitorDetailPage} />

            {/* ── Crawler Engine (v2) ─────────────────────────── */}
            {/* /crawler/settings removed per request — to restore, re-add  */}
            {/* the import + Route. The page file lives at                  */}
            {/* crawler/pages/CrawlerSettings.tsx.                            */}
            <Route path="/crawler" component={CrawlerDashboard} />
            <Route path="/crawler/tree" component={SiteTreePage} />
            <Route path="/crawler/logs" component={CrawlerLogs} />
            <Route path="/crawler/reports" component={CrawlerReports} />
            <Route path="/crawler/reports/:key" component={CrawlerReportDetail} />
            {/* Phase 1 — audit engine: typed issues inbox + Health Score. */}
            <Route path="/crawler/issues" component={IssuesPage} />
            <Route path="/crawler/issues/:slug" component={IssuesPage} />
            {/* Phase 2 — Ahrefs-style Page Explorer with sortable/
                filterable URL inventory over the latest crawl. */}
            <Route path="/crawler/pages" component={PageExplorerPage} />
            {/* Phase 4 — Health Dashboard (Ahrefs overview). */}
            <Route path="/health" component={HealthDashboard} />
            {/* Phase 5 — Trends (Health Score over time) + Compare Crawls. */}
            <Route path="/trends" component={TrendsPage} />
            <Route path="/compare" component={CompareCrawlsPage} />
            {/* Phase 6 — GEO suite (llms.txt + IndexNow + AI-bots + backlinks). */}
            <Route path="/geo" component={GeoDashboard} />

            <Route>
              <div style={{ padding: 24 }}>Not found</div>
            </Route>
          </Switch>
        </main>
      </div>
    </div>
  );
}
