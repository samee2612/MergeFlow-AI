type AnimatedHeroProps = {
  eyebrow: string;
  title: string;
  subtitle: string;
  highlight?: string;
};

export function AnimatedHero({ eyebrow, title, subtitle, highlight }: AnimatedHeroProps) {
  return (
    <header className="hero hero--animated">
      <div className="hero__glow" aria-hidden="true" />
      <p className="eyebrow hero__eyebrow">{eyebrow}</p>
      <h1 className="hero__title">
        {title}
        {highlight ? <span className="hero__gradient-text"> {highlight}</span> : null}
      </h1>
      <p className="hero__subtitle">{subtitle}</p>
    </header>
  );
}
