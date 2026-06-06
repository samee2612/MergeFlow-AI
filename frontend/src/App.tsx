import { Dashboard } from "./pages/Dashboard";
import { RunDetails } from "./pages/RunDetails";
import { ServiceDetails } from "./pages/ServiceDetails";
import { TeamDetails } from "./pages/TeamDetails";

export function App() {
  const path = window.location.pathname;
  const runMatch = path.match(/^\/runs\/([^/]+)$/);
  const teamMatch = path.match(/^\/teams\/([^/]+)$/);
  const serviceMatch = path.match(/^\/services\/([^/]+)$/);

  if (runMatch) {
    return <RunDetails runId={decodeURIComponent(runMatch[1])} />;
  }

  if (teamMatch) {
    return <TeamDetails teamId={decodeURIComponent(teamMatch[1])} />;
  }

  if (serviceMatch) {
    return <ServiceDetails serviceId={decodeURIComponent(serviceMatch[1])} />;
  }

  return <Dashboard />;
}
