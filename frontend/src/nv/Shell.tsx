import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { link } from "../routes";
import "./nv.css";

// The app frame: window bar, rail, and the page. Only screens that exist appear in the rail,
// so nothing in the product is a button that does nothing.

export type Theme = "dark" | "light";
export type Screen = "leads" | "station" | "connections" | "business" | "motion";

const KEY = "nv-theme";

// The rail in the locked design's order. Items without a screen are not built yet: shown with
// "Soon", but not links and not focusable. "sep" draws the divider.
const RAIL: (readonly [string, Screen | null] | "sep")[] = [
  ["Station", "station"],
  ["Leads", "leads"],
  ["Decisions", null],
  ["Situations", null],
  ["Back in motion", "motion"],
  ["Accounts", null],
  ["Territory", null],
  ["Connections", "connections"],
  ["Editions", null],
  ["Outcomes", null],
  "sep",
  ["What I’ve learned", null],
  ["Your business", "business"],
];

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
          {RAIL.map((item, i) => {
            if (item === "sep") return <div className="sep" key={`sep${i}`} />;
            const [label, id] = item;
            if (!id)
              return (
                <span key={label} className="nv-nav off" aria-disabled="true">
                  {label}
                  <span className="soon">Soon</span>
                </span>
              );
            return (
              <a
                key={id}
                className="nv-nav"
                href={link("app", client, day, ...(id === "station" ? [] : [id]))}
                aria-current={screen === id ? "page" : undefined}
              >
                {label}
                {counts[id] !== undefined && <span className="n">{counts[id]}</span>}
              </a>
            );
          })}
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
