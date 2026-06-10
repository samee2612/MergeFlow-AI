import type { RunSummary } from "../types";
import { formatScope, formatStatus, formatTimestamp } from "../utils/formatters";

type RunPreviewDrawerProps = {
  run: RunSummary | null;
  onClose: () => void;
};

export function RunPreviewDrawer({ run, onClose }: RunPreviewDrawerProps) {
  if (!run) {
    return null;
  }

  return (
    <>
      <button aria-label="Close run preview" className="drawer-backdrop" onClick={onClose} type="button" />
      <aside className="run-drawer">
        <div className="run-drawer__header">
          <div>
            <p className="eyebrow">
              {run.serviceName} · PR #{run.prNumber}
            </p>
            <h2>{run.prTitle}</h2>
          </div>
          <button className="drawer-close" onClick={onClose} type="button">
            ×
          </button>
        </div>

        <div className="run-drawer__body">
          <div className="run-drawer__meta">
            <span className={`status status--${run.status.toLowerCase()}`}>{formatStatus(run.status)}</span>
            <time>{formatTimestamp(run.timestamp)}</time>
          </div>

          <p className="muted">{run.repository}</p>

          {run.changeScope ? (
            <div className="tag-row">
              <span className="tag">{formatScope(run.changeScope)}</span>
              {run.action === "track_only" ? <span className="tag tag--muted">Tracked only</span> : null}
            </div>
          ) : null}

          <div className="run-drawer__preview-steps">
            <div className="run-drawer__step">
              <span className="check">✓</span> Service resolved
            </div>
            <div className="run-drawer__step">
              <span className="check">✓</span> Change classified
            </div>
            <div className="run-drawer__step">
              <span className={run.action === "track_only" ? "check check--muted" : "check"}>
                {run.action === "track_only" ? "○" : "✓"}
              </span>
              {run.action === "track_only" ? "Artifacts skipped" : "Artifacts generated"}
            </div>
          </div>
        </div>

        <div className="run-drawer__footer">
          <a className="button button--ghost" href={`/services/${run.serviceId}`}>
            Service page
          </a>
          <a className="button" href={`/runs/${encodeURIComponent(run.id)}`}>
            Full run details
          </a>
        </div>
      </aside>
    </>
  );
}
