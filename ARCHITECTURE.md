# Architecture Conventions

## Project Shape

Backend is a modular monolith:

- API composition: `app/api/v1/routers.py`
- Modules: `app/modules/*`
- Shared infrastructure: `app/shared/*`
- DB migrations: `alembic/versions/*`

## Module Template (Target Standard)

Each module should follow the same structure:

- `api/` HTTP routers + request/response DTO
- `application/` use cases and services
- `domain/` enums, domain rules, domain errors
- `infrastructure/` ORM models and repositories

If a module is missing one layer, keep changes minimal and align gradually to this template.

## Layer Rules

- `api` can call only `application` and shared dependency providers.
- `application` can call repositories via UoW/session.
- `infrastructure` must not import `api`.
- Cross-module access should go through UoW repositories or explicit service calls.

## Transaction Rules

- Open transaction scope in endpoint: `with uow:`.
- Mutating endpoints call `uow.commit()` exactly once.
- Services do not call `commit()`.
- Use `flush()` only when ID or DB-generated values are needed before commit.
- On errors, rollback happens via UoW context manager.

## Migration Rules

- Migrations are schema-only changes.
- Do not include business logic in migrations.
- Keep explicit names for constraints/indexes.
- Verify state with `alembic upgrade head` and integration tests.

## Testing Rules

- Integration tests live in `tests/integration`.
- Use dependency overrides for UoW/auth where needed.
- Every new admin endpoint should have:
  - success path test
  - access control test (`403`)
  - input validation tests (`422`)
