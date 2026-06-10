const STEPS = [
  { id: "merge", label: "PR Merged", detail: "GitHub webhook fires on merge" },
  { id: "classify", label: "Classify", detail: "Scope and change type detected" },
  { id: "generate", label: "Generate", detail: "API docs, OpenAPI, Postman" },
  { id: "notion", label: "Notion", detail: "Service and PR pages updated" },
  { id: "email", label: "Notify", detail: "Release summary email sent" },
];

export function AutomationMap() {
  return (
    <section className="automation-map panel panel--glass">
      <div className="panel-header">
        <div>
          <h2>Automation Flow</h2>
          <p className="muted">Hover each step to see what MergeFlow handles after merge.</p>
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
