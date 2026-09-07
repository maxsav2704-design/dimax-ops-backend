BEGIN;

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'door_status') THEN
    ALTER TYPE door_status ADD VALUE IF NOT EXISTS 'IN_PROGRESS';
    ALTER TYPE door_status ADD VALUE IF NOT EXISTS 'ISSUE_OPEN';
    ALTER TYPE door_status ADD VALUE IF NOT EXISTS 'LOCKED';
    ALTER TYPE door_status ADD VALUE IF NOT EXISTS 'CANCELLED';
  END IF;
END $$;

ALTER TABLE users
  ALTER COLUMN email TYPE citext USING email::citext;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS status varchar(20);

UPDATE users
SET status = CASE WHEN is_active THEN 'ACTIVE' ELSE 'INACTIVE' END
WHERE status IS NULL;

ALTER TABLE users
    ALTER COLUMN status SET DEFAULT 'ACTIVE';

ALTER TABLE users
    ALTER COLUMN status SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_users_status'
  ) THEN
    ALTER TABLE users
      ADD CONSTRAINT ck_users_status
      CHECK (status IN ('ACTIVE', 'INACTIVE', 'LOCKED'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS installer_profiles (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  installer_id uuid UNIQUE REFERENCES installers(id) ON DELETE CASCADE,
  display_name varchar(255),
  phone varchar(40),
  language varchar(8) NOT NULL DEFAULT 'en',
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_installer_profiles_language CHECK (language IN ('ru', 'en', 'he'))
);

INSERT INTO installer_profiles (user_id, company_id, installer_id, display_name, phone, language, is_active)
SELECT i.user_id, i.company_id, i.id, i.full_name, i.phone, 'en', i.is_active
FROM installers i
WHERE i.user_id IS NOT NULL
ON CONFLICT (user_id) DO UPDATE
SET
  company_id = EXCLUDED.company_id,
  installer_id = EXCLUDED.installer_id,
  display_name = EXCLUDED.display_name,
  phone = EXCLUDED.phone,
  is_active = EXCLUDED.is_active;

CREATE TABLE IF NOT EXISTS door_status_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  door_id uuid NOT NULL REFERENCES doors(id) ON DELETE CASCADE,
  changed_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  from_status varchar(40),
  to_status varchar(40) NOT NULL,
  reason text,
  source varchar(40) NOT NULL DEFAULT 'SYSTEM',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_door_status_history_door_id
  ON door_status_history (door_id);

CREATE TABLE IF NOT EXISTS door_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  door_id uuid NOT NULL REFERENCES doors(id) ON DELETE CASCADE,
  installer_id uuid NOT NULL REFERENCES installers(id) ON DELETE CASCADE,
  assigned_by uuid REFERENCES users(id) ON DELETE SET NULL,
  assigned_at timestamptz NOT NULL DEFAULT now(),
  unassigned_at timestamptz
);

CREATE INDEX IF NOT EXISTS ix_door_assignments_door_id
  ON door_assignments (door_id);

CREATE INDEX IF NOT EXISTS ix_door_assignments_installer_id
  ON door_assignments (installer_id);

CREATE TABLE IF NOT EXISTS product_library (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  sku varchar(80) NOT NULL,
  name_ru varchar(255) NOT NULL,
  name_he varchar(255) NOT NULL,
  install_type varchar(80) NOT NULL,
  manufacturer varchar(255),
  unit varchar(32) NOT NULL DEFAULT 'pcs',
  status varchar(20) NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_product_library_company_sku UNIQUE (company_id, sku),
  CONSTRAINT ck_product_library_status CHECK (status IN ('ACTIVE', 'ARCHIVED'))
);

CREATE TABLE IF NOT EXISTS client_price_list (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  product_id uuid NOT NULL REFERENCES product_library(id) ON DELETE CASCADE,
  base_client_rate numeric(12,2) NOT NULL,
  final_client_rate numeric(12,2) NOT NULL,
  effective_from date NOT NULL,
  effective_to date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_client_price_list_rates_nonnegative
    CHECK (base_client_rate >= 0 AND final_client_rate >= 0)
);

CREATE INDEX IF NOT EXISTS ix_client_price_list_product_effective
  ON client_price_list (product_id, effective_from DESC);

CREATE TABLE IF NOT EXISTS additional_work_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  code varchar(64) NOT NULL,
  name_ru varchar(255) NOT NULL,
  name_he varchar(255) NOT NULL,
  client_price numeric(12,2) NOT NULL DEFAULT 0,
  installer_rate numeric(12,2) NOT NULL DEFAULT 0,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_additional_work_types_company_code UNIQUE (company_id, code),
  CONSTRAINT ck_additional_work_types_prices_nonnegative
    CHECK (client_price >= 0 AND installer_rate >= 0)
);

CREATE TABLE IF NOT EXISTS project_work_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  additional_work_type_id uuid REFERENCES additional_work_types(id) ON DELETE SET NULL,
  door_id uuid REFERENCES doors(id) ON DELETE SET NULL,
  qty_planned numeric(12,2) NOT NULL DEFAULT 1,
  client_price numeric(12,2) NOT NULL DEFAULT 0,
  installer_rate numeric(12,2) NOT NULL DEFAULT 0,
  surcharge_pct numeric(6,2) NOT NULL DEFAULT 100,
  apply_surcharge_to_installer boolean NOT NULL DEFAULT false,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_project_work_items_surcharge_pct CHECK (surcharge_pct >= 100),
  CONSTRAINT ck_project_work_items_qty_positive CHECK (qty_planned > 0)
);

CREATE INDEX IF NOT EXISTS ix_project_work_items_project_id
  ON project_work_items (project_id);

CREATE TABLE IF NOT EXISTS completed_work (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
  door_id uuid REFERENCES doors(id) ON DELETE SET NULL,
  installer_id uuid NOT NULL REFERENCES installers(id) ON DELETE RESTRICT,
  completed_at timestamptz NOT NULL,
  quantity numeric(12,2) NOT NULL DEFAULT 1,
  rate_snapshot numeric(12,2) NOT NULL,
  amount_snapshot numeric(12,2) NOT NULL,
  entry_type varchar(20) NOT NULL DEFAULT 'ORIGINAL',
  correction_ref_id uuid REFERENCES completed_work(id) ON DELETE SET NULL,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_completed_work_entry_type
    CHECK (entry_type IN ('ORIGINAL', 'REVERSAL', 'CORRECTION'))
);

CREATE INDEX IF NOT EXISTS ix_completed_work_installer_completed_at
  ON completed_work (installer_id, completed_at DESC);

CREATE TABLE IF NOT EXISTS client_price_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    completed_work_id uuid NOT NULL UNIQUE REFERENCES completed_work(id) ON DELETE CASCADE,
  base_client_rate numeric(12,2) NOT NULL,
  final_client_rate numeric(12,2) NOT NULL,
  final_installer_rate numeric(12,2) NOT NULL,
  margin numeric(12,2) GENERATED ALWAYS AS (final_client_rate - final_installer_rate) STORED,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS issue_comments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    issue_id uuid NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    author_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    body text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_issue_comments_issue_id
    ON issue_comments(issue_id);

ALTER TABLE issues
  ADD COLUMN IF NOT EXISTS created_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS sync_queue_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id text,
  entity_type varchar(64) NOT NULL,
  entity_id uuid NOT NULL,
  operation_type varchar(64) NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  base_version integer NOT NULL DEFAULT 0,
  status varchar(20) NOT NULL DEFAULT 'PENDING',
  conflict_code varchar(64),
  created_at timestamptz NOT NULL DEFAULT now(),
  synced_at timestamptz,
  CONSTRAINT ck_sync_queue_items_status
    CHECK (status IN ('PENDING', 'APPLIED', 'CONFLICT', 'BLOCKED', 'AUTH_REQUIRED'))
);

CREATE INDEX IF NOT EXISTS ix_sync_queue_items_user_status
  ON sync_queue_items (user_id, status);

CREATE TABLE IF NOT EXISTS refresh_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  jti varchar(64) NOT NULL,
  token_hash text NOT NULL,
  device_id text,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  revoke_reason varchar(32),
  replaced_by_jti varchar(64),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_refresh_sessions_company_jti UNIQUE (company_id, jti),
  CONSTRAINT ck_refresh_sessions_revoke_reason
    CHECK (
      revoke_reason IS NULL
      OR revoke_reason IN ('LOGOUT', 'ROTATION', 'ADMIN_REVOKE', 'REPLAY_DETECTED')
    )
);

INSERT INTO refresh_sessions (
  company_id,
  user_id,
  jti,
  token_hash,
  expires_at,
  revoked_at,
  revoke_reason,
  replaced_by_jti,
  created_at,
  updated_at
)
SELECT
  company_id,
  user_id,
  jti,
  token_hash,
  expires_at,
  revoked_at,
  CASE WHEN revoked_at IS NOT NULL THEN 'ROTATION' ELSE NULL END,
  replaced_by_jti,
  created_at,
  updated_at
FROM auth_refresh_tokens
ON CONFLICT (company_id, jti) DO NOTHING;

CREATE TABLE IF NOT EXISTS journal_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  event_type varchar(80) NOT NULL,
  actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  entity_type varchar(80) NOT NULL,
  entity_id uuid NOT NULL,
  before_state jsonb,
  after_state jsonb,
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_journal_events_entity_id
  ON journal_events (entity_id);

CREATE TABLE IF NOT EXISTS notification_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  channel varchar(32) NOT NULL,
  target text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status varchar(20) NOT NULL DEFAULT 'PENDING',
  idempotency_key varchar(255) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz,
  CONSTRAINT uq_notification_outbox_idempotency UNIQUE (idempotency_key)
);

ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS lifecycle_status varchar(20),
  ADD COLUMN IF NOT EXISTS health_status varchar(20);

UPDATE projects
SET lifecycle_status = COALESCE(lifecycle_status, 'ACTIVE'),
    health_status = COALESCE(
      health_status,
      CASE WHEN status::text = 'PROBLEM' THEN 'AT_RISK' ELSE 'NORMAL' END
    );

ALTER TABLE projects
  ALTER COLUMN lifecycle_status SET NOT NULL,
  ALTER COLUMN health_status SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_projects_lifecycle_status'
  ) THEN
    ALTER TABLE projects
      ADD CONSTRAINT ck_projects_lifecycle_status
      CHECK (lifecycle_status IN ('PLANNED', 'ACTIVE', 'COMPLETED', 'ARCHIVED'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_projects_health_status'
  ) THEN
    ALTER TABLE projects
      ADD CONSTRAINT ck_projects_health_status
      CHECK (health_status IN ('NORMAL', 'AT_RISK', 'BLOCKED'));
  END IF;
END $$;

ALTER TABLE doors
  ADD COLUMN IF NOT EXISTS door_code varchar(120),
  ADD COLUMN IF NOT EXISTS is_critical boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS surcharge_pct numeric(6,2) NOT NULL DEFAULT 100;

UPDATE doors
SET door_code = COALESCE(NULLIF(door_code, ''), unit_label || '-' || left(id::text, 8))
WHERE door_code IS NULL OR door_code = '';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_doors_surcharge_pct'
  ) THEN
    ALTER TABLE doors
      ADD CONSTRAINT ck_doors_surcharge_pct
      CHECK (surcharge_pct >= 100);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_doors_project_door_code'
  ) THEN
    ALTER TABLE doors
      ADD CONSTRAINT uq_doors_project_door_code
      UNIQUE (project_id, door_code);
  END IF;
END $$;

ALTER TABLE door_types
  ADD COLUMN IF NOT EXISTS is_critical_default boolean NOT NULL DEFAULT false;

COMMIT;
