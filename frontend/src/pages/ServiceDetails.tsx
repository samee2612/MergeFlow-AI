import { useEffect, useMemo, useState } from "react";

import { fetchOrganization, fetchServiceRuns } from "../api";
import type { Organization, RunSummary, Service, Team } from "../types";
import { formatRelativeTime, formatStatus } from "../utils/formatters";

type ServiceDetailsProps = {
  serviceId: string;
};

type FeatureGroup = {
  id: string;
  branchName: string;
  label: string;
  latestRun: RunSummary;
  runs: RunSummary[];
  authors: string[];
  summary: string;
};

export function ServiceDetails({ serviceId }: ServiceDetailsProps) {
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [animationCycle, setAnimationCycle] = useState(0);

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
  const featureGroups = useMemo(() => groupRunsByFeature(runs), [runs]);

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
  const selectedFeature = featureGroups.find((feature) => feature.id === selectedFeatureId) ?? featureGroups[0];
  const serviceActivitySummary = buildServiceActivitySummary(service, featureGroups);

  return (
    <>
      <a className="back-link" href={`/teams/${team.id}`}>
        Back to {team.name}
      </a>

      <header className="hero">
        <p className="eyebrow">{team.name}</p>
        <h1>{service.name}</h1>
        <p className="muted">{service.description}</p>
        <p className="service-brief">{serviceActivitySummary}</p>
      </header>

      <section className="metrics-grid">
        <a className="metric-card metric-card--link" href={`https://github.com/${service.repository}`} rel="noreferrer" target="_blank">
          <p className="eyebrow">Repository</p>
          <strong className="metric-card__text">{service.repository}</strong>
          <span>Open the connected source repository</span>
        </a>
        <a className="metric-card metric-card--link" href="#service-features">
          <p className="eyebrow">Feature Branches</p>
          <strong>{featureGroups.length}</strong>
          <span>Branch-level features processed for this service</span>
        </a>
      </section>

      <section className="panel panel--glass" id="service-features">
        <div className="panel-header">
          <div>
            <h2>Service Features</h2>
            <p className="muted">
              Branches are treated as feature streams. Open a feature to see the accumulated PR activity and pipeline state.
            </p>
          </div>
        </div>

        {featureGroups.length === 0 ? <p className="muted">No feature branches have been processed for this service yet.</p> : null}
        {featureGroups.length > 0 ? (
          <div className="feature-layout">
            <div className="feature-grid">
              {featureGroups.map((feature, index) => (
                <button
                  className={`feature-card${selectedFeature?.id === feature.id ? " feature-card--active" : ""}`}
                  key={feature.id}
                  onClick={() => {
                    setSelectedFeatureId(feature.id);
                    setAnimationCycle((cycle) => cycle + 1);
                  }}
                  style={{ animationDelay: `${index * 60}ms` }}
                  type="button"
                >
                  <div>
                    <p className="eyebrow">{feature.label}</p>
                    <h3>{feature.branchName}</h3>
                    <p className="muted">{feature.summary}</p>
                  </div>
                  <div className="feature-card__footer">
                    <span className={`status status--${feature.latestRun.status.toLowerCase()}`}>
                      {formatStatus(feature.latestRun.status)}
                    </span>
                    <span>{feature.runs.length} merged PR{feature.runs.length === 1 ? "" : "s"}</span>
                  </div>
                </button>
              ))}
            </div>

            {selectedFeature ? (
              <FeatureDetail
                animationKey={`${selectedFeature.id}-${animationCycle}`}
                feature={selectedFeature}
                service={service}
                team={team}
              />
            ) : null}
          </div>
        ) : null}
      </section>
    </>
  );
}

type FeatureDetailProps = {
  animationKey: string;
  feature: FeatureGroup;
  service: Service;
  team: Team;
};

function FeatureDetail({ animationKey, feature, service, team }: FeatureDetailProps) {
  const steps = pipelineStepsForFeature(feature.latestRun);

  return (
    <article className="feature-detail">
      <div className="feature-detail__header">
        <div>
          <p className="eyebrow">Feature Intelligence</p>
          <h3>{feature.branchName}</h3>
        </div>
        <span className={`status status--${feature.latestRun.status.toLowerCase()}`}>
          {formatStatus(feature.latestRun.status)}
        </span>
      </div>

      <p className="feature-detail__summary">
        {service.name} has accumulated {feature.runs.length} merged PR{feature.runs.length === 1 ? "" : "s"} under
        this feature for {team.name}. Current feature description: {feature.summary}
      </p>

      <div className="feature-detail__meta">
        <span>Author: {feature.authors.join(", ") || "GitHub author"}</span>
        <span>Team: {team.name}</span>
        <span>Latest update: {formatRelativeTime(feature.latestRun.timestamp)}</span>
      </div>

      <div className="feature-pipeline" key={animationKey}>
        {steps.map((step, index) => (
          <div
            className={`feature-pipeline__step${step.complete ? " feature-pipeline__step--complete" : ""}`}
            key={step.label}
            style={{ animationDelay: `${index * 120}ms` }}
          >
            <span className={step.complete ? "check" : "check check--muted"}>{step.complete ? "✓" : "○"}</span>
            <span>{step.label}</span>
          </div>
        ))}
      </div>

      <div className="feature-pr-list">
        <p className="section-label">Merged PRs in this feature</p>
        {feature.runs.map((run) => (
          <a className="feature-pr-row" href={`/runs/${encodeURIComponent(run.id)}`} key={run.id}>
            <span>PR #{run.prNumber}</span>
            <strong>{run.prTitle}</strong>
          </a>
        ))}
      </div>
    </article>
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

function groupRunsByFeature(runs: RunSummary[]): FeatureGroup[] {
  const groups = new Map<string, RunSummary[]>();

  for (const run of runs) {
    const featureKey = normalizedFeatureKey(run);
    const groupRuns = groups.get(featureKey) ?? [];
    groupRuns.push(run);
    groups.set(featureKey, groupRuns);
  }

  return Array.from(groups.entries()).map(([featureKey, groupRuns]) => {
    const sortedRuns = [...groupRuns].sort(
      (left, right) => new Date(right.timestamp).getTime() - new Date(left.timestamp).getTime(),
    );
    const latestRun = sortedRuns[0];
    const authors = Array.from(new Set(sortedRuns.map((run) => run.author).filter(Boolean))) as string[];
    const hasBranchName = Boolean(latestRun.headBranch?.trim());

    return {
      id: featureKey,
      branchName: displayFeatureName(latestRun),
      label: hasBranchName ? "Feature Branch" : "Feature",
      latestRun,
      runs: sortedRuns,
      authors,
      summary: buildAccumulatedFeatureSummary(sortedRuns),
    };
  });
}

function normalizedFeatureKey(run: RunSummary) {
  const branch = run.headBranch?.trim();
  if (branch) {
    return `branch:${branch.toLowerCase()}`;
  }

  return `title:${slugify(run.prTitle || `pr-${run.prNumber}`)}`;
}

function displayFeatureName(run: RunSummary) {
  return run.headBranch?.trim() || run.prTitle || `Feature PR #${run.prNumber}`;
}

function buildAccumulatedFeatureSummary(runs: RunSummary[]) {
  const titles = uniqueNonEmpty(runs.map((run) => run.prTitle));
  if (titles.length === 0) {
    return "This feature has processed changes, but no PR summary is available yet.";
  }
  if (titles.length === 1) {
    return titles[0];
  }

  return titles
    .slice()
    .reverse()
    .map((title, index) => `${index + 1}. ${title}`)
    .join(" ");
}

function buildServiceActivitySummary(service: Service, features: FeatureGroup[]) {
  if (features.length === 0) {
    return `${service.name} has no merged feature activity yet. Once changes land, this description will summarize the active service capabilities and delivery updates.`;
  }

  const uniqueSummaries = uniqueNonEmpty(features.flatMap((feature) => feature.runs.map((run) => run.prTitle)));
  const totalPrs = features.reduce((count, feature) => count + feature.runs.length, 0);
  const summaryText = uniqueSummaries.slice(0, 3).join("; ");
  const overflow = uniqueSummaries.length > 3 ? `, plus ${uniqueSummaries.length - 3} more updates` : "";

  return `${service.name} currently reflects ${features.length} feature stream${features.length === 1 ? "" : "s"} across ${totalPrs} merged PR${totalPrs === 1 ? "" : "s"}: ${summaryText}${overflow}.`;
}

function uniqueNonEmpty(values: Array<string | undefined>) {
  return Array.from(new Set(values.map((value) => value?.trim()).filter(Boolean))) as string[];
}

function slugify(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function pipelineStepsForFeature(run: RunSummary) {
  const generatedArtifacts = run.action !== "track_only" && run.status !== "FAILED" && run.status !== "IGNORED";
  const completedHandoff = run.status === "SUCCESS" || run.status === "NEEDS_ATTENTION";

  return [
    { label: "PR merged", complete: true },
    { label: "Service resolved", complete: true },
    { label: "Change classified", complete: Boolean(run.changeScope) },
    { label: "Artifacts evaluated", complete: generatedArtifacts || run.action === "track_only" },
    { label: "Knowledge handoff updated", complete: completedHandoff },
  ];
}
