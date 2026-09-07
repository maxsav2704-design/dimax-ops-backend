BEGIN;

INSERT INTO door_types (
  id,
  created_at,
  updated_at,
  company_id,
  code,
  name,
  is_active,
  is_critical_default
)
SELECT
  gen_random_uuid(),
  now(),
  now(),
  c.id,
  seed.code,
  seed.name,
  true,
  seed.is_critical_default
FROM companies c
CROSS JOIN (
  VALUES
    ('ENTRY_SINGLE', 'Single entry door', false),
    ('ENTRY_DOUBLE', 'Double entry door', true),
    ('INTERIOR_STD', 'Standard interior door', false),
    ('FIRE_60', 'Fire door 60m', true),
    ('SERVICE_METAL', 'Service metal door', false),
    ('SLIDING_GLASS', 'Sliding glass system', false)
) AS seed(code, name, is_critical_default)
ON CONFLICT (company_id, code) DO UPDATE
SET
  name = EXCLUDED.name,
  is_active = true,
  is_critical_default = EXCLUDED.is_critical_default,
  updated_at = now();

COMMIT;
