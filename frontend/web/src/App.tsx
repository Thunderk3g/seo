import { Route, Switch } from 'wouter';
import Sidebar from './components/Sidebar';
import Topbar from './components/Topbar';
import StatusBar from './components/StatusBar';
import DashboardPage from './pages/DashboardPage';
import SessionsPage from './pages/SessionsPage';
import PagesUrlsPage from './pages/PagesUrlsPage';
import IssuesPage from './pages/IssuesPage';
import AnalyticsPage from './pages/AnalyticsPage';
import VisualizationsPage from './pages/VisualizationsPage';
import ExportsPage from './pages/ExportsPage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <Topbar />
        <main className="content-scroll">
          <Switch>
            <Route path="/" component={DashboardPage} />
            <Route path="/sessions" component={SessionsPage} />
            <Route path="/pages" component={PagesUrlsPage} />
            <Route path="/issues" component={IssuesPage} />
            <Route path="/analytics" component={AnalyticsPage} />
            <Route path="/visualizations" component={VisualizationsPage} />
            <Route path="/exports" component={ExportsPage} />
            <Route path="/settings" component={SettingsPage} />
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
