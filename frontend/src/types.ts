// Shapes returned by northvaine/api (views.py, runs.py, feedback.py).

export interface ClientSummary {
  client_id: string;
  offer: string | null;
  latest: string | null;
  runs: string[];
  accounts: number;
  tenders: number;
}

export interface Row {
  rank: number;
  status: string;
  company: string;
  country: string;
  stream: string;
  what: string;
  requirement: "stated" | "inferred";
  requirement_ref: string | null;
  why_now: string;
  caution: string;
}

export interface BriefView {
  client_id: string;
  offer: string;
  as_of: string;
  accounts: Row[];
  tenders: Row[];
  weaker: Row[];
  thin: boolean;
  notes: string[];
}

export interface Claim {
  ref: string;
  statement: string;
  quote: string;
  url: string;
  source: string;
  is_value: boolean;
}

export interface Source {
  url: string;
  name: string;
  available: string;
  kinds: string[];
}

export interface Sentence {
  text: string;
  model_written: boolean;
}

export interface Bidder {
  name: string;
  country: string | null;
  wins: number;
  last_won: string | null;
  source_url: string;
  quote: string;
}

export interface Dossier {
  rank: number;
  company: string;
  country: string;
  stream: string;
  stream_note: string;
  status: string;
  caution: string;
  strength: string;
  who_roles: string[];
  what: string;
  when: string[];
  demand: Sentence;
  claims: Claim[];
  sources: Source[];
  requirement: string;
  requirement_ref: string | null;
  who_buys: string | null;
  direct_buyer: string;
  buyer_reason: Sentence;
  uncertain: Sentence[];
  stage_action: string | null;
  opening_question: string | null;
  suggestion: Sentence;
  rank_reasons: string[];
  likely_bidders: Bidder[];
  decision_line: string;
}

export const FAILURE_CHIPS = [
  "wrong company",
  "not a buyer",
  "competitor/publisher let through",
  "stale/closed window",
  "wrong fact",
  "not actionable",
] as const;

export const OUTCOMES = [
  "none",
  "redirect",
  "info request",
  "requirement",
  "sample",
  "quote",
  "meeting",
] as const;

export interface FeedbackRecord {
  client: string;
  as_of: string;
  rank: number;
  company: string;
  correct: boolean | null;
  relevant: boolean | null;
  new: boolean | null;
  actionable: boolean | null;
  failure_chip: string | null;
  known_already: boolean | null;
  new_intelligence: boolean | null;
  contacted: boolean | null;
  outcome: string | null;
  note: string;
  received_at: string;
}
