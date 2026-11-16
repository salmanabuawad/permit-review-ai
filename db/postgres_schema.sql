-- Production schema (PostgreSQL 16 + PostGIS 3 + pgvector). The POC runs the operational
-- subset on SQLite via SQLAlchemy (backend/app/models.py); this DDL is the target ERD.
-- Tenant isolation: every municipal table has tenant_id + Row Level Security.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE municipalities (id text PRIMARY KEY, name_he text NOT NULL, is_demo boolean NOT NULL DEFAULT false,
  settings jsonb NOT NULL DEFAULT '{}');
CREATE TABLE users (id text PRIMARY KEY, tenant_id text NOT NULL REFERENCES municipalities, display_name text NOT NULL,
  role text NOT NULL, idp_subject text UNIQUE, mfa_enrolled boolean NOT NULL DEFAULT false);

-- knowledge base ------------------------------------------------------------------------
CREATE TABLE documents (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id text REFERENCES municipalities,
  category text NOT NULL, title_he text NOT NULL, url text, verification text NOT NULL, notes text);
CREATE TABLE document_versions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_id uuid NOT NULL REFERENCES documents,
  edition text, published_on date, sha256 char(64) NOT NULL, storage_uri text NOT NULL, page_count int,
  lifecycle text NOT NULL DEFAULT 'ACTIVE' CHECK (lifecycle IN ('ACTIVE','ARCHIVED','DELETED')),
  retrieved_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE source_spans (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_version_id uuid NOT NULL REFERENCES document_versions,
  page int, section text, bbox box, text_he text, is_quote boolean NOT NULL DEFAULT false,
  embedding vector(768), tsv tsvector);
CREATE INDEX ON source_spans USING gin (tsv);
CREATE INDEX ON source_spans USING hnsw (embedding vector_cosine_ops);

CREATE TABLE plans (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id text NOT NULL REFERENCES municipalities,
  plan_number text NOT NULL, aliases text[] NOT NULL DEFAULT '{}', name_he text, authority text,
  status text, approved_on date, published_on date, UNIQUE (tenant_id, plan_number));
CREATE TABLE plan_versions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), plan_id uuid NOT NULL REFERENCES plans,
  valid_from date, valid_to date, geom geometry(MultiPolygon, 2039),  -- Israel TM Grid (ITM)
  reviewed_by text REFERENCES users, approval_status text NOT NULL DEFAULT 'UNVERIFIED');
CREATE TABLE plan_relations (from_plan uuid REFERENCES plans, to_plan uuid REFERENCES plans,
  relation text NOT NULL CHECK (relation IN ('AMENDS','REPLACES','SUBJECT_TO','CANCELS')), PRIMARY KEY (from_plan, to_plan, relation));
CREATE TABLE regulations (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id text REFERENCES municipalities,
  legal_level text NOT NULL, document_id uuid REFERENCES documents, title_he text NOT NULL);
CREATE TABLE regulation_sections (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), regulation_id uuid REFERENCES regulations,
  plan_version_id uuid REFERENCES plan_versions, section text NOT NULL, exact_text_he text, source_span_id uuid REFERENCES source_spans);
CREATE TABLE parcels (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id text NOT NULL REFERENCES municipalities,
  gush text NOT NULL, helka text NOT NULL, zone text, geom geometry(MultiPolygon, 2039), UNIQUE (tenant_id, gush, helka));
CREATE INDEX ON parcels USING gist (geom);

-- rules ---------------------------------------------------------------------------------
CREATE TABLE rules (id text NOT NULL, tenant_id text NOT NULL REFERENCES municipalities, PRIMARY KEY (tenant_id, id));
CREATE TABLE rule_versions (tenant_id text NOT NULL, rule_id text NOT NULL, version text NOT NULL,
  title_he text NOT NULL, legal_level text NOT NULL, jurisdiction text NOT NULL,
  exact_clause_he text, valid_from date, valid_to date, spatial_scope jsonb, permit_types text[], stages text[],
  prerequisites jsonb, check_spec jsonb NOT NULL,   -- kind, operand, operator, threshold(_by), units, geometry_method, tolerance
  evidence_required text[], severity text NOT NULL, report text NOT NULL,
  review_state text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, rule_id, version), FOREIGN KEY (tenant_id, rule_id) REFERENCES rules);
CREATE TABLE rule_sources (tenant_id text, rule_id text, version text, source_span_id uuid REFERENCES source_spans,
  section text, page int, FOREIGN KEY (tenant_id, rule_id, version) REFERENCES rule_versions);
CREATE TABLE applicability_conditions (id bigserial PRIMARY KEY, tenant_id text, rule_id text, version text,
  grp text NOT NULL CHECK (grp IN ('all','any')), fact text NOT NULL, op text NOT NULL, value jsonb, label_he text,
  FOREIGN KEY (tenant_id, rule_id, version) REFERENCES rule_versions);
CREATE TABLE rule_approvals (id bigserial PRIMARY KEY, tenant_id text NOT NULL, rule_id text NOT NULL, rule_version text NOT NULL,
  decision text NOT NULL CHECK (decision IN ('APPROVED','REVOKED')), approved_by text NOT NULL REFERENCES users,
  note text NOT NULL, at timestamptz NOT NULL DEFAULT now());
CREATE TABLE acceptance_tests (id bigserial PRIMARY KEY, tenant_id text, rule_id text, version text,
  name text NOT NULL, facts jsonb NOT NULL, expected_status text NOT NULL, last_result text, last_run timestamptz);

-- cases ---------------------------------------------------------------------------------
CREATE TABLE permit_cases (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id text NOT NULL REFERENCES municipalities,
  case_number text NOT NULL, title text NOT NULL, is_demo boolean NOT NULL DEFAULT false, parcel_id uuid REFERENCES parcels,
  permit_type text NOT NULL, track text NOT NULL, stage text NOT NULL, zone text, applicable_plans text[],
  declared jsonb NOT NULL DEFAULT '{}', status text NOT NULL, assigned_to text REFERENCES users,
  sla_due timestamptz, locked_version int, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, case_number));
CREATE TABLE case_files (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id text NOT NULL, case_id uuid NOT NULL REFERENCES permit_cases,
  doc_type text NOT NULL, suggested_doc_type text, filename text NOT NULL, kind text NOT NULL, sha256 char(64) NOT NULL,
  size_bytes bigint NOT NULL, version int NOT NULL, supersedes_id uuid REFERENCES case_files, storage_uri text NOT NULL,
  ingest_status text NOT NULL, ingest_report jsonb, av_status text NOT NULL, signature_status text NOT NULL,
  lifecycle text NOT NULL DEFAULT 'ACTIVE', uploaded_by text REFERENCES users, uploaded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (case_id, sha256));
CREATE TABLE cad_entities (id bigserial PRIMARY KEY, tenant_id text NOT NULL, file_id uuid NOT NULL REFERENCES case_files,
  layer text NOT NULL, role text, dxftype text NOT NULL, geom geometry NOT NULL,   -- metres, local drawing CRS
  closed boolean, source_handle text, via_block text);
CREATE INDEX ON cad_entities USING gist (geom);
CREATE TABLE check_runs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id text NOT NULL, case_id uuid NOT NULL REFERENCES permit_cases,
  version int NOT NULL, ruleset_hash char(64) NOT NULL, input_hashes jsonb NOT NULL, measurements jsonb,
  summary jsonb, started_at timestamptz NOT NULL DEFAULT now(), duration_ms int, locked boolean NOT NULL DEFAULT false,
  UNIQUE (case_id, version));
CREATE TABLE findings (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id text NOT NULL, run_id uuid NOT NULL REFERENCES check_runs,
  report text NOT NULL, rule_id text NOT NULL, rule_version text NOT NULL,
  computed_result text NOT NULL CHECK (computed_result IN ('PASS','FAIL','UNCERTAIN','NA')),
  status text NOT NULL CHECK (status IN ('PASS','FAIL','UNCERTAIN','NA')), severity text NOT NULL,
  title_he text NOT NULL, explanation_he text NOT NULL, fix_hint_he text, measured_value double precision,
  measured_uncertainty double precision, threshold double precision, operator text, units text,
  confidence real NOT NULL, citations jsonb NOT NULL, evidence jsonb, overlay geometry, flags text[]);
CREATE TABLE overrides (id bigserial PRIMARY KEY, tenant_id text NOT NULL, finding_id uuid NOT NULL REFERENCES findings,
  decision text NOT NULL CHECK (decision IN ('CONFIRMED','OVERRIDDEN')), note text NOT NULL,
  reviewer_id text NOT NULL REFERENCES users, at timestamptz NOT NULL DEFAULT now());
CREATE TABLE approvals (id bigserial PRIMARY KEY, tenant_id text NOT NULL, case_id uuid NOT NULL REFERENCES permit_cases,
  run_id uuid NOT NULL REFERENCES check_runs, approved_by text NOT NULL REFERENCES users, at timestamptz NOT NULL DEFAULT now());

-- audit / AI / integrations ---------------------------------------------------------------
CREATE TABLE audit_events (id bigserial PRIMARY KEY, tenant_id text NOT NULL, at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL, action text NOT NULL, entity text NOT NULL, entity_id text, detail jsonb NOT NULL,
  prev_hash char(64) NOT NULL, hash char(64) NOT NULL);
REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;   -- append-only for the app role
CREATE TABLE ai_providers (id text PRIMARY KEY, kind text NOT NULL, location text NOT NULL, tasks text[] NOT NULL,
  model_version text NOT NULL, approved boolean NOT NULL, enabled boolean NOT NULL, no_training_on_data boolean,
  cost_per_unit_ils numeric(10,4));
CREATE TABLE ai_policies (id bigserial PRIMARY KEY, tenant_id text NOT NULL, task text NOT NULL, data_class text NOT NULL,
  mode text NOT NULL CHECK (mode IN ('LOCAL','CLOUD','HYBRID')), provider_order text[] NOT NULL,
  approved_by text REFERENCES users, approved_at timestamptz);
CREATE TABLE inference_costs (id bigserial PRIMARY KEY, tenant_id text NOT NULL, case_id uuid, user_id text, task text NOT NULL,
  provider_id text NOT NULL, model_version text NOT NULL, outcome text NOT NULL, latency_ms int, units real,
  cost_ils numeric(10,4), at timestamptz NOT NULL DEFAULT now());
CREATE TABLE integrations (id text PRIMARY KEY, name_he text NOT NULL, stage int, status text NOT NULL DEFAULT 'PLANNED',
  enabled boolean NOT NULL DEFAULT false CHECK (enabled = false OR status = 'APPROVED'));
CREATE TABLE integration_permissions (integration_id text REFERENCES integrations, tenant_id text REFERENCES municipalities,
  scope text NOT NULL, approved_by text REFERENCES users, approved_at timestamptz, PRIMARY KEY (integration_id, tenant_id, scope));

-- Row Level Security (example; repeat for every tenant table)
ALTER TABLE permit_cases ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON permit_cases USING (tenant_id = current_setting('app.tenant_id'));
