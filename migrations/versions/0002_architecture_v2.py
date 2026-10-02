"""Architecture v2: the learning data model (docs/ARCHITECTURE.md section 21).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02

UPGRADE and DOWNGRADE are lists of single SQL statements, each run with
`op.execute(sa.text(s))` (asyncpg cannot run several commands in one prepared statement).
Because `sa.text` reads a colon followed by a word as a bind parameter, no statement
contains one. DOWNGRADE is the exact reverse of UPGRADE. Extensions are never dropped.
Vector columns are dimensionless until the embedding model is chosen; no vector indexes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEARNERS = "'world','org','buying','research','allocator'"
_STAGES = (
    "'candidate','gated','investigated','briefed','approved','contacted','replied',"
    "'meeting','samples','quoted','won','lost','dismissed'"
)
_SEED = (
    ("facility_opened", "A new site, plant, yard, branch or warehouse opened or announced"),
    ("contract_awarded", "A contract or tender award was made to the company"),
    ("tender_published", "The company published a tender or request for proposals"),
    ("hiring_surge", "A marked rise in open roles at the company"),
    ("leadership_change", "A senior leader joined, left or changed role"),
    ("product_launch", "The company launched or announced a product or service"),
    ("market_entry", "The company entered a new region or segment"),
    ("trade_measure", "A tariff, quota, duty or other trade rule changed"),
    ("website_change", "A material change to the company website"),
    ("reorder_due", "A past customer is due to reorder based on its history"),
    ("quote_stale", "A quote was sent and has had no reply for too long"),
    ("inbound_question", "A buyer or buyer agent asked a question through the Gateway"),
)
_SEED_VALUES = ", ".join(f"(0, '{label}', '{desc}')" for label, desc in _SEED)

UPGRADE: list[str] = [
    # --- event_concepts (world layer) and its level-0 seed ---
    """CREATE TABLE event_concepts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id uuid REFERENCES event_concepts(id) ON DELETE RESTRICT,
  level int NOT NULL CHECK (level >= 0),
  label text NOT NULL CHECK (label ~ '^[a-z][a-z0-9_]*$'),
  description text NOT NULL,
  embedding vector,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','proposed','merged','retired')),
  merged_into uuid REFERENCES event_concepts(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((level = 0) = (parent_id IS NULL)),
  UNIQUE NULLS NOT DISTINCT (parent_id, label)
)""",
    f"INSERT INTO event_concepts (level, label, description) VALUES {_SEED_VALUES}",
    # --- hypotheses (one registry for all learners) ---
    f"""CREATE TABLE hypotheses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  learner text NOT NULL CHECK (learner IN ({_LEARNERS})),
  kind text NOT NULL CHECK (kind ~ '^[a-z][a-z0-9_]*$'),
  parent_id uuid REFERENCES hypotheses(id),
  body jsonb NOT NULL,
  schema_ver text NOT NULL,
  status text NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed','exploring','exploiting','degraded','retired','rejected')),
  origin text NOT NULL CHECK (origin IN
    ('llm_prior','history_mining','world_lift','error_driven','missed_opportunity',
     'cross_org','owner')),
  proposed_at timestamptz NOT NULL DEFAULT now(),
  tests jsonb NOT NULL DEFAULT '[]',
  decided_at timestamptz,
  strategy_version int NOT NULL DEFAULT 0
)""",
    "CREATE INDEX hypotheses_lookup ON hypotheses (workspace_id, learner, kind, status)",
    # --- changes to v1 tables ---
    "ALTER TABLE documents ADD COLUMN available_at timestamptz",
    "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector",
    "ALTER TABLE theses ALTER COLUMN embedding TYPE vector",
    "ALTER TABLE theses DROP COLUMN alpha",
    "ALTER TABLE theses DROP COLUMN beta",
    "ALTER TABLE events ADD COLUMN concept_id uuid REFERENCES event_concepts(id)",
    "ALTER TABLE events ADD COLUMN slots jsonb NOT NULL DEFAULT '{}'",
    "CREATE INDEX events_concept ON events (concept_id)",
    "ALTER TABLE cases ADD COLUMN pattern_id uuid REFERENCES hypotheses(id)",
    f"ALTER TABLE cases ADD CONSTRAINT cases_stage_check CHECK (stage IN ({_STAGES}))",
    "CREATE UNIQUE INDEX cases_open_unique ON cases "
    "(workspace_id, company_id, pattern_id, window_start) NULLS NOT DISTINCT "
    "WHERE stage NOT IN ('won','lost','dismissed')",
    f"ALTER TABLE outcomes ADD CONSTRAINT outcomes_stage_check CHECK (stage IN ({_STAGES}))",
    "ALTER TABLE contacts ADD COLUMN workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE",
    "ALTER TABLE jobs ADD COLUMN created_at timestamptz NOT NULL DEFAULT now()",
    "ALTER TABLE jobs ADD COLUMN finished_at timestamptz",
    "ALTER TABLE jobs ADD COLUMN max_attempts int NOT NULL DEFAULT 5 CHECK (max_attempts >= 1)",
    "ALTER TABLE jobs ADD COLUMN locked_by text",
    "ALTER TABLE jobs ADD COLUMN workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE",
    "DROP INDEX jobs_ready",
    "CREATE INDEX jobs_claim ON jobs (run_after, id) WHERE status = 'queued'",
    "CREATE INDEX jobs_lease ON jobs (locked_at) WHERE status = 'running'",
    # --- patterns is a view over hypotheses ---
    "CREATE VIEW patterns AS SELECT id, workspace_id, learner, parent_id, body, schema_ver, "
    "status, origin, proposed_at, tests, decided_at, strategy_version "
    "FROM hypotheses WHERE kind = 'pattern'",
    # --- remaining new tables ---
    """CREATE TABLE playbooks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  hypothesis_id uuid REFERENCES hypotheses(id),
  thesis_id uuid REFERENCES theses(id),
  name text NOT NULL,
  spec jsonb NOT NULL,
  schema_ver text NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','exploring','retired')),
  pinned boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
)""",
    """CREATE TABLE search_programs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  source_hypothesis uuid REFERENCES hypotheses(id),
  name text NOT NULL,
  templates jsonb NOT NULL DEFAULT '[]',
  sources jsonb NOT NULL DEFAULT '[]',
  filters jsonb NOT NULL DEFAULT '{}',
  schedule jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'trial' CHECK (status IN ('active','trial','paused','retired')),
  yields jsonb NOT NULL DEFAULT '{}',
  schema_ver text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
)""",
    f"""CREATE TABLE expectations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  company_id uuid NOT NULL REFERENCES companies(id),
  concept_id uuid NOT NULL REFERENCES event_concepts(id),
  hypothesis_id uuid REFERENCES hypotheses(id),
  window_start date NOT NULL,
  window_end date NOT NULL,
  origin text NOT NULL CHECK (origin IN ({_LEARNERS})),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','met','missed')),
  value numeric,
  met_event_id uuid REFERENCES events(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  CHECK (window_end >= window_start)
)""",
    "CREATE INDEX expectations_open ON expectations (status, window_end)",
    f"""CREATE TABLE beliefs (
  id bigserial PRIMARY KEY,
  learner text NOT NULL CHECK (learner IN ({_LEARNERS})),
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  strategy_version int NOT NULL DEFAULT 0,
  kind text NOT NULL CHECK (kind ~ '^[a-z][a-z0-9_]*$'),
  key text NOT NULL,
  params jsonb NOT NULL,
  schema_ver text NOT NULL,
  n_evidence real NOT NULL DEFAULT 0 CHECK (n_evidence >= 0),
  prior_source text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (learner, workspace_id, strategy_version, kind, key)
)""",
    f"""CREATE TABLE belief_source_calibration (
  id bigserial PRIMARY KEY,
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  learner text NOT NULL CHECK (learner IN ({_LEARNERS})),
  prior_source text NOT NULL,
  bias real NOT NULL DEFAULT 0,
  spread real NOT NULL DEFAULT 1 CHECK (spread > 0),
  n_pairs int NOT NULL DEFAULT 0 CHECK (n_pairs >= 0),
  strategy_version int NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (workspace_id, learner, prior_source, strategy_version)
)""",
    """CREATE TABLE policy_params (
  id bigserial PRIMARY KEY,
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_.]*$'),
  default_value jsonb NOT NULL,
  current_value jsonb NOT NULL,
  update_rule text NOT NULL,
  metric text NOT NULL,
  strategy_version int NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (workspace_id, name)
)""",
    """CREATE TABLE decisions (
  id bigserial PRIMARY KEY,
  workspace_id uuid REFERENCES workspaces(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('brief','search','investigation','question')),
  case_id uuid REFERENCES cases(id) ON DELETE SET NULL,
  company_id uuid REFERENCES companies(id),
  features jsonb NOT NULL,
  choice jsonb NOT NULL,
  value_estimate real,
  propensity real NOT NULL CHECK (propensity > 0 AND propensity <= 1),
  cost_usd numeric(10,6) NOT NULL DEFAULT 0,
  strategy_version int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
)""",
    "CREATE INDEX decisions_log ON decisions (workspace_id, kind, created_at)",
    f"""CREATE TABLE failure_attributions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  feedback_id uuid NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
  code text NOT NULL CHECK (code ~ '^[a-z][a-z0-9_]*$'),
  learner text NOT NULL CHECK (learner IN ({_LEARNERS})),
  component text NOT NULL,
  target_id text,
  weight real NOT NULL DEFAULT 1 CHECK (weight > 0 AND weight <= 1),
  confirmed boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
)""",
    """CREATE TABLE missed_opportunities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  source text NOT NULL CHECK (source IN ('inbound','win','public_award')),
  company_id uuid REFERENCES companies(id),
  case_id uuid REFERENCES cases(id) ON DELETE SET NULL,
  occurred_on date NOT NULL,
  evidence_claim_id uuid REFERENCES claims(id),
  postmortem_status text NOT NULL DEFAULT 'pending' CHECK (postmortem_status IN
    ('pending','not_surfaced','surfaced_dropped','surfaced_late','surfaced_in_time')),
  postmortem jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  analyzed_at timestamptz
)""",
    """CREATE TABLE controls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  hypothesis_id uuid REFERENCES hypotheses(id) ON DELETE CASCADE,
  positive_company_id uuid NOT NULL REFERENCES companies(id),
  control_company_id uuid NOT NULL REFERENCES companies(id),
  as_of date NOT NULL,
  match_on jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (positive_company_id <> control_company_id),
  UNIQUE NULLS NOT DISTINCT
    (workspace_id, hypothesis_id, positive_company_id, control_company_id, as_of)
)""",
    f"""CREATE TABLE lessons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  strategy_version int NOT NULL,
  learner text NOT NULL CHECK (learner IN ({_LEARNERS})),
  body text NOT NULL,
  belief_change jsonb NOT NULL,
  behaviour_change jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (workspace_id, strategy_version)
    REFERENCES strategy_versions(workspace_id, version)
)""",
    """CREATE TABLE inbound_queries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  channel text NOT NULL,
  counterpart text NOT NULL CHECK (counterpart IN ('human','agent')),
  agent_domain text,
  query text NOT NULL,
  answered boolean NOT NULL DEFAULT false,
  case_id uuid REFERENCES cases(id) ON DELETE SET NULL,
  cluster_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
)""",
    f"""CREATE TABLE case_open_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  question text NOT NULL,
  source_learner text NOT NULL CHECK (source_learner IN ({_LEARNERS})),
  hypothesis_id uuid REFERENCES hypotheses(id),
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','answered','dropped')),
  answer_claim_id uuid REFERENCES claims(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
)""",
]

DOWNGRADE: list[str] = [
    "DROP TABLE case_open_questions",
    "DROP TABLE inbound_queries",
    "DROP TABLE lessons",
    "DROP TABLE controls",
    "DROP TABLE missed_opportunities",
    "DROP TABLE failure_attributions",
    "DROP INDEX decisions_log",
    "DROP TABLE decisions",
    "DROP TABLE policy_params",
    "DROP TABLE belief_source_calibration",
    "DROP TABLE beliefs",
    "DROP INDEX expectations_open",
    "DROP TABLE expectations",
    "DROP TABLE search_programs",
    "DROP TABLE playbooks",
    "DROP VIEW patterns",
    "DROP INDEX jobs_lease",
    "DROP INDEX jobs_claim",
    "CREATE INDEX jobs_ready ON jobs (status, run_after)",
    "ALTER TABLE jobs DROP COLUMN workspace_id",
    "ALTER TABLE jobs DROP COLUMN locked_by",
    "ALTER TABLE jobs DROP COLUMN max_attempts",
    "ALTER TABLE jobs DROP COLUMN finished_at",
    "ALTER TABLE jobs DROP COLUMN created_at",
    "ALTER TABLE contacts DROP COLUMN workspace_id",
    "ALTER TABLE outcomes DROP CONSTRAINT outcomes_stage_check",
    "DROP INDEX cases_open_unique",
    "ALTER TABLE cases DROP CONSTRAINT cases_stage_check",
    "ALTER TABLE cases DROP COLUMN pattern_id",
    "DROP INDEX events_concept",
    "ALTER TABLE events DROP COLUMN slots",
    "ALTER TABLE events DROP COLUMN concept_id",
    "ALTER TABLE theses ADD COLUMN beta real NOT NULL DEFAULT 1",
    "ALTER TABLE theses ADD COLUMN alpha real NOT NULL DEFAULT 1",
    "ALTER TABLE theses ALTER COLUMN embedding TYPE vector(1024)",
    "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024)",
    "ALTER TABLE documents DROP COLUMN available_at",
    "DROP INDEX hypotheses_lookup",
    "DROP TABLE hypotheses",
    "DROP TABLE event_concepts",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(sa.text(statement))
