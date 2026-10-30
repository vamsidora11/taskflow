# TaskFlow

Multi-tenant SaaS task management platform. See [PLAN.md](PLAN.md) for the full specification and
[CLAUDE.md](CLAUDE.md) for contributor conventions. Current state: Phase 2 (authentication).

## Quick start

```bash
cp .env.example .env          # edit secrets
docker compose up --build     # app at http://localhost:8080
```

- API docs: http://localhost:8080/docs (when `ENABLE_DOCS=true`)
- Health: http://localhost:8080/health and http://localhost:8080/health/ready

## Backend (local)

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy app scripts tests && pytest
uvicorn app.main:app --reload
```

### Database tests

Tests run against a real PostgreSQL (see PLAN.md section 13). Point `TEST_DATABASE_URL` at a
**superuser** connection; the suite creates its own roles (`tf_test_owner`, `tf_test_app`) and a
throwaway database, applies the migrations, and drops it afterwards. Without a reachable server
the database tests are skipped locally and fail in CI. A reachable Redis (`REDIS_URL`) enables one
extra test.

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
```

### Migrations

`alembic upgrade head` connects with `MIGRATION_DATABASE_URL` (the `owner` role). The API itself
connects as `app_user` (`DATABASE_URL`), which has DML grants only, so row-level security applies.
`docker compose up` runs the migrations automatically before the API starts.

### Authentication

Try it in Swagger (`/docs`): `POST /api/v1/auth/signup`, copy the `access_token`, click
**Authorize**, then call `GET /api/v1/auth/me`.

- Access token: 15-minute HS256 JWT (`sub`, `org_id`, `role`, `iat`, `exp`, `jti`, `type`).
- Refresh token: opaque random value, stored only as a SHA-256 hash, delivered in an `HttpOnly`,
  `SameSite=Strict` cookie scoped to `/api/v1/auth`. Each token works once; replaying a rotated
  token revokes the whole family. The cookie is `Secure` by default (`COOKIE_SECURE`); browsers
  exempt `localhost`, so plain-HTTP local use works.
- Passwords: Argon2id, minimum 12 characters. Login returns the identical error for an unknown
  email, a wrong password and a disabled account.
- Every request re-checks the token against the live membership, so removing a member takes effect
  immediately rather than when their token expires.

Design note: login must find a user's organizations before any organization is chosen, which
row-level security on `memberships` would block. Rather than widening a policy, two narrow
`SECURITY DEFINER` functions (`auth_find_user_by_email`, `auth_list_memberships`) are the only
pre-tenant lookups; the second takes no argument and returns only the current user's rows.

## Frontend (local)

```bash
cd frontend && npm install && npm run dev
```
