import { useEffect, useState } from "react";

import { fetchRuns } from "../api";
import { PipelineRun } from "../components/PipelineRun";
import type { RunSummary } from "../types";

export function Dashboard() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetchRuns()
      .then(setRuns)
      .catch((loadError: Error) => setError(loadError.message))
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <main className="page">
      <header className="hero">
        <p className="eyebrow">MergeFlow Dashboard V1</p>
        <h1>Recent Runs</h1>
        <p className="muted">Processed backend PRs and the artifacts MergeFlow generated for them.</p>
      </header>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Recent Runs</h2>
            <p className="muted">Click a run to inspect classification, APIs, test cases, and artifacts.</p>
          </div>
        </div>

        {isLoading ? <p className="muted">Loading runs...</p> : null}
        {error ? <p className="error">{error}</p> : null}
        {!isLoading && !error && runs.length === 0 ? <p className="muted">No runs found yet.</p> : null}

        <div className="run-list">
          {runs.map((run) => (
            <PipelineRun key={run.id} run={run} />
          ))}
        </div>
      </section>
    </main>
  );
}
