import type { ReactNode } from "react";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="app-shell">
      <div className="app-shell__glow app-shell__glow--one" aria-hidden="true" />
      <div className="app-shell__glow app-shell__glow--two" aria-hidden="true" />

      <header className="top-nav">
        <a className="brand" href="/">
          <span className="brand__mark">MF</span>
          <span className="brand__text">
            MergeFlow <span className="brand__accent">AI</span>
          </span>
        </a>
        <nav className="top-nav__links">
          <a href="/">Command Center</a>
        </nav>
      </header>

      <main className="page">{children}</main>
    </div>
  );
}
