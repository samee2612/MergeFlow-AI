type PipelineTimelineProps = {
  steps: Array<{ label: string; complete: boolean; active?: boolean }>;
};

export function PipelineTimeline({ steps }: PipelineTimelineProps) {
  return (
    <div className="pipeline-timeline">
      {steps.map((step, index) => (
        <div
          className={`pipeline-timeline__item${step.complete ? " pipeline-timeline__item--complete" : ""}${step.active ? " pipeline-timeline__item--active" : ""}`}
          key={step.label}
          style={{ animationDelay: `${index * 100}ms` }}
        >
          <div className="pipeline-timeline__marker">
            {step.complete ? "✓" : step.active ? <span className="pulse-dot" /> : "○"}
          </div>
          <div className="pipeline-timeline__content">
            <strong>{step.label}</strong>
            <span>{step.complete ? "Completed" : step.active ? "In progress" : "Pending"}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
