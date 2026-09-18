-- Case Closed schema. Apply with: npx @insforge/cli db import db/001_schema.sql
-- The gateway writes with the admin key. The browser only reads (anon SELECT).

CREATE TABLE IF NOT EXISTS cases (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status       text NOT NULL DEFAULT 'open',  -- open | proposed | filed | declined | emergency | ended
  case_type    text,                          -- a key from routing.yaml
  confidence   real,
  language     text,
  location     text,
  consent      boolean,
  emergency    boolean NOT NULL DEFAULT false,
  summary      text,
  proposed_at  timestamptz,
  approved_at  timestamptz,
  is_eval      boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS case_fields (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id    uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  field      text NOT NULL,
  value      text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (case_id, field)
);

CREATE TABLE IF NOT EXISTS transcript_turns (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id       uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  item_id       text NOT NULL,               -- Higgs conversation item; caller turns grow, so upsert on it
  speaker       text NOT NULL,               -- patrick | caller
  original_text text NOT NULL,
  english_text  text,
  language      text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (case_id, item_id)
);

CREATE TABLE IF NOT EXISTS inconsistencies (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id     uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  description text NOT NULL,
  status      text NOT NULL DEFAULT 'open',  -- open | resolved
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tool_events (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id    uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  name       text NOT NULL,
  args       jsonb,
  result     jsonb,
  status     text NOT NULL DEFAULT 'done',   -- running | done | error
  source     text NOT NULL DEFAULT 'patrick',   -- patrick (voice model) | backup (gateway scribe)
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS authority_searches (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id      uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  query        text NOT NULL,
  status       text NOT NULL DEFAULT 'running', -- running | done | failed
  result_count int,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS authorities (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id    uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  role       text NOT NULL,                  -- destination key from routing.yaml
  rank       int,
  name       text NOT NULL,
  handles    text,
  reason     text,
  email      text,
  form_url   text,
  phone      text,
  source_url text,
  is_cached  boolean NOT NULL DEFAULT false,
  approval   text NOT NULL DEFAULT 'pending', -- pending | approved | removed
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dispatches (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id            uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  authority_id       uuid REFERENCES authorities(id) ON DELETE SET NULL,
  kind               text NOT NULL,          -- authority | caller
  intended_name      text,
  intended_recipient text,                   -- the real address or form; never mailed in safe mode
  delivered_to       text,
  status             text NOT NULL DEFAULT 'drafting', -- drafting | sent | delivered | blocked | failed
  source_url         text,
  form_url           text,
  reference          text,
  subject            text,
  body_html          text,
  report_url         text,
  error              text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mock_accounts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  holder_name  text NOT NULL,
  bank_name    text NOT NULL,
  account_hint text NOT NULL                 -- last four digits only
);

CREATE TABLE IF NOT EXISTS mock_transactions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id   uuid NOT NULL REFERENCES mock_accounts(id) ON DELETE CASCADE,
  posted_at    timestamptz NOT NULL,
  amount       numeric NOT NULL,
  currency     text NOT NULL,
  direction    text NOT NULL,                -- debit | credit
  counterparty text,
  reference    text,
  description  text
);

CREATE TABLE IF NOT EXISTS eval_runs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  total       int,
  passed      int,
  score       real,
  notes       text
);

CREATE TABLE IF NOT EXISTS eval_results (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id           uuid NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
  caller_id        text NOT NULL,
  language         text,
  scenario         text,
  case_type_ok     boolean,
  fields_ok        boolean,
  inconsistency_ok boolean,
  routing_ok       boolean,
  score            real,
  details          jsonb
);

-- The case board reads with the anon key. Bank data stays gateway only.
GRANT USAGE ON SCHEMA public TO anon;
GRANT SELECT ON cases, case_fields, transcript_turns, inconsistencies, tool_events,
  authority_searches, authorities, dispatches, eval_runs, eval_results TO anon;
