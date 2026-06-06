import type { RunSummary } from "../types";

type PipelineRunProps = {
  run: RunSummary;
};

export function PipelineRun({ run }: PipelineRunProps) {
  return (
    <a className="run-card" href={`/runs/${encodeURIComponent(run.id)}`}>
      <div>
        <p className="eyebrow">PR #{run.prNumber}</p>
        <h2>{run.prTitle}</h2>
        <p className="muted">{run.repository}</p>
      </div>
      <div className="run-card__meta">
        <span className={`status status--${run.status.toLowerCase()}`}>{run.status}</span>
        <time>{formatTimestamp(run.timestamp)}</time>
      </div>
    </a>
  );
}

function formatTimestamp(timestamp: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestamp));
}
