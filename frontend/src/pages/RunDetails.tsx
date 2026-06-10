import { useEffect, useMemo, useState } from "react";

import { fetchRun } from "../api";
import { AnimatedHero } from "../components/AnimatedHero";
import { ArtifactDock } from "../components/ArtifactDock";
import { PipelineTimeline } from "../components/PipelineTimeline";
import type { RunDetail } from "../types";

type RunDetailsProps = {
  runId: string;
};

const PIPELINE_STEPS: Array<[keyof RunDetail["pipelineStatus"], string]> = [
  ["backendDetection", "Service Detection"],
  ["classification", "Change Classification"],
  ["testCaseGeneration", "Test Case Generation"],
  ["openapiGeneration", "OpenAPI Generation"],
  ["postmanGeneration", "Postman Generation"],
  ["notionUpdate", "Notion Update"],
  ["emailSent", "Release Email"],
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

  const timelineSteps = useMemo(() => {
    if (!run) {
      return [];
    }

    return PIPELINE_STEPS.map(([key, label]) => ({
      label,
      complete: Boolean(run.pipelineStatus[key]),
      active: run.status === "RUNNING" && !run.pipelineStatus[key],
    }));
  }, [run]);

  if (isLoading) {
    return <p className="muted loading-text">Loading run...</p>;
  }

  if (error || run === null) {
    return (
      <>
        <a className="back-link" href={run?.serviceId ? `/services/${run.serviceId}` : "/"}>
          Back to service
        </a>
        <p className="error">{error || "Run not found."}</p>
      </>
    );
  }

  return (
    <>
      <a className="back-link" href={`/services/${run.serviceId}`}>
        Back to {run.serviceName}
      </a>

      <AnimatedHero
        eyebrow={`${run.teamName} / ${run.serviceName} / PR #${run.prNumber}`}
        subtitle={`${run.repository} · ${run.status.replace(/_/g, " ")}${run.changeScope ? ` · ${run.changeScope.toUpperCase()}` : ""}`}
        title={run.prTitle}
      />

      <section className="summary-panel panel panel--glass">
        <p className="eyebrow">AI Summary</p>
        <h2>What changed in this merge</h2>
        <p>{run.classification.summary || "MergeFlow classified this PR and recorded the automation outcome."}</p>
        <div className="tag-row">
          {run.classification.changeTypes.map((changeType) => (
            <span className="tag" key={changeType}>
              {changeType}
            </span>
          ))}
        </div>
      </section>

      {run.status === "TRACKED_ONLY" ? (
        <section className="panel panel--notice">
          <h2>Tracked Only</h2>
          <p>
            MergeFlow recorded this PR on the service dashboard. Full artifact generation is enabled for backend/API
            changes only.
          </p>
        </section>
      ) : null}

      <section className="panel panel--glass">
        <h2>Pipeline Timeline</h2>
        <p className="muted">Step-by-step automation progress for this merged PR.</p>
        <PipelineTimeline steps={timelineSteps} />
      </section>

      <section className="panel panel--glass">
        <h2>Generated Artifacts</h2>
        {run.status === "TRACKED_ONLY" ? (
          <p className="muted">No artifacts generated for this tracked-only change.</p>
        ) : (
          <>
            <p className="muted">
              OpenAPI, Postman, and test plans are embedded in Notion. Use the tiles below to jump to outputs.
            </p>
            <ArtifactDock artifacts={run.artifacts} />
          </>
        )}
      </section>

      {run.apiOverview.length > 0 ? (
        <section className="panel panel--glass">
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
      ) : null}

      {run.testCases.length > 0 ? (
        <section className="panel panel--glass">
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
      ) : null}
    </>
  );
}
