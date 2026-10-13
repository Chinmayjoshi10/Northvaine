import type { Link, Row } from "../types";

// How a lead reads in the app. All of it is derived from the run record; nothing is invented.

export const SLOT: Record<Link["slot"], string> = {
  authority: "Authority",
  project: "Project",
  contract: "Contract",
  contractor: "Contractor",
  buyer: "Buys what you sell",
};

const KEEP_UPPER = new Set([
  "SAS",
  "SA",
  "SARL",
  "SEDIF",
  "GMBH",
  "KG",
  "AG",
  "LBM",
  "TU",
  "SNC",
  "EG",
]);

// Particles stay lower case inside a name ("Compagnie de Diffusion", "Stadt und Land").
const PARTICLES = new Set([
  "de",
  "du",
  "des",
  "la",
  "le",
  "les",
  "et",
  "d",
  "l",
  "und",
  "der",
  "die",
  "das",
  "von",
  "van",
  "of",
  "the",
  "and",
]);

/** All-caps registry names read better in title case; short forms and acronyms stay as they are. */
export function nice(name: string): string {
  if (name !== name.toUpperCase()) return name;
  return name
    .split(/(\s+|-)/)
    .map((w, i) => {
      if (KEEP_UPPER.has(w.toUpperCase())) return w;
      const lower = w.toLowerCase();
      if (i > 0 && PARTICLES.has(lower)) return lower;
      // "D'AUBAGNE" -> "d'Aubagne"
      return lower
        .replace(
          /(^|['’])(\p{L})/gu,
          (_m, q: string, c: string) => q + c.toUpperCase(),
        )
        .replace(/^([DL])(['’])/u, (_m, a: string, q: string) =>
          (i > 0 ? a.toLowerCase() : a) + q,
        );
    })
    .join("");
}

/** "France – Supplies of equipment – Fourniture…" → "Supplies of equipment – Fourniture…": the country is shown elsewhere. */
export function stripCountry(text: string): string {
  return text.replace(/^[A-Z][\p{L}]+(?: [A-Z][\p{L}]+)? – /u, "");
}

export function typeOf(r: Row): string {
  if (r.stream === "tender") return "Tender";
  if (r.stream === "award") return "Award";
  if (r.stream === "announcement") return "Project";
  return r.stream.charAt(0).toUpperCase() + r.stream.slice(1);
}

export function stageOf(r: Row): string {
  if (r.status === "contact now" || r.status === "bid now") return "Act now";
  if (r.status === "qualify first") return "Developing";
  if (r.status === "watch only") return "Watching";
  return "Detected";
}

export function roleOf(r: Row): string {
  const role = r.account_role ?? "";
  if (role === "demand_source" || role === "direct_purchaser")
    return "authority";
  if (role === "awarded_contractor") return "contractor";
  return role.replace(/_/g, " ");
}

/** The window, worded for a list: "awarded 6 Oct", "closes in 7 days". */
export function windowOf(r: Row): string {
  const m = r.why_now.match(/award published (\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return (
      "awarded " +
      d.toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        timeZone: "UTC",
      })
    );
  }
  return r.why_now.replace(/^tender /, "");
}

export function isHot(r: Row): boolean {
  return stageOf(r) === "Act now" || /closes in [0-9] days?/.test(r.why_now);
}

/** The headline is assembled from the chain's stated fields only (D98). */
export function headline(r: Row, maxProject = Infinity): string {
  const chain = r.chain ?? [];
  const auth = chain.find(
    (l) => l.slot === "authority" && l.state === "stated",
  );
  const proj = chain.find((l) => l.slot === "project" && l.state === "stated");
  const full = proj
    ? stripCountry(proj.label).split(" – ").slice(-1)[0]
    : stripCountry(r.what);
  // cut at a word, never mid-name
  const project =
    full.length <= maxProject
      ? full
      : `${full.slice(0, maxProject).replace(/\s+\S*$/, "")}…`;
  const who = nice(r.company);
  if (r.stream === "award" && auth)
    return `${nice(auth.label)} awards ${project} to ${who}`;
  if (r.stream === "tender") return `${who} opens a tender: ${project}`;
  return who;
}

export function domain(url: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function longDate(day: string): { weekday: string; date: string } {
  const d = new Date(`${day}T06:00:00Z`);
  return {
    weekday: d.toLocaleDateString("en-GB", {
      weekday: "long",
      timeZone: "UTC",
    }),
    date: d.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    }),
  };
}

/** The project's own name, from the chain when it is on record, else from the lead. */
export function projectOf(r: Row): string {
  const proj = (r.chain ?? []).find(
    (l) => l.slot === "project" && l.state === "stated",
  );
  return stripCountry(proj ? proj.label : r.what)
    .split(" – ")
    .slice(-1)[0];
}

/** Days until a tender closes, or null when it is not a tender with a stated deadline. */
export function daysLeft(r: Row): number | null {
  const m = r.why_now.match(/closes in (\d+) days?/);
  if (!m || /too late/.test(r.why_now)) return null;
  return Number(m[1]);
}

/** The award's date ("2026-10-06"), when the lead is an award. */
export function awardDay(r: Row): string | null {
  const m = r.why_now.match(/award(?:ed| published) (\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : null;
}

/** The chain steps not yet known, worded for a sentence. */
export function unknownSteps(r: Row): string[] {
  return (r.chain ?? [])
    .filter((l) => l.state === "unknown")
    .map((l) => (l.slot === "buyer" ? "who buys" : SLOT[l.slot].toLowerCase()));
}

export function shortDate(day: string): string {
  return new Date(`${day.slice(0, 10)}T12:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
