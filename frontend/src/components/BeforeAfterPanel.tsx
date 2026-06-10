const MANUAL_TASKS = [
  "Write API documentation",
  "Update OpenAPI spec",
  "Build Postman collection",
  "Update Notion workspace",
  "Send release email",
];

const AUTOMATED_TASKS = [
  "Gemini-generated API analysis",
  "Validated OpenAPI YAML",
  "Import-ready Postman JSON",
  "Structured Notion pages",
  "SendGrid release summary",
];

export function BeforeAfterPanel() {
  return (
    <section className="before-after panel panel--glass">
      <div className="panel-header">
        <div>
          <h2>Manual vs MergeFlow</h2>
          <p className="muted">What your team skips after every merged PR.</p>
        </div>
      </div>
      <div className="before-after__grid">
        <article className="before-after__column before-after__column--manual">
          <p className="eyebrow">Before</p>
          <h3>Manual handoff</h3>
          <ul>
            {MANUAL_TASKS.map((task) => (
              <li key={task}>{task}</li>
            ))}
          </ul>
        </article>
        <article className="before-after__column before-after__column--automated">
          <p className="eyebrow">After</p>
          <h3>MergeFlow generated</h3>
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
