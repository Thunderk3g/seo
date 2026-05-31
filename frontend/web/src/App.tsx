import { lazy, Suspense } from 'react';
import { Route, Switch } from 'wouter';
import Sidebar from './components/Sidebar';
import RouteErrorBoundary from './components/RouteErrorBoundary';
// StatusBar removed per request — file kept at components/StatusBar.tsx.
import ChatPage from './pages/ChatPage';
import GscPage from './pages/GscPage';
import SemrushPage from './pages/SemrushPage';
import AdobePage from './pages/AdobePage';
import AdobeSeoJoinPage from './pages/AdobeSeoJoinPage';
import BrandMonitorPage from './pages/BrandMonitorPage';
import MetaAdsPage from './pages/MetaAdsPage';
import SitemapContentPage from './pages/SitemapContentPage';
import CompetitorsPage from './pages/CompetitorsPage';
// Embedded Crawler Engine (v2) pages — see src/crawler/* and crawler-engine/.
import CrawlerDashboard from './crawler/pages/CrawlerDashboard';
import SiteTreePage from './crawler/pages/SiteTreePage';
import CrawlerLogs from './crawler/pages/CrawlerLogs';
import CrawlerReports from './crawler/pages/CrawlerReports';
import CrawlerReportDetail from './crawler/pages/CrawlerReportDetail';
import IssuesPage from './crawler/pages/IssuesPage';
import CompliancePage from './crawler/pages/CompliancePage';
// ContentMapPage pulls in @react-three/fiber, which crashes at import-time
// against React 18 (r3f@9 needs React 19). Lazy-load it so the rest of the
// app keeps working; downgrade r3f→8 / drei→9 to fix the page itself.
const ContentMapPage = lazy(() => import('./crawler/pages/ContentMapPage'));
import ContentClustersPage from './crawler/pages/ContentClustersPage';
import ReportsPage from './pages/ReportsPage';
import PageExplorerPage from './crawler/pages/PageExplorerPage';
import HealthDashboard from './crawler/pages/HealthDashboard';
import TrendsPage from './crawler/pages/TrendsPage';
import CompareCrawlsPage from './crawler/pages/CompareCrawlsPage';
import GeoDashboard from './crawler/pages/GeoDashboard';
import CompetitorDetailPage from './pages/CompetitorDetailPage';
import CompetitorPageDetailPage from './pages/CompetitorPageDetailPage';
import PageDetailPage from './pages/PageDetailPage';
import ContentWriterPage from './pages/ContentWriterPage';
import ContentWriterV2Page from './pages/ContentWriterV2Page';
import CustodiansPage from './pages/CustodiansPage';
import BriefingsPage from './pages/BriefingsPage';
import GeoPage from './pages/GeoPage';
import CompetitorChangesPage from './pages/CompetitorChangesPage';

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
            {/* Our own Bajaj Life Meta ads — isolated from competitor
                sections so the ad-library detail page for any
                competitor never bleeds Bajaj ads into a rival's slot. */}
            <Route path="/meta-ads" component={MetaAdsPage} />
            <Route path="/sitemap" component={SitemapContentPage} />
            <Route path="/competitors" component={CompetitorsPage} />
            {/* Phase 2 — per-competitor + per-URL detail. Replaces
                the DeepCrawlPanel "dropdown" pattern. */}
            <Route
              path="/competitors/:domain/pages/:b64"
              component={CompetitorPageDetailPage}
            />
            <Route path="/competitors/:domain" component={CompetitorDetailPage} />

            {/* Snapshot-explicit per-URL detail — same layout as the
                competitor route, but driven by an explicit snapshot ID.
                Used by Bajaj Page Explorer and the ad-hoc URL crawler so
                all three sources render with one component. */}
            <Route
              path="/crawler/pages/:snapshotId/:b64"
              component={PageDetailPage}
            />
            <Route
              path="/adhoc/pages/:snapshotId/:b64"
              component={PageDetailPage}
            />

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
            {/* Compliance — WCAG / GDPR / OWASP manager-facing report. */}
            <Route path="/crawler/compliance" component={CompliancePage} />
            {/* 3D content map — segregated by product + page-type.
                Wrapped in an error boundary because @react-three/fiber@9
                crashes against React 18; downgrade to r3f@8 / drei@9 to
                fix. Use Content Clusters in the meantime. */}
            <Route path="/crawler/content-map">
              <RouteErrorBoundary
                label="Content Map (3D)"
                hint="Run: cd frontend/web && npm install @react-three/fiber@^8 @react-three/drei@^9 — r3f@9 needs React 19 but this app is on React 18. The Content Clusters page is a non-3D alternative."
              >
                <Suspense fallback={<div style={{ padding: 24 }}>Loading 3D map…</div>}>
                  <ContentMapPage />
                </Suspense>
              </RouteErrorBoundary>
            </Route>
            {/* Hierarchical cluster tree (Product → Page-type → pages). */}
            <Route path="/crawler/content-clusters" component={ContentClustersPage} />
            {/* Manager-facing XLSX report builder. */}
            <Route path="/reports" component={ReportsPage} />
            {/* ContentWriter — LLM rewrites with citation pills. */}
            <Route path="/content-writer" component={ContentWriterPage} />
            {/* V2 — SERP-discovery-driven page revamp. New flow lives
                in apps/seo_ai/content_writer/ (separate dir). */}
            <Route path="/content-writer-v2" component={ContentWriterV2Page} />
            {/* DataCustodians — our domain + competitor roster + SiteDiffer. */}
            <Route path="/custodians" component={CustodiansPage} />
            {/* Briefings — Orchestrator V2 headline + biggest signals. */}
            <Route path="/briefings" component={BriefingsPage} />
            {/* GEO score — Generative Engine Optimization rollup. */}
            <Route path="/geo-score" component={GeoPage} />
            {/* ChangeWatcher feed — daily competitor change events. */}
            <Route path="/competitor-changes" component={CompetitorChangesPage} />
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
