import { Dashboard } from "./pages/Dashboard";
import { RunDetails } from "./pages/RunDetails";

export function App() {
  const path = window.location.pathname;
  const runMatch = path.match(/^\/runs\/([^/]+)$/);

  if (runMatch) {
    return <RunDetails runId={decodeURIComponent(runMatch[1])} />;
  }

  return <Dashboard />;
}
