import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { BriefPage } from "./pages/BriefPage";
import { ClientsPage } from "./pages/ClientsPage";
import { DossierPage } from "./pages/DossierPage";
import { MorningPage } from "./pages/MorningPage";
import { link } from "./routes";

// Hash routes keep the app a static bundle that any server can host:
//   #/                      clients
//   #/c/<client>/<day>      brief (day may be "latest")
//   #/c/<client>/<day>/e/<rank>   dossier
//   #/m/<client>/<day>      the Morning (day may be "latest")
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

  if (path[0] === "m" && path.length >= 3) {
    return <MorningPage client={path[1]} day={path[2]} />;
  }

  let page: ReactNode;
  if (path[0] === "c" && path.length >= 3 && path[3] === "e" && path[4]) {
    const rank = Number(path[4]);
    page = Number.isInteger(rank) ? (
      <DossierPage client={path[1]} day={path[2]} rank={rank} />
    ) : (
      <p role="alert">That entry link is not valid.</p>
    );
  } else if (path[0] === "c" && path.length >= 3) {
    page = <BriefPage client={path[1]} day={path[2]} />;
  } else {
    page = <ClientsPage />;
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
        {page}
      </main>
      <footer className="foot">
        Drafts and briefs only. A person decides and makes contact.
      </footer>
    </>
  );
}
