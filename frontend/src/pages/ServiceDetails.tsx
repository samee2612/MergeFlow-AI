import { useEffect, useState } from "react";

import { fetchOrganization, fetchServiceRuns } from "../api";
import { PipelineRun } from "../components/PipelineRun";
import type { Organization, RunSummary, Service, Team } from "../types";

type ServiceDetailsProps = {
  serviceId: string;
};

export function ServiceDetails({ serviceId }: ServiceDetailsProps) {
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchOrganization(), fetchServiceRuns(serviceId)])
      .then(([loadedOrganization, loadedRuns]) => {
        setOrganization(loadedOrganization);
        setRuns(loadedRuns);
      })
      .catch((loadError: Error) => setError(loadError.message))
      .finally(() => setIsLoading(false));
  }, [serviceId]);

  const match = findService(organization, serviceId);

  if (isLoading) {
    return <p className="muted loading-text">Loading service...</p>;
  }

  if (error || !match) {
    return (
      <>
        <a className="back-link" href="/">
          Back to organization
        </a>
        <p className="error">{error || "Service not found."}</p>
      </>
    );
  }

  const { service, team } = match;
  const latestRun = runs[0];

  return (
    <>
      <a className="back-link" href={`/teams/${team.id}`}>
        Back to {team.name}
      </a>

      <header className="hero">
        <p className="eyebrow">{team.name}</p>
        <h1>{service.name}</h1>
        <p className="muted">{service.description}</p>
      </header>

      <section className="metrics-grid">
        <article className="metric-card">
          <p className="eyebrow">Repository</p>
          <strong className="metric-card__text">{service.repository}</strong>
          <span>Connected GitHub service repo</span>
        </article>
        <article className="metric-card">
          <p className="eyebrow">Runs</p>
          <strong>{runs.length}</strong>
          <span>PRs processed by MergeFlow</span>
        </article>
        <article className="metric-card">
          <p className="eyebrow">Latest Status</p>
          {latestRun ? (
            <strong className={`metric-card__status metric-card__status--${latestRun.status.toLowerCase()}`}>
              {latestRun.status}
            </strong>
          ) : (
            <strong className="metric-card__status metric-card__status--empty">NO RUNS</strong>
          )}
          <span>Docs and artifacts state</span>
        </article>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Service Workflow</h2>
            <p className="muted">MergeFlow resolves the service, classifies the change, and runs full automation for backend/API PRs.</p>
          </div>
        </div>

        <div className="workflow-grid">
          <span>Service resolution</span>
          <span>Change scope classification</span>
          <span>API artifact generation</span>
          <span>OpenAPI and Postman</span>
          <span>Notion and email</span>
          <span>Dashboard update</span>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Service Runs</h2>
            <p className="muted">Open a run to see generated API docs, OpenAPI YAML, Postman collection, and Notion links.</p>
          </div>
        </div>

        {runs.length === 0 ? <p className="muted">No MergeFlow runs found for this service yet.</p> : null}
        <div className="run-list">
          {runs.map((run) => (
            <PipelineRun key={run.id} run={run} />
          ))}
        </div>
      </section>
    </>
  );
}

function findService(
  organization: Organization | null,
  serviceId: string,
): { team: Team; service: Service } | null {
  if (!organization) {
    return null;
  }

  for (const team of organization.teams) {
    const service = team.services.find((candidate) => candidate.id === serviceId);
    if (service) {
      return { team, service };
    }
  }

  return null;
}
