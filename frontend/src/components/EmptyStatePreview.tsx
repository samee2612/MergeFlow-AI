export function EmptyStatePreview() {
  return (
    <section className="empty-preview panel panel--glass">
      <div className="empty-preview__glow" aria-hidden="true" />
      <p className="eyebrow">Preview</p>
      <h2>Your first merge run will appear here</h2>
      <p className="muted">
        Merge a PR on a connected service repo. MergeFlow will classify the change, generate artifacts, update Notion,
        and send a release email.
      </p>
      <div className="empty-preview__timeline">
        {["PR merged", "Classified", "Docs generated", "Notion updated", "Email sent"].map((step, index) => (
          <div className="empty-preview__step" key={step} style={{ animationDelay: `${index * 120}ms` }}>
            <span className="empty-preview__dot" />
            <span>{step}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
