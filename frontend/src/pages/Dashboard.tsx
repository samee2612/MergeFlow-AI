import { useEffect, useState } from "react";

import { fetchOrganization, fetchRuns } from "../api";
import { PipelineRun } from "../components/PipelineRun";
import type { Organization, RunSummary, Service } from "../types";

export function Dashboard() {
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchOrganization(), fetchRuns()])
      .then(([loadedOrganization, loadedRuns]) => {
        setOrganization(loadedOrganization);
        setRuns(loadedRuns);
      })
      .catch((loadError: Error) => setError(loadError.message))
      .finally(() => setIsLoading(false));
  }, []);

  const serviceCount = organization?.teams.reduce((count, team) => count + team.services.length, 0) ?? 0;

  return (
    <main className="page">
      <header className="hero">
        <p className="eyebrow">MergeFlow Enterprise Dashboard</p>
        <h1>{organization?.name ?? "Engineering Organization"}</h1>
        <p className="muted">
          {organization?.description ??
            "Track service documentation, API specs, Postman collections, Notion updates, and release emails after PR merges."}
        </p>
      </header>

      {isLoading ? <p className="muted">Loading enterprise dashboard...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {organization && !error ? (
        <>
          <section className="metrics-grid">
            <article className="metric-card">
              <p className="eyebrow">Teams</p>
              <strong>{organization.teams.length}</strong>
              <span>Engineering groups</span>
            </article>
            <article className="metric-card">
              <p className="eyebrow">Services</p>
              <strong>{serviceCount}</strong>
              <span>Repository-backed services</span>
            </article>
            <article className="metric-card">
              <p className="eyebrow">Runs</p>
              <strong>{runs.length}</strong>
              <span>Documented PR merges</span>
            </article>
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <h2>Teams</h2>
                <p className="muted">Select a team to inspect its services and generated MergeFlow artifacts.</p>
              </div>
            </div>

            <div className="team-grid">
              {organization.teams.map((team) => (
                <a className="team-card" href={`/teams/${team.id}`} key={team.id}>
                  <p className="eyebrow">{team.services.length} services</p>
                  <h3>{team.name}</h3>
                  <p>{team.description}</p>
                </a>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <h2>Service Catalog</h2>
                <p className="muted">Each service maps to a GitHub repository monitored by MergeFlow.</p>
              </div>
            </div>

            <div className="service-grid">
              {organization.teams.flatMap((team) =>
                team.services.map((service) => (
                  <ServiceCard key={service.id} runs={runs} service={service} teamName={team.name} />
                )),
              )}
            </div>
          </section>
        </>
      ) : null}

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Recent Enterprise Runs</h2>
            <p className="muted">Click a run to inspect classification, APIs, test cases, and generated artifacts.</p>
          </div>
        </div>

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

type ServiceCardProps = {
  service: Service;
  teamName: string;
  runs: RunSummary[];
};

function ServiceCard({ service, teamName, runs }: ServiceCardProps) {
  const latestRun = runs.find((run) => run.repository === service.repository);

  return (
    <a className="service-card" href={`/services/${service.id}`}>
      <div>
        <p className="eyebrow">{teamName}</p>
        <h3>{service.name}</h3>
        <p>{service.description}</p>
      </div>
      <div className="service-card__footer">
        <span className="repo-label">{service.repository}</span>
        {latestRun ? (
          <span className={`status status--${latestRun.status.toLowerCase()}`}>{latestRun.status}</span>
        ) : (
          <span className="status status--empty">NO RUNS YET</span>
        )}
      </div>
    </a>
  );
}
