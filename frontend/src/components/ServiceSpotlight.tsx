import type { RunSummary, Service } from "../types";
import { formatRelativeTime, formatStatus } from "../utils/formatters";

type ServiceSpotlightProps = {
  run: RunSummary;
  service: Service;
  teamName: string;
};

export function ServiceSpotlight({ run, service, teamName }: ServiceSpotlightProps) {
  return (
    <section className="spotlight panel panel--glass">
      <div className="spotlight__badge">Latest automation</div>
      <div className="spotlight__content">
        <div>
          <p className="eyebrow">{teamName}</p>
          <h2>{service.name}</h2>
          <p className="muted">{run.prTitle}</p>
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
