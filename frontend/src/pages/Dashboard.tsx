import { useEffect, useMemo, useState } from "react";

import { fetchOrganization, fetchRuns } from "../api";
import { AnimatedHero } from "../components/AnimatedHero";
import { AutomationMap } from "../components/AutomationMap";
import { BeforeAfterPanel } from "../components/BeforeAfterPanel";
import { DiffTypeFilter } from "../components/DiffTypeFilter";
import { EmptyStatePreview } from "../components/EmptyStatePreview";
import { PipelineRun } from "../components/PipelineRun";
import { RunPreviewDrawer } from "../components/RunPreviewDrawer";
import { ServiceSpotlight } from "../components/ServiceSpotlight";
import type { ChangeScope, Organization, RunSummary, Service } from "../types";

export function Dashboard() {
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [scopeFilter, setScopeFilter] = useState<ChangeScope | "all">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [previewRun, setPreviewRun] = useState<RunSummary | null>(null);

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
  const successCount = runs.filter((run) => run.status === "SUCCESS").length;
  const automatedCount = runs.filter((run) => run.action !== "track_only").length;

  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      const matchesScope = scopeFilter === "all" || run.changeScope === scopeFilter;
      const query = searchQuery.trim().toLowerCase();
      const matchesSearch =
        !query ||
        run.prTitle.toLowerCase().includes(query) ||
        run.serviceName.toLowerCase().includes(query) ||
        run.repository.toLowerCase().includes(query) ||
        String(run.prNumber).includes(query);
      return matchesScope && matchesSearch;
    });
  }, [runs, scopeFilter, searchQuery]);

  const spotlight = useMemo(() => findSpotlight(organization, runs), [organization, runs]);

  return (
    <>
      <AnimatedHero
        eyebrow="MergeFlow Command Center"
        highlight="automated"
        subtitle={
          organization?.description ??
          "Track service documentation, API specs, Postman collections, Notion updates, and release emails after PR merges."
        }
        title="Post-merge workflow,"
      />

      {isLoading ? <p className="muted loading-text">Loading command center...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {organization && !error ? (
        <>
          <section className="metrics-grid metrics-grid--animated">
            <article className="metric-card metric-card--glass">
              <p className="eyebrow">Teams</p>
              <strong>{organization.teams.length}</strong>
              <span>Engineering groups</span>
            </article>
            <article className="metric-card metric-card--glass">
              <p className="eyebrow">Services</p>
              <strong>{serviceCount}</strong>
              <span>Monitored repositories</span>
            </article>
            <article className="metric-card metric-card--glass">
              <p className="eyebrow">Runs</p>
              <strong>{runs.length}</strong>
              <span>Processed PR merges</span>
            </article>
            <article className="metric-card metric-card--glass">
              <p className="eyebrow">Automated</p>
              <strong>{automatedCount}</strong>
              <span>{successCount} successful artifact runs</span>
            </article>
          </section>

          {spotlight ? (
            <ServiceSpotlight run={spotlight.run} service={spotlight.service} teamName={spotlight.teamName} />
          ) : null}

          <AutomationMap />
          <BeforeAfterPanel />

          <section className="panel panel--glass">
            <div className="panel-header panel-header--stack">
              <div>
                <h2>Teams</h2>
                <p className="muted">Explore services and automation history by engineering group.</p>
              </div>
            </div>
            <div className="team-grid">
              {organization.teams.map((team, index) => (
                <a
                  className="team-card team-card--animated"
                  href={`/teams/${team.id}`}
                  key={team.id}
                  style={{ animationDelay: `${index * 60}ms` }}
                >
                  <p className="eyebrow">{team.services.length} services</p>
                  <h3>{team.name}</h3>
                  <p>{team.description}</p>
                </a>
              ))}
            </div>
          </section>

          <section className="panel panel--glass">
            <div className="panel-header panel-header--stack">
              <div>
                <h2>Service Catalog</h2>
                <p className="muted">Each service maps to a GitHub repository monitored by MergeFlow.</p>
              </div>
            </div>
            <div className="service-grid">
              {organization.teams.flatMap((team) =>
                team.services.map((service, index) => (
                  <ServiceCard
                    animationDelay={index * 40}
                    key={service.id}
                    runs={runs}
                    service={service}
                    teamName={team.name}
                  />
                )),
              )}
            </div>
          </section>
        </>
      ) : null}

      <section className="panel panel--glass">
        <div className="panel-header panel-header--stack">
          <div>
            <h2>Recent Runs</h2>
            <p className="muted">Preview or open a run to inspect classification, artifacts, and pipeline status.</p>
          </div>
          <div className="panel-toolbar">
            <input
              aria-label="Search runs"
              className="search-input"
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search PRs, services, repos..."
              type="search"
              value={searchQuery}
            />
            <DiffTypeFilter active={scopeFilter} onChange={setScopeFilter} />
          </div>
        </div>

        {!isLoading && !error && runs.length === 0 ? <EmptyStatePreview /> : null}
        {!isLoading && !error && runs.length > 0 && filteredRuns.length === 0 ? (
          <p className="muted">No runs match your current filters.</p>
        ) : null}

        <div className="run-list">
          {filteredRuns.map((run, index) => (
            <PipelineRun
              animationDelay={index * 50}
              key={run.id}
              onPreview={setPreviewRun}
              run={run}
            />
          ))}
        </div>
      </section>

      <RunPreviewDrawer onClose={() => setPreviewRun(null)} run={previewRun} />
    </>
  );
}

type ServiceCardProps = {
  service: Service;
  teamName: string;
  runs: RunSummary[];
  animationDelay?: number;
};

function ServiceCard({ service, teamName, runs, animationDelay = 0 }: ServiceCardProps) {
  const latestRun = runs.find((run) => run.repository === service.repository);

  return (
    <a
      className="service-card service-card--animated"
      href={`/services/${service.id}`}
      style={{ animationDelay: `${animationDelay}ms` }}
    >
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

function findSpotlight(
  organization: Organization | null,
  runs: RunSummary[],
): { run: RunSummary; service: Service; teamName: string } | null {
  if (!organization || runs.length === 0) {
    return null;
  }

  const latestRun = runs[0];
  for (const team of organization.teams) {
    const service = team.services.find((candidate) => candidate.repository === latestRun.repository);
    if (service) {
      return { run: latestRun, service, teamName: team.name };
    }
  }

  return null;
}
