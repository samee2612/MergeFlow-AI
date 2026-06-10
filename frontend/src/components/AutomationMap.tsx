const STEPS = [
  { id: "merge", label: "Merge Captured", detail: "GitHub webhook records the approved change" },
  { id: "classify", label: "Impact Classified", detail: "Scope and service context are identified" },
  { id: "generate", label: "Artifacts Prepared", detail: "API docs, OpenAPI, and Postman outputs" },
  { id: "notion", label: "Knowledge Updated", detail: "Service documentation is refreshed" },
  { id: "email", label: "Stakeholders Notified", detail: "Release summary delivered to the team" },
];

export function AutomationMap() {
  return (
    <section className="automation-map panel panel--glass">
      <div className="panel-header">
        <div>
          <h2>Automation Flow</h2>
          <p className="muted">A controlled handoff from merged code to operational documentation.</p>
        </div>
      </div>
      <div className="automation-map__track">
        {STEPS.map((step, index) => (
          <div className="automation-map__step" key={step.id} style={{ animationDelay: `${index * 80}ms` }}>
            <div className="automation-map__node">
              <span className="automation-map__index">{index + 1}</span>
            </div>
            <div className="automation-map__content">
              <strong>{step.label}</strong>
              <span>{step.detail}</span>
            </div>
            {index < STEPS.length - 1 ? <div className="automation-map__connector" aria-hidden="true" /> : null}
          </div>
        ))}
      </div>
    </section>
  );
}
