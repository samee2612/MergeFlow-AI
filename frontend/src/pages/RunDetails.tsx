import { useEffect, useState } from "react";

import { fetchRun } from "../api";
import { ArtifactLinks } from "../components/ArtifactLinks";
import type { RunDetail } from "../types";

type RunDetailsProps = {
  runId: string;
};

const PIPELINE_STEPS: Array<[keyof RunDetail["pipelineStatus"], string]> = [
  ["backendDetection", "Backend Detection"],
  ["classification", "Classification"],
  ["testCaseGeneration", "Test Case Generation"],
  ["openapiGeneration", "OpenAPI Generation"],
  ["postmanGeneration", "Postman Generation"],
  ["notionUpdate", "Notion Update"],
  ["emailSent", "Email Sent"],
];

export function RunDetails({ runId }: RunDetailsProps) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetchRun(runId)
      .then(setRun)
      .catch((loadError: Error) => setError(loadError.message))
      .finally(() => setIsLoading(false));
  }, [runId]);

  if (isLoading) {
    return <main className="page">Loading run...</main>;
  }

  if (error || run === null) {
    return (
      <main className="page">
        <a className="back-link" href="/">
          Back to runs
        </a>
        <p className="error">{error || "Run not found."}</p>
      </main>
    );
  }

  return (
    <main className="page">
      <a className="back-link" href="/">
        Back to runs
      </a>

      <header className="hero">
        <p className="eyebrow">PR #{run.prNumber}</p>
        <h1>{run.prTitle}</h1>
        <p className="muted">
          {run.repository} · <span className={`status status--${run.status.toLowerCase()}`}>{run.status}</span>
        </p>
      </header>

      <section className="panel">
        <h2>Pipeline Status</h2>
        <div className="status-grid">
          {PIPELINE_STEPS.map(([key, label]) => (
            <div className="status-item" key={key}>
              <span className={run.pipelineStatus[key] ? "check" : "check check--muted"}>
                {run.pipelineStatus[key] ? "✓" : "○"}
              </span>
              {label}
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Classification</h2>
        <p className="section-label">Change Types</p>
        <div className="tag-row">
          {run.classification.changeTypes.map((changeType) => (
            <span className="tag" key={changeType}>
              {changeType}
            </span>
          ))}
        </div>
        <p className="section-label">Summary</p>
        <p>{run.classification.summary}</p>
      </section>

      <section className="panel">
        <h2>Generated Artifacts</h2>
        <ArtifactLinks artifacts={run.artifacts} />
      </section>

      <section className="panel">
        <h2>API Overview</h2>
        <div className="endpoint-list">
          {run.apiOverview.map((endpoint) => (
            <article className="endpoint-card" key={`${endpoint.method}-${endpoint.path}`}>
              <h3>
                <span className="method">{endpoint.method}</span> {endpoint.path}
              </h3>
              <p className="section-label">Request Fields</p>
              <ul>
                {endpoint.requestFields.map((field) => (
                  <li key={field}>{field}</li>
                ))}
              </ul>
              <p className="section-label">Response Codes</p>
              <div className="tag-row">
                {endpoint.responseCodes.map((code) => (
                  <span className="tag" key={code}>
                    {code}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Generated Test Cases</h2>
        <div className="test-list">
          {run.testCases.map((testCase) => (
            <article className="test-card" key={testCase.name}>
              <h3>{testCase.name}</h3>
              <p>Expected: {testCase.expected}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
