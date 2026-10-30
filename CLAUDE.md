# CLAUDE.md

## Project
Multi-tenant task management SaaS. See PLAN.md for full spec. Always read PLAN.md before starting a task.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, PostgreSQL 16, Redis 7
- Frontend: React 18, Vite, TypeScript, TanStack Query, Tailwind

## Rules
- Follow the layering in PLAN.md section 3: routers -> services -> repositories. No DB queries in routers.
- Every tenant-owned table must have organization_id and be covered by RLS.
- Every state-changing service method must call AuditService.record in the same transaction.
- Never return ORM objects from endpoints; use Pydantic schemas.
- Use Decimal for money, never float.
- Use UUID primary keys and timestamptz in UTC.
- Return 404 (not 403) for resources in another organization.
- Never log passwords, tokens, or the Authorization header.

## Commands
- Backend tests: `cd backend && pytest`
- Lint: `ruff check . && ruff format --check . && mypy app`
- Migrations: `alembic upgrade head`
- Dev stack: `docker compose up --build`

## Workflow
- Work one phase at a time. Stop at the end of each phase and summarize.
- Write or update tests in the same change as the code.
- Run lint and tests before declaring a task done.
- Make small commits with conventional messages (feat:, fix:, test:, chore:).
