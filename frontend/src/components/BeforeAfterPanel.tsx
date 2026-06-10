const MANUAL_TASKS = [
  "Manually prepare API documentation",
  "Refresh OpenAPI specifications",
  "Package validation artifacts",
  "Update the team knowledge base",
  "Draft stakeholder communications",
];

const AUTOMATED_TASKS = [
  "AI-assisted change analysis",
  "Validated OpenAPI deliverables",
  "Import-ready test collections",
  "Structured service documentation",
  "Release summary distribution",
];

export function BeforeAfterPanel() {
  return (
    <section className="before-after panel panel--glass">
      <div className="panel-header">
        <div>
          <h2>Manual vs MergeFlow</h2>
          <p className="muted">Standardize post-merge handoffs without adding operational overhead.</p>
        </div>
      </div>
      <div className="before-after__grid">
        <article className="before-after__column before-after__column--manual">
          <p className="eyebrow">Before</p>
          <h3>Manual process</h3>
          <ul>
            {MANUAL_TASKS.map((task) => (
              <li key={task}>{task}</li>
            ))}
          </ul>
        </article>
        <article className="before-after__column before-after__column--automated">
          <p className="eyebrow">After</p>
          <h3>MergeFlow governed</h3>
          <ul>
            {AUTOMATED_TASKS.map((task) => (
              <li key={task}>{task}</li>
            ))}
          </ul>
        </article>
      </div>
    </section>
  );
}
