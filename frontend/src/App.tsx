import { AppShell } from "./components/layout/AppShell";
import { Dashboard } from "./pages/Dashboard";
import { RunDetails } from "./pages/RunDetails";
import { ServiceDetails } from "./pages/ServiceDetails";
import { TeamDetails } from "./pages/TeamDetails";

export function App() {
  const path = window.location.pathname;
  const runMatch = path.match(/^\/runs\/([^/]+)$/);
  const teamMatch = path.match(/^\/teams\/([^/]+)$/);
  const serviceMatch = path.match(/^\/services\/([^/]+)$/);

  let content = <Dashboard />;

  if (runMatch) {
    content = <RunDetails runId={decodeURIComponent(runMatch[1])} />;
  } else if (teamMatch) {
    content = <TeamDetails teamId={decodeURIComponent(teamMatch[1])} />;
  } else if (serviceMatch) {
    content = <ServiceDetails serviceId={decodeURIComponent(serviceMatch[1])} />;
  }

  return <AppShell>{content}</AppShell>;
}
