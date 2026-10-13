import { useEffect, useState } from "react";
import { ClientsPage } from "./pages/ClientsPage";
import { LeadsPage } from "./nv/LeadsPage";
import { StationPage } from "./nv/StationPage";
import { link } from "./routes";

// Hash routes keep the app a static bundle that any server can host:
//   #/                           clients
//   #/app/<client>/<day>         Station, the edition (day may be "latest")
//   #/app/<client>/<day>/leads   Leads, with the case as a sheet
// Older links (#/c/..., #/m/...) open Station for the same client and day.
function currentPath(): string[] {
  return window.location.hash
    .replace(/^#\/?/, "")
    .split("/")
    .filter(Boolean)
    .map(decodeURIComponent);
}

export function App() {
  const [path, setPath] = useState<string[]>(currentPath());
  useEffect(() => {
    const onChange = () => {
      setPath(currentPath());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  if (path[0] === "app" && path.length >= 3) {
    return path[3] === "leads" ? (
      <LeadsPage client={path[1]} day={path[2]} />
    ) : (
      <StationPage client={path[1]} day={path[2]} />
    );
  }
  if ((path[0] === "c" || path[0] === "m") && path.length >= 3) {
    return <StationPage client={path[1]} day={path[2]} />;
  }

  return (
    <>
      <a className="skip" href="#main" onClick={(e) => e.currentTarget.blur()}>
        Skip to content
      </a>
      <header className="top">
        <a className="brand" href={link()}>
          Northvaine
        </a>
        <span className="tag">Radar</span>
      </header>
      <main id="main" tabIndex={-1}>
        <ClientsPage />
      </main>
      <footer className="foot">
        Drafts and briefs only. A person decides and makes contact.
      </footer>
    </>
  );
}
