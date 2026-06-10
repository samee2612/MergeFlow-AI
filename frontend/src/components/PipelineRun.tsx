import type { RunSummary } from "../types";
import { formatRelativeTime, formatScope, formatStatus } from "../utils/formatters";

type PipelineRunProps = {
  run: RunSummary;
  onPreview?: (run: RunSummary) => void;
  animationDelay?: number;
};

export function PipelineRun({ run, onPreview, animationDelay = 0 }: PipelineRunProps) {
  return (
    <article
      className="run-card run-card--interactive"
      style={{ animationDelay: `${animationDelay}ms` }}
    >
      <div className="run-card__main">
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

      <div className="run-card__actions">
        <div className="run-card__meta">
          <span className={`status status--${run.status.toLowerCase()}${run.status === "RUNNING" ? " status--pulse" : ""}`}>
            {formatStatus(run.status)}
          </span>
          <time title={run.timestamp}>{formatRelativeTime(run.timestamp)}</time>
        </div>
        <div className="run-card__buttons">
          {onPreview ? (
            <button className="button button--ghost button--small" onClick={() => onPreview(run)} type="button">
              Preview
            </button>
          ) : null}
          <a className="button button--small" href={`/runs/${encodeURIComponent(run.id)}`}>
            Details
          </a>
        </div>
      </div>
    </article>
  );
}
