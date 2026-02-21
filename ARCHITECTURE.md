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

## Module Checklist (Definition of Done)

When creating or changing a module, verify:

- `api/*` uses explicit `response_model` (or explicit binary `responses` for streams).
- request/response DTO live in `api/*schemas.py`.
- endpoint logic is thin; business behavior is in `application/*`.
- domain-specific exceptions are declared in `domain/errors.py` and used in `application`.
- ORM queries are isolated in `infrastructure/repositories.py`.
- new routes are included only through `app/api/v1/routers.py`.

## Layer Rules

- `api` can call only `application` and shared dependency providers.
- `application` can call repositories via UoW/session.
- `infrastructure` must not import `api`.
- Cross-module access should go through UoW repositories or explicit service calls.

## Transaction Rules

- Open transaction scope in endpoint: `with uow:`.
- API layer owns transaction boundary and commit point.
- Mutating flows call `uow.commit()` exactly once per request path.
- `application/*` services do not call `commit()`.
- Use `flush()` only when DB-generated values are required before commit.
- On exceptions, rollback is handled by UoW context manager.

## API/Error Contract Rules

- Protected routers must expose unified error responses in OpenAPI: `400/401/403/404/409/422` with `ApiErrorResponseDTO`.
- Public routers expose validation error contract (`422`) with `ApiErrorResponseDTO`.
- Runtime error envelope is stable:
  - `{"error": {"code": "...", "message": "...", "details": ...}}`
- `204 No Content` endpoints must not return JSON body.
- Binary endpoints must document explicit media type (`application/pdf`, `application/octet-stream`) and `format: binary`.

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
  - access control test (`401/403`)
  - input validation tests (`422`)
  - OpenAPI contract assertion for response schema and error statuses

## Quick Anti-Patterns

- fat routers with business logic and DB branching
- direct ORM usage in `api/*`
- committing inside `application/*`
- adding new response shape without updating OpenAPI contract tests
- introducing migration with runtime/domain behavior
