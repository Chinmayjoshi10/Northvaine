import type {
  BriefView,
  ClientSummary,
  ContactIn,
  Dossier,
  OnboardingAnswers,
  OnboardingSession,
  FeedbackRecord,
  Learning, BusinessView } from "./types";

// Static demo (GitHub Pages): demo GETs read exported JSON; live calls go to the API host.
// Both switches are build-time; with them unset everything is same-origin as before.
export const STATIC_DATA = import.meta.env.VITE_STATIC_DATA === "1";
const LIVE_API: string = STATIC_DATA
  ? ((import.meta.env.VITE_LIVE_API as string | undefined) ?? "").replace(/\/$/, "")
  : "";

/** Where a live call goes: the API host in static mode, same-origin otherwise. */
export const liveUrl = (path: string) => LIVE_API + path;

/** `/api/clients/c/feedback?as_of=D` -> `<base>data/api/clients/c/feedback/D.json`.
 * Keep in step with `static_file` in scripts/export_static.py. */
export function staticPath(path: string): string {
  const [route, query = ""] = path.split("?");
  const day = query.startsWith("as_of=") ? "/" + query.slice("as_of=".length) : "";
  return `${import.meta.env.BASE_URL}data${route}${day}.json`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(liveUrl(path), init);
  return read<T>(response);
}

/** A demo GET. In static mode the exported file answers; anything not exported (a client built
 * after the last nightly run) falls back to the live API. */
async function load<T>(path: string): Promise<T> {
  if (!STATIC_DATA) return request<T>(path);
  const exported = await fetch(staticPath(path)).catch(() => null);
  if (exported?.ok) return read<T>(exported);
  return request<T>(path);
}

/** Free hosting sleeps when idle: resolves once the live API answers (or after `giveUpMs`). */
export async function wakeLiveApi(giveUpMs = 180_000): Promise<void> {
  if (!STATIC_DATA) return;
  const until = Date.now() + giveUpMs;
  while (Date.now() < until) {
    const r = await fetch(liveUrl("/health")).catch(() => null);
    if (r?.ok) return;
    await new Promise((done) => setTimeout(done, 3000));
  }
}

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(
      response.status === 404 ? "Not found." : `The server answered ${response.status}.`,
    );
  }
  return (await response.json()) as T;
}

const seg = encodeURIComponent;

export const api = {
  clients: () => load<ClientSummary[]>("/api/clients"),
  business: (client: string) =>
    load<BusinessView>(`/api/clients/${seg(client)}/business`),
  brief: (client: string, day: string) =>
    load<BriefView>(`/api/clients/${seg(client)}/runs/${seg(day)}`),
  entry: (client: string, day: string, rank: number) =>
    load<Dossier>(`/api/clients/${seg(client)}/runs/${seg(day)}/entries/${rank}`),
  feedback: (client: string, day: string) =>
    load<FeedbackRecord[]>(`/api/clients/${seg(client)}/feedback?as_of=${seg(day)}`),
  learning: (client: string) =>
    load<Learning>(`/api/clients/${seg(client)}/learning`),
  sendFeedback: (body: Omit<FeedbackRecord, "received_at">) =>
    request<FeedbackRecord>("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  onboardingStart: (body: { email: string; company: string; website: string }) =>
    fetch(liveUrl("/api/onboarding"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  onboarding: (id: string) => request<OnboardingSession>(`/api/onboarding/${seg(id)}`),
  onboardingCatalogue: (id: string, file: File) =>
    request<{ pages: number; readable: boolean }>(`/api/onboarding/${seg(id)}/catalogue`, {
      method: "POST",
      headers: { "Content-Type": "application/pdf" },
      body: file,
    }),
  onboardingPropose: (id: string) =>
    request<OnboardingSession>(`/api/onboarding/${seg(id)}/propose`, { method: "POST" }),
  onboardingAnswers: (id: string, body: OnboardingAnswers) =>
    request<OnboardingSession>(`/api/onboarding/${seg(id)}/answers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  contact: (body: ContactIn) =>
    request<{ received: boolean }>("/api/contact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

/** Only http(s) links are made clickable; source URLs are external content. */
export function safeHref(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}
