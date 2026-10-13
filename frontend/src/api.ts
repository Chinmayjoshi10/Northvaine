import type { BriefView, ClientSummary, Dossier, FeedbackRecord, Learning } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new Error(
      response.status === 404 ? "Not found." : `The server answered ${response.status}.`,
    );
  }
  return (await response.json()) as T;
}

const seg = encodeURIComponent;

export const api = {
  clients: () => request<ClientSummary[]>("/api/clients"),
  brief: (client: string, day: string) =>
    request<BriefView>(`/api/clients/${seg(client)}/runs/${seg(day)}`),
  entry: (client: string, day: string, rank: number) =>
    request<Dossier>(`/api/clients/${seg(client)}/runs/${seg(day)}/entries/${rank}`),
  feedback: (client: string, day: string) =>
    request<FeedbackRecord[]>(`/api/clients/${seg(client)}/feedback?as_of=${seg(day)}`),
  learning: (client: string) =>
    request<Learning>(`/api/clients/${seg(client)}/learning`),
  sendFeedback: (body: Omit<FeedbackRecord, "received_at">) =>
    request<FeedbackRecord>("/api/feedback", {
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
