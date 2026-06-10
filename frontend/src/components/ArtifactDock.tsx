import type { ArtifactLink } from "../types";

const ARTIFACT_ICONS: Record<string, string> = {
  notionServicePage: "N",
  notionPrReview: "P",
  githubPullRequest: "G",
  emailSummary: "@",
};

type ArtifactDockProps = {
  artifacts: Record<string, ArtifactLink>;
};

export function ArtifactDock({ artifacts }: ArtifactDockProps) {
  return (
    <div className="artifact-dock">
      {Object.entries(artifacts).map(([key, artifact]) => (
        <article className={`artifact-tile${artifact.url ? " artifact-tile--active" : ""}`} key={key}>
          <div className="artifact-tile__icon">{ARTIFACT_ICONS[key] ?? "•"}</div>
          <div>
            <p className="eyebrow">Output</p>
            <h3>{artifact.label}</h3>
          </div>
          {artifact.url ? (
            <a className="artifact-tile__link" href={artifact.url} rel="noreferrer" target="_blank">
              Open
            </a>
          ) : key === "emailSummary" ? (
            <span className="artifact-tile__status">Delivered</span>
          ) : (
            <span className="artifact-tile__status artifact-tile__status--muted">Unavailable</span>
          )}
        </article>
      ))}
    </div>
  );
}
