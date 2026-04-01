# DIMAX Installer Audit — Phase 1 DB

Status legend: `PASS` / `FAIL`

Re-run baseline after:
- `migrations/002_schema_alignment.sql`
- `migrations/003_seed_baseline.sql`

## 1.1 Tables and constraints

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 1.1.1* | `companies` exists with `id`, `name`, `created_at` | `docker compose exec db psql -U postgres -d dimax -c "\d companies"` | All three fields present, `id` UUID PK | PASS | Baseline table present |
| 1.1.2* | `users` has `id`, `company_id`, `email (citext)`, `role`, `status` | `docker compose exec db psql -U postgres -d dimax -c "\d users"` | `email` is `citext`; `status` exists with CHECK | PASS | `email` migrated to `citext`, `status` added with `ck_users_status` |
| 1.1.3* | `installer_profiles` exists with `language` CHECK in (`ru`,`en`,`he`) | `docker compose exec db psql -U postgres -d dimax -c "\d installer_profiles"` | Table exists with language constraint | PASS | `ck_installer_profiles_language` present |
| 1.1.4* | `projects` has `lifecycle_status` and `health_status` with CHECK constraints | `docker compose exec db psql -U postgres -d dimax -c "\d projects"` | lifecycle/health fields exist | PASS | `ck_projects_lifecycle_status` and `ck_projects_health_status` present |
| 1.1.5* | `doors` has `status`, `is_critical`, `version`, `surcharge_pct` | `docker compose exec db psql -U postgres -d dimax -c "\d doors"` | Required fields exist with defaults | PASS | Added and backfilled |
| 1.1.6* | `door_status_history` exists | `docker compose exec db psql -U postgres -d dimax -c "\d door_status_history"` | Table exists with FK to `doors` and `users` | PASS | Table and FK graph present |
| 1.1.7* | `door_assignments` exists | `docker compose exec db psql -U postgres -d dimax -c "\d door_assignments"` | Table exists with assignment history fields | PASS | Table and indexes present |
| 1.1.8* | `completed_work` exists with `entry_type`, `correction_ref_id` | `docker compose exec db psql -U postgres -d dimax -c "\d completed_work"` | Table exists with correction ledger fields | PASS | `ORIGINAL/REVERSAL/CORRECTION` check present |
| 1.1.9* | `client_price_snapshots` exists | `docker compose exec db psql -U postgres -d dimax -c "\d client_price_snapshots"` | Table exists with generated `margin` | PASS | Stored generated `margin` present |
| 1.1.10* | `issues` has `status` and `workflow_state` constraints | `docker compose exec db psql -U postgres -d dimax -c "\d issues"` | Required fields exist with allowed states | PASS | Enum-backed constraints present |
| 1.1.11* | `issue_comments` exists | `docker compose exec db psql -U postgres -d dimax -c "\d issue_comments"` | Table exists with FK to `issues` and `users` | PASS | Added to alignment migration and verified |
| 1.1.12* | `sync_queue_items` exists with `status` and `conflict_code` | `docker compose exec db psql -U postgres -d dimax -c "\d sync_queue_items"` | Table exists with specified status model | PASS | `ck_sync_queue_items_status` present |
| 1.1.13* | `refresh_sessions` exists with `token_hash` | `docker compose exec db psql -U postgres -d dimax -c "\d refresh_sessions"` | Table named `refresh_sessions`, `token_hash NOT NULL` | PASS | Created parallel to legacy `auth_refresh_tokens` and backfilled |
| 1.1.14* | `journal_events` exists | `docker compose exec db psql -U postgres -d dimax -c "\d journal_events"` | Event journal table exists | PASS | Table and `entity_id` index present |
| 1.1.15* | `notification_outbox` exists with unique `idempotency_key` | `docker compose exec db psql -U postgres -d dimax -c "\d notification_outbox"` | Table exists and unique key present | PASS | `uq_notification_outbox_idempotency` present |
| 1.1.16* | `product_library` and `client_price_list` exist | `docker compose exec db psql -U postgres -d dimax -c "\d product_library"` and `\d client_price_list` | Both tables exist | PASS | Both tables aligned |
| 1.1.17* | `additional_work_types` exists | `docker compose exec db psql -U postgres -d dimax -c "\d additional_work_types"` | Table exists with localized names and pricing | PASS | Localized names and price fields present |
| 1.1.18* | `project_work_items` exists | `docker compose exec db psql -U postgres -d dimax -c "\d project_work_items"` | Table exists with surcharge fields | PASS | `surcharge_pct` and `apply_surcharge_to_installer` present |
| 1.1.19* | `door_types` has `is_critical_default` | `docker compose exec db psql -U postgres -d dimax -c "\d door_types"` | Field exists with default false | PASS | Column added and seeded |
| 1.1.20 | Seed data loaded | `SELECT count(*) FROM companies; SELECT count(*) FROM users; SELECT count(*) FROM door_types;` | `companies>=1`, `users>=3`, `door_types>=6` | PASS | `companies=3`, `users=7`, `door_types=20` |

## 1.2 Indexes and performance

| # | Check | Command / action | Pass criterion | Status | Notes |
|---|---|---|---|---|---|
| 1.2.1 | Index on `doors.project_id` | `docker compose exec db psql -U postgres -d dimax -c "\d doors"` | Index present | PASS | `ix_doors_project_id` exists |
| 1.2.2 | Index on `sync_queue_items.user_id` and `status` | `docker compose exec db psql -U postgres -d dimax -c "\d sync_queue_items"` | Required indexes present | PASS | `ix_sync_queue_items_user_status` exists |
| 1.2.3 | Index on `completed_work.installer_id, completed_at` | `docker compose exec db psql -U postgres -d dimax -c "\d completed_work"` | Index present | PASS | `ix_completed_work_installer_completed_at` exists |
| 1.2.4 | Index on `journal_events.entity_id` | `docker compose exec db psql -U postgres -d dimax -c "\d journal_events"` | Index present | PASS | `ix_journal_events_entity_id` exists |
| 1.2.5 | UNIQUE on `projects.code` per company | `docker compose exec db psql -U postgres -d dimax -c "\d projects"` | `UNIQUE (company_id, code)` | PASS | Implemented as partial unique for active rows: `(company_id, code) WHERE deleted_at IS NULL` |
| 1.2.6 | UNIQUE on `doors.door_code` per project | `docker compose exec db psql -U postgres -d dimax -c "\d doors"` | `UNIQUE (project_id, door_code)` | PASS | `uq_doors_project_door_code` exists |

## Phase 1 result

- Total checks: `26`
- PASS: `26`
- FAIL: `0`
- Critical PASS: `20`
- Critical FAIL: `0`
- Non-critical PASS: `6`
- Non-critical FAIL: `0`

## Release impact

Phase 1 no longer blocks Phase 2. Schema baseline required by API, Business Logic, and Offline audit phases is now present in the database.
