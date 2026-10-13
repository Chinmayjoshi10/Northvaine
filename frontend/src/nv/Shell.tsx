import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { link } from "../routes";
import "./nv.css";

// The app frame: window bar, rail, and the page. Only screens that exist appear in the rail,
// so nothing in the product is a button that does nothing.

export type Theme = "dark" | "light";
export type Screen = "leads" | "station";

const KEY = "nv-theme";

function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch {
    // storage blocked (private window): fall through to the system setting
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const choose = (t: Theme) => {
    setTheme(t);
    try {
      localStorage.setItem(KEY, t);
    } catch {
      // the choice still applies for this visit
    }
  };
  return [theme, choose];
}

export function Shell(props: {
  client: string;
  day: string;
  screen: Screen;
  crumb: ReactNode;
  counts?: Partial<Record<Screen, number>>;
  peek?: boolean;
  /** Rendered outside the scaled body, so a sheet is not dimmed with the list behind it. */
  overlay?: ReactNode;
  children: ReactNode;
}) {
  const {
    client,
    day,
    screen,
    crumb,
    counts = {},
    peek = false,
    overlay,
    children,
  } = props;
  const [theme, setTheme] = useTheme();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  const time = now.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });

  const nav: { id: Screen; label: string }[] = [
    { id: "station", label: "Station" },
    { id: "leads", label: "Leads" },
  ];

  return (
    <div className={`nv${peek ? " peek" : ""}`} data-theme={theme}>
      <header className="nv-bar">
        <a className="nv-word" href={link("app", client, day)}>
          NORTHVAINE
        </a>
        <span className="nv-crumb">{crumb}</span>
        <div
          className="nv-ask"
          aria-disabled="true"
          title="Ask Northvaine is coming soon"
        >
          Ask about your market…<kbd>⌘ K</kbd>
        </div>
        <div className="nv-toggle" role="group" aria-label="Theme">
          {(["dark", "light"] as const).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={theme === t}
              onClick={() => setTheme(t)}
            >
              {t === "dark" ? "Dark" : "Light"}
            </button>
          ))}
        </div>
        <span className="nv-live mono">
          <i />
          watching · {time}
        </span>
      </header>
      <div className="nv-body">
        <nav className="nv-rail" aria-label="Screens">
          {nav.map((n) => (
            <a
              key={n.id}
              className="nv-nav"
              href={link("app", client, day, ...(n.id === "station" ? [] : [n.id]))}
              aria-current={screen === n.id ? "page" : undefined}
            >
              {n.label}
              {counts[n.id] !== undefined && (
                <span className="n">{counts[n.id]}</span>
              )}
            </a>
          ))}
          <div className="foot">
            <span className="mono">{client.replace(/_/g, " ")}</span>
          </div>
        </nav>
        <main className="nv-main" id="main" tabIndex={-1}>
          {children}
        </main>
      </div>
      {overlay}
    </div>
  );
}
