import type { RunSummary } from "../types";

type PipelineRunProps = {
  run: RunSummary;
};

export function PipelineRun({ run }: PipelineRunProps) {
  return (
    <a className="run-card" href={`/runs/${encodeURIComponent(run.id)}`}>
      <div>
        <p className="eyebrow">
          {run.serviceName} · PR #{run.prNumber}
        </p>
        <h2>{run.prTitle}</h2>
        <p className="muted">
          {run.teamName} · {run.repository}
        </p>
        {run.changeScope ? (
          <div className="tag-row tag-row--compact">
            <span className="tag">{formatScope(run.changeScope)}</span>
            {run.action === "track_only" ? <span className="tag tag--muted">Tracked only</span> : null}
          </div>
        ) : null}
      </div>
      <div className="run-card__meta">
        <span className={`status status--${run.status.toLowerCase()}`}>{formatStatus(run.status)}</span>
        <time>{formatTimestamp(run.timestamp)}</time>
      </div>
    </a>
  );
}

function formatScope(scope: string) {
  return scope.charAt(0).toUpperCase() + scope.slice(1);
}

function formatStatus(status: string) {
  return status.replace(/_/g, " ");
}

function formatTimestamp(timestamp: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestamp));
}
