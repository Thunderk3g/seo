import { Route, Switch } from 'wouter';
import Sidebar from './components/Sidebar';
// StatusBar removed per request — file kept at components/StatusBar.tsx.
import ChatPage from './pages/ChatPage';
import GscPage from './pages/GscPage';
import SemrushPage from './pages/SemrushPage';
import AdobePage from './pages/AdobePage';
import AdobeSeoJoinPage from './pages/AdobeSeoJoinPage';
import BrandMonitorPage from './pages/BrandMonitorPage';
import MetaAdsPage from './pages/MetaAdsPage';
import ContentPage from './pages/ContentPage';
import CompetitorsPage from './pages/CompetitorsPage';
// Embedded Crawler Engine (v2) pages — see src/crawler/* and crawler-engine/.
import CrawlerDashboard from './crawler/pages/CrawlerDashboard';
import SiteTreePage from './crawler/pages/SiteTreePage';
import CrawlerLogs from './crawler/pages/CrawlerLogs';
import CrawlerReports from './crawler/pages/CrawlerReports';
import CrawlerReportDetail from './crawler/pages/CrawlerReportDetail';
import CrawlerSectionDetail from './crawler/pages/CrawlerSectionDetail';
import ReportsPage from './pages/ReportsPage';
import PageExplorerPage from './crawler/pages/PageExplorerPage';
import CompetitorDetailPage from './pages/CompetitorDetailPage';
import CompetitorPageDetailPage from './pages/CompetitorPageDetailPage';
import PageDetailPage from './pages/PageDetailPage';
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
            <Route path="/content" component={ContentPage} />
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
            {/* Section detail — must precede the generic :key table route. */}
            <Route path="/crawler/reports/section/:key" component={CrawlerSectionDetail} />
            <Route path="/crawler/reports/:key" component={CrawlerReportDetail} />
            {/* Manager-facing XLSX report builder. */}
            <Route path="/reports" component={ReportsPage} />
            {/* Legacy /content-writer (DB-roster Page Revamp) REMOVED 2026-05-31. */}
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
            <Route>
              <div style={{ padding: 24 }}>Not found</div>
            </Route>
          </Switch>
        </main>
      </div>
    </div>
  );
}
