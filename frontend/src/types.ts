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
  /** D103: act_now | just_changed | account_to_work, and the fact behind it */
  label?: string | null;
  label_reason?: string | null;
  /** also briefed in the client's previous run */
  returning?: boolean;
  status: string;
  company: string;
  country: string;
  stream: string;
  what: string;
  requirement: "stated" | "inferred";
  requirement_ref: string | null;
  why_now: string;
  caution: string;
  account_role?: string | null;
  evidence_level?: string | null;
  contract_nature?: string | null;
  company_key?: string;
  chain?: Link[];
}

/** One step of the commercial chain, as known: stated (a verified quote), inferred, unknown. */
export interface Link {
  // a trade record (D102) uses importer, product, history and buyer
  slot:
    | "authority"
    | "project"
    | "contract"
    | "contractor"
    | "buyer"
    | "importer"
    | "product"
    | "history";
  label: string;
  state: "stated" | "inferred" | "unknown";
  quote: string | null;
  url: string | null;
}

export interface Funnel {
  documents: number;
  candidates: number;
  rejected: Record<string, number>;
  briefed: number;
}

export interface BriefView {
  client_id: string;
  offer: string;
  /** the client's company name, when onboarding gave one */
  client_name?: string | null;
  /** the previous run's date; null on a client's first run */
  previous?: string | null;
  as_of: string;
  accounts: Row[];
  tenders: Row[];
  weaker: Row[];
  thin: boolean;
  notes: string[];
  funnel?: Funnel | null;
  log?: LogItem[];
  /** D103: today's few checked targets; empty on a thin day */
  edition?: Row[];
}

/** One thing the run saw, newest first: when its source made it public, what, and about whom. */
export interface LogItem {
  at: string | null;
  kind: string;
  text: string;
  company: string | null;
  rank: number | null;
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
  company_site: string | null;
  company_contact: { email: string | null; phone: string | null; url: string } | null;
  like_customers: string[];
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
  accepted_for_contact?: boolean | null;
  known_already: boolean | null;
  new_intelligence: boolean | null;
  contacted: boolean | null;
  outcome: string | null;
  note: string;
  received_at: string;
}

/** One answer and what it taught (D100), worded by the server from the real change. */
export interface Lesson {
  as_of: string;
  rank: number;
  company: string;
  said: string;
  teaches: string | null;
  change: string;
  received_at: string;
}

export interface Learning {
  answers: number;
  labels: number;
  needed: number;
  active: boolean;
  lessons: Lesson[];
}

/** D104: a "talk to us" request; a person answers it. `website_url` is a hidden bot trap. */
export interface ContactIn {
  kind: "subscribe" | "contact";
  name: string;
  company: string;
  email: string;
  website: string;
  message: string;
  website_url: string;
}

/** D105: onboarding. The proposal is checked by code; the person edits every field. */
export interface Proposal {
  offer: string;
  offer_terms: string[];
  related_terms: string[];
  markets: string[];
  buyer_roles: string[];
  not_buyers: string[];
  hs_codes: string[];
  cpv_codes: string[];
  search_phrases: string[];
  dropped: string[];
}

export interface OnboardingSession {
  id: string;
  company: string;
  website: string;
  stage: "reading" | "ready" | "proposing" | "proposed" | "running" | "done" | "failed";
  site_read: boolean;
  catalogue: { pages: number; readable: boolean } | null;
  proposal: Proposal | null;
  client_id: string | null;
  error: string | null;
  notes: string[];
}

export interface OnboardingAnswers {
  company: string;
  website: string;
  offer: string;
  offer_terms: string[];
  related_terms: string[];
  markets: string[];
  buyer_roles: string[];
  not_buyers: string[];
  hs_codes: string[];
  cpv_codes: string[];
  search_phrases: string[];
  existing_customers: string[];
}

/** Your business: what the radar was told about the client (read-only). */
export interface BusinessView {
  client_id: string;
  name: string | null;
  offer: string;
  markets: string[];
  offer_terms: string[];
  related_terms: string[];
  buyer_roles: string[];
  not_buyers: string[];
  product_codes: string[];
  /** how many current customers are left out; their names are never sent to the page */
  existing_customers: number;
  searches: { source: string; count: number }[];
}
