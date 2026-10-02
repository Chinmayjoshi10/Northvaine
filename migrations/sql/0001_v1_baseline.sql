-- Northvaine canonical schema (Postgres 16 + pgvector)
-- Two layers:
--   WORLD   = public facts about companies, shared and reusable (companies, documents, claims, events)
--   PRIVATE = everything belonging to one client workspace (profile, theses, cases, outcomes)
-- Rules: every fact traces to a document; generated JSON is validated by a versioned Pydantic schema;
-- nothing industry-specific lives in this file.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============ TENANCY ============
CREATE TABLE workspaces (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  primary_domain text,                       -- the client's own website
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email      text UNIQUE NOT NULL,
  name       text
);

CREATE TABLE memberships (
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id      uuid REFERENCES users(id) ON DELETE CASCADE,
  role         text NOT NULL CHECK (role IN ('owner','manager','rep','ops')),
  territory    jsonb,                        -- e.g. {"countries":["DE","NL"],"products":["SP-630"]}
  PRIMARY KEY (workspace_id, user_id)
);

-- ============ WORLD LAYER (shared, public facts) ============
CREATE TABLE companies (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  primary_domain text UNIQUE,                -- canonical key for entity resolution
  name           text NOT NULL,
  aliases        text[] NOT NULL DEFAULT '{}',
  country        char(2),                    -- ISO 3166-1 alpha-2
  locality       text,
  industry_codes text[] NOT NULL DEFAULT '{}', -- e.g. 'isic:4663', 'naics:423320'
  attributes     jsonb NOT NULL DEFAULT '{}',  -- size band, type (distributor, contractor...)
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sources (
  id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name   text NOT NULL,                      -- 'tavily', 'ted', 'website', 'order_history'
  tier   text NOT NULL CHECK (tier IN ('official','company','reported','social','private','paid')),
  trust  real NOT NULL DEFAULT 0.5           -- learned over time
);

CREATE TABLE documents (                     -- every fetched page or record, snapshotted
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id     uuid REFERENCES sources(id),
  url           text NOT NULL,
  content_hash  text NOT NULL,               -- unchanged page = no new work
  title         text,
  text          text NOT NULL,               -- extracted plain text used for quote checks
  published_on  date,
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  workspace_id  uuid REFERENCES workspaces(id), -- NULL = public; set = private (e.g. order CSV)
  UNIQUE (url, content_hash)
);

CREATE TABLE document_chunks (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid REFERENCES documents(id) ON DELETE CASCADE,
  text        text NOT NULL,
  embedding   vector(1024)                   -- set to the Nemotron Embed dimension you use
);

CREATE TABLE claims (                        -- the evidence ledger: one verified fact each
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid REFERENCES companies(id),
  document_id   uuid NOT NULL REFERENCES documents(id),
  statement     text NOT NULL,               -- "Opened a second yard in Katy, Texas"
  source_quote  text NOT NULL,               -- exact sentence from documents.text
  quote_offset  int,                         -- where it was found (set by the code check)
  verified      boolean NOT NULL DEFAULT false,
  verified_by   text,                        -- 'code', 'code+llm'
  extracted_by  text NOT NULL,               -- model id that proposed it
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE events (                        -- something that CHANGED, in generic vocabulary
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id   uuid REFERENCES companies(id),
  event_type   text NOT NULL,                -- 'facility_opened','contract_awarded','hiring_surge',
                                             -- 'trade_measure','leadership_change','website_change',
                                             -- 'product_launch','reorder_due', ...
  occurred_on  date,
  details      jsonb NOT NULL DEFAULT '{}',  -- e.g. {"cpv":["44911000"],"value_eur":2100000}
  cluster_id   uuid,                         -- same story from many sites = one cluster
  claim_ids    uuid[] NOT NULL,              -- an event without verified claims is not stored
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- ============ PRIVATE LAYER (per client workspace) ============
CREATE TABLE business_profiles (             -- the "genome", versioned
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  version      int NOT NULL,
  schema_ver   text NOT NULL,                -- Pydantic model version that validated it
  profile      jsonb NOT NULL,               -- offer, regions, MOQ, anti-customers, capacity
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, version)
);

CREATE TABLE products (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  sku          text,
  name         text NOT NULL,
  hs_code      text,                         -- Harmonized System code where known
  attributes   jsonb NOT NULL DEFAULT '{}',  -- sizes, finishes, certifications
  public       boolean NOT NULL DEFAULT true -- shown on the Gateway profile
);

CREATE TABLE workspace_companies (           -- this client's relationship to a world company
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  company_id   uuid REFERENCES companies(id),
  relation     text NOT NULL CHECK (relation IN ('customer','best_customer','prospect','competitor','suppressed')),
  owner_user   uuid REFERENCES users(id),    -- contact lock: one person per company
  PRIMARY KEY (workspace_id, company_id)
);

CREATE TABLE theses (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  name         text NOT NULL,
  spec         jsonb NOT NULL,               -- trigger, follow_up_signals, disqualifiers,
                                             -- buyer_roles, window_days, event_types, queries
  origin       text NOT NULL CHECK (origin IN ('generated','user','discovered')),
  pinned       boolean NOT NULL DEFAULT false,
  alpha        real NOT NULL DEFAULT 1,      -- weighted successes (Beta distribution)
  beta         real NOT NULL DEFAULT 1,      -- weighted failures
  status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active','exploring','retired')),
  embedding    vector(1024),
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cases (                         -- one opportunity, inbound or outbound
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  company_id   uuid REFERENCES companies(id),
  direction    text NOT NULL CHECK (direction IN ('outbound','inbound')),
  thesis_id    uuid REFERENCES theses(id),
  stage        text NOT NULL DEFAULT 'candidate',
               -- candidate → gated → investigated → briefed → approved → contacted
               -- → replied → meeting → samples → quoted → won | lost | dismissed
  verdict      jsonb,                        -- strength, confidence, why_now, angle, first_offer
  window_start date,
  window_end   date,
  assigned_to  uuid REFERENCES users(id),
  trace        jsonb NOT NULL DEFAULT '[]',  -- every stage it passed or failed, with reason
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE case_evidence (
  case_id  uuid REFERENCES cases(id) ON DELETE CASCADE,
  claim_id uuid REFERENCES claims(id),
  stance   text NOT NULL CHECK (stance IN ('for','against','unknown')),
  PRIMARY KEY (case_id, claim_id)
);

CREATE TABLE contacts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id  uuid REFERENCES companies(id),
  role        text NOT NULL,                 -- 'procurement', 'owner', ...
  name        text,
  email       text,
  claim_id    uuid REFERENCES claims(id),    -- where we learned it
  verified    boolean NOT NULL DEFAULT false
);

CREATE TABLE messages (                      -- drafts, outreach, replies, Gateway chat
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id        uuid REFERENCES cases(id) ON DELETE CASCADE,
  direction      text NOT NULL CHECK (direction IN ('out','in')),
  channel        text NOT NULL,              -- 'email','chat','agent_mcp'
  counterpart    text NOT NULL CHECK (counterpart IN ('human','agent')),
  agent_domain   text,                       -- verified domain of a buyer's agent
  subject        text,
  body           text NOT NULL,
  status         text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','sent','received')),
  approved_by    uuid REFERENCES users(id),
  classification text,                       -- for replies: interested, question, not_now, no
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quote_requests (                -- structured intake from the Gateway receptionist
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id      uuid REFERENCES cases(id) ON DELETE CASCADE,
  items        jsonb NOT NULL,               -- [{product_id, quantity, unit}]
  destination  text,                         -- UN/LOCODE port where possible, e.g. 'USHOU'
  needed_by    date,
  notes        text,
  reply_due_at timestamptz,
  answered_at  timestamptz                   -- always answered by a person
);

CREATE TABLE feedback (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id   uuid REFERENCES cases(id) ON DELETE CASCADE,
  user_id   uuid REFERENCES users(id),
  rating    text NOT NULL CHECK (rating IN ('good','not_relevant','wrong_facts','later')),
  reason    text,                            -- 'too_small','wrong_region','already_customer',...
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE outcomes (                      -- the furthest stage reached, with value
  case_id    uuid PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
  stage      text NOT NULL,
  value      numeric,
  currency   char(3),                        -- ISO 4217
  recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE strategy_versions (             -- every nightly learning change, reversible
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  version      int NOT NULL,
  snapshot     jsonb NOT NULL,               -- thesis weights, rules, source trust at that time
  changes      jsonb NOT NULL,               -- plain-language "what I learned"
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, version)
);

CREATE TABLE questions (                     -- the assistant's "keep asking" queue
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  question     text NOT NULL,
  reason       text NOT NULL,                -- which gap or pattern triggered it
  status       text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','asked','answered','skipped')),
  answer       text,
  asked_at     timestamptz
);

-- ============ OPERATIONS ============
CREATE TABLE jobs (                          -- Postgres-backed queue
  id          bigserial PRIMARY KEY,
  kind        text NOT NULL,                 -- 'discover','filter','gate','investigate','verify','judge'
  payload     jsonb NOT NULL,
  status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
  attempts    int NOT NULL DEFAULT 0,
  run_after   timestamptz NOT NULL DEFAULT now(),
  locked_at   timestamptz,
  error       text
);
CREATE INDEX jobs_ready ON jobs (status, run_after);

CREATE TABLE llm_calls (                     -- cost and audit of every model call
  id           bigserial PRIMARY KEY,
  workspace_id uuid,
  case_id      uuid,
  model        text NOT NULL,
  purpose      text NOT NULL,
  input_tokens int, output_tokens int,
  cost_usd     numeric(10,6),
  ok           boolean,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (                     -- append-only: who did what, when
  id           bigserial PRIMARY KEY,
  workspace_id uuid,
  actor        text NOT NULL,                -- user id or 'system:<component>'
  action       text NOT NULL,
  target       text,
  details      jsonb,
  created_at   timestamptz NOT NULL DEFAULT now()
);
