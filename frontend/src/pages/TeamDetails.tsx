import { useEffect, useState } from "react";

import { fetchOrganization, fetchTeamRuns } from "../api";
import { PipelineRun } from "../components/PipelineRun";
import type { Organization, RunSummary, Team } from "../types";

type TeamDetailsProps = {
  teamId: string;
};

export function TeamDetails({ teamId }: TeamDetailsProps) {
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchOrganization(), fetchTeamRuns(teamId)])
      .then(([loadedOrganization, loadedRuns]) => {
        setOrganization(loadedOrganization);
        setRuns(loadedRuns);
      })
      .catch((loadError: Error) => setError(loadError.message))
      .finally(() => setIsLoading(false));
  }, [teamId]);

  const team = organization?.teams.find((candidate) => candidate.id === teamId);

  if (isLoading) {
    return <p className="muted loading-text">Loading team...</p>;
  }

  if (error || !team) {
    return (
      <>
        <a className="back-link" href="/">
          Back to organization
        </a>
        <p className="error">{error || "Team not found."}</p>
      </>
    );
  }

  return (
    <>
      <a className="back-link" href="/">
        Back to organization
      </a>

      <header className="hero">
        <p className="eyebrow">{organization?.name}</p>
        <h1>{team.name}</h1>
        <p className="muted">{team.description}</p>
      </header>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Owned Services</h2>
            <p className="muted">Services maintained by {team.name} and monitored by MergeFlow.</p>
          </div>
        </div>

        <div className="service-grid">
          {team.services.map((service) => (
            <TeamServiceCard key={service.id} runs={runs} service={service} team={team} />
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Team Runs</h2>
            <p className="muted">Recent PR merges and generated artifacts across this team.</p>
          </div>
        </div>

        {runs.length === 0 ? <p className="muted">No MergeFlow runs found for this team yet.</p> : null}
        <div className="run-list">
          {runs.map((run) => (
            <PipelineRun key={run.id} run={run} />
          ))}
        </div>
      </section>
    </>
  );
}

type TeamServiceCardProps = {
  team: Team;
  service: Team["services"][number];
  runs: RunSummary[];
};

function TeamServiceCard({ team, service, runs }: TeamServiceCardProps) {
  const latestRun = runs.find((run) => run.repository === service.repository);

  return (
    <a className="service-card" href={`/services/${service.id}`}>
      <div>
        <p className="eyebrow">{team.name}</p>
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
