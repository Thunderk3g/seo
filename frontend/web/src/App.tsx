import { Route, Switch } from 'wouter';
import Sidebar from './components/Sidebar';
import Topbar from './components/Topbar';
import StatusBar from './components/StatusBar';
import ChatPage from './pages/ChatPage';
import GscPage from './pages/GscPage';
import SemrushPage from './pages/SemrushPage';
import SitemapContentPage from './pages/SitemapContentPage';
import CompetitorsPage from './pages/CompetitorsPage';
// Embedded Crawler Engine (v2) pages — see src/crawler/* and crawler-engine/.
import CrawlerDashboard from './crawler/pages/CrawlerDashboard';
import SiteTreePage from './crawler/pages/SiteTreePage';
import CrawlerLogs from './crawler/pages/CrawlerLogs';
import CrawlerReports from './crawler/pages/CrawlerReports';
import CrawlerReportDetail from './crawler/pages/CrawlerReportDetail';
import CrawlerSettings from './crawler/pages/CrawlerSettings';

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <Topbar />
        <main className="content-scroll">
          <Switch>
            {/* ── Bajaj SEO Assistant (primary surface) ──────── */}
            <Route path="/" component={ChatPage} />

            {/* ── Data Sources ─────────────────────────────────── */}
            <Route path="/gsc" component={GscPage} />
            <Route path="/semrush" component={SemrushPage} />
            <Route path="/sitemap" component={SitemapContentPage} />
            <Route path="/competitors" component={CompetitorsPage} />

            {/* ── Crawler Engine (v2) ─────────────────────────── */}
            <Route path="/crawler" component={CrawlerDashboard} />
            <Route path="/crawler/tree" component={SiteTreePage} />
            <Route path="/crawler/logs" component={CrawlerLogs} />
            <Route path="/crawler/reports" component={CrawlerReports} />
            <Route path="/crawler/reports/:key" component={CrawlerReportDetail} />
            <Route path="/crawler/settings" component={CrawlerSettings} />

            <Route>
              <div style={{ padding: 24 }}>Not found</div>
            </Route>
          </Switch>
        </main>
        <StatusBar />
      </div>
    </div>
  );
}
