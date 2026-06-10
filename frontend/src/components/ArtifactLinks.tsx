import type { ArtifactLink } from "../types";

type ArtifactLinksProps = {
  artifacts: Record<string, ArtifactLink>;
};

export function ArtifactLinks({ artifacts }: ArtifactLinksProps) {
  return (
    <div className="artifact-grid">
      {Object.entries(artifacts).map(([key, artifact]) => (
        <article className="artifact-card" key={key}>
          <div>
            <p className="eyebrow">Artifact</p>
            <h3>{artifact.label}</h3>
          </div>
          {artifact.url ? (
            <a className="button" href={artifact.url} rel="noreferrer" target="_blank">
              View
            </a>
          ) : key === "emailSummary" ? (
            <span className="button button--disabled">Delivered via SendGrid</span>
          ) : (
            <span className="button button--disabled">Unavailable</span>
          )}
        </article>
      ))}
    </div>
  );
}
