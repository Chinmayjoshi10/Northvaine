import { useEffect, useState } from "react";
import { LandingPage } from "./pages/LandingPage";
import { ClientsPage } from "./pages/ClientsPage";
import { ContactPage } from "./pages/ContactPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { LeadsPage } from "./nv/LeadsPage";
import { CasePage } from "./nv/CasePage";
import { StationPage } from "./nv/StationPage";
import { link } from "./routes";

// Hash routes keep the app a static bundle that any server can host:
//   #/                           landing page
//   #/clients                    clients
//   #/contact[/used]             talk to us (D104); "used" after the free radar
//   #/app/<client>/<day>         Station, the edition (day may be "latest")
//   #/app/<client>/<day>/leads   Leads, with the case as a sheet
//   #/app/<client>/<day>/case/<rank>   the full case page
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
    if (path[3] === "case" && /^\d+$/.test(path[4] ?? ""))
      return <CasePage client={path[1]} day={path[2]} rank={Number(path[4])} />;
    return path[3] === "leads" ? (
      <LeadsPage client={path[1]} day={path[2]} />
    ) : (
      <StationPage client={path[1]} day={path[2]} />
    );
  }
  if ((path[0] === "c" || path[0] === "m") && path.length >= 3) {
    return <StationPage client={path[1]} day={path[2]} />;
  }

  if (path.length === 0 || path[0] === "intro") {
    return <LandingPage intro={path[0] === "intro"} />;
  }

  if (path[0] === "contact") {
    return <ContactPage reason={path[1]} />;
  }

  if (path[0] === "onboarding") {
    return <OnboardingPage />;
  }


  // In-page anchors in the locked landing design use plain hashes (#what, #trust, …).
  // Keep rendering the landing page for those anchors; only #/clients opens the old index.
  if (path[0] !== "clients") {
    return <LandingPage intro={false} />;
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
