import type { RunSummary, Service } from "../types";
import { formatRelativeTime, formatStatus } from "../utils/formatters";

type ServiceSpotlightProps = {
  run: RunSummary;
  service: Service;
  teamName: string;
};

export function ServiceSpotlight({ run, service, teamName }: ServiceSpotlightProps) {
  const author = run.author || "GitHub author";

  return (
    <section className="spotlight panel panel--glass">
      <div className="spotlight__badge">Latest Automation</div>
      <div className="spotlight__content">
        <div className="spotlight__primary">
          <p className="eyebrow">Service</p>
          <h2>{service.name}</h2>
          <p className="spotlight__summary">
            PR #{run.prNumber}: {run.prTitle}
          </p>
          <div className="spotlight__details">
            <span>Published by {author}</span>
            <span>{teamName}</span>
          </div>
        </div>
        <div className="spotlight__meta">
          <span className={`status status--${run.status.toLowerCase()}`}>{formatStatus(run.status)}</span>
          <span className="spotlight__time">{formatRelativeTime(run.timestamp)}</span>
        </div>
      </div>
      <div className="spotlight__actions">
        <a className="button" href={`/services/${service.id}`}>
          View service
        </a>
        <a className="button button--ghost" href={`/runs/${encodeURIComponent(run.id)}`}>
          Open run
        </a>
      </div>
    </section>
  );
}
