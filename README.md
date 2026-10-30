# TaskFlow

Multi-tenant SaaS task management platform. See [PLAN.md](PLAN.md) for the full specification and
[CLAUDE.md](CLAUDE.md) for contributor conventions. Current state: Phase 6 (backend complete: auth, RBAC, boards, tasks, comments, audit, rate limiting).

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

### Roles and organization management

Roles are per organization (`admin`, `manager`, `member`). The permission matrix lives in one file,
`backend/app/core/permissions.py`, and routes guard themselves with
`Depends(require_permission(Permission.X))`. `backend/tests/unit/test_permissions.py` restates the
matrix from PLAN.md section 5 independently and checks every role and permission pair.

- The role used on each request is read from the database, not from the token, so promoting,
  demoting or removing someone takes effect on their very next request.
- An organization always keeps at least one admin. Role changes and removals row-lock the admin
  memberships, so two admins demoting each other at once cannot both succeed.
- Invitations are single-use, expire after 7 days, and are stored hashed. Re-inviting an address
  replaces its pending invitation. Accepting requires a password: new accounts choose one,
  existing accounts must supply theirs, so the emailed link alone never unlocks an account.
- `EMAIL_BACKEND=console` prints invitation emails, including the link, to the server output for local
  development. Use `smtp` anywhere else.
- The invitation token travels in the URL path (`/org/invitations/{token}/accept`), as specified,
  so it can appear in HTTP access logs. Treat those logs as sensitive or switch access logging off.

### Boards, columns and tasks

- Every tenant table (`boards`, `board_columns`, `tasks`) carries `organization_id` and is covered by
  forced RLS. Another organization's board or task answers 404, exactly like one that does not exist.
- A new board gets To Do / In Progress / Done unless `columns` is supplied. Archiving (`DELETE`)
  makes a board read-only and hides it from the default list; `PATCH is_archived=false` restores it.
- Tasks keep a dense 0-based `position` within their column. Moving, creating and deleting take a row
  lock on the board and renumber in one transaction, so concurrent edits cannot interleave and a
  failed move changes nothing. Deleting a task is a soft delete; a column that still holds live
  tasks cannot be deleted.
- Ownership rules (service layer): admins and managers edit, move and reassign any task; a member
  edits and moves only tasks assigned to them, cannot reassign, and can create a task only for
  themselves or unassigned. Deleting tasks is admin/manager only.
- Task lists use keyset pagination in board order (column, then position). A task moved between page
  requests can appear twice or be skipped; the cursor is stable for a static board, not a snapshot.
- `POST /boards/{id}/tasks` honours `Idempotency-Key` (max 128 chars). The first response is kept in
  Redis for 24 hours and replayed with `Idempotent-Replay: true`; the same key with a different body
  is 409; concurrent duplicates get 409 while the first runs; a failed request releases its key.
  Keys are scoped to organization, user and URL, and are stored hashed. If Redis is unreachable, a
  request that sends the header gets 503 (a silent duplicate would defeat the point), while requests
  without it are unaffected.
- `docs/openapi.json` is the committed API contract. After changing any route or schema run
  `cd backend && python -m scripts.export_openapi`; a test and CI fail if it is stale.

### Rate limiting and hardening

- **Rate limits** (Redis, fixed window, atomic `INCR`+`EXPIRE`+`TTL` in one `MULTI/EXEC`), all from
  configuration: login 10/min per IP and 5 per 15 min per account, refresh 30/min per IP, signup and
  invitation-accept 10/min per IP, authenticated writes 120/min and reads 600/min per user. A 429
  carries `Retry-After`, `X-RateLimit-Limit` and `X-RateLimit-Remaining`; the same two budget headers
  appear on every response that was counted, including errors. Identities are hashed in Redis keys.
- **Fail open.** If Redis is unreachable the limiter logs a warning and lets the request through, so a
  Redis outage cannot take the API down. The trade-off is explicit: while Redis is down there is no
  throttling (brute-force protection is degraded), so alert on that warning. Idempotency is the
  opposite, deliberately: a request that sends `Idempotency-Key` gets 503 rather than risking a
  silent duplicate.
- **Behind a proxy**, the backend runs with `--proxy-headers`, so per-IP limits and audit rows see the
  client address from `X-Forwarded-For`. This is only safe because the backend port is not published;
  never expose it directly while `--forwarded-allow-ips=*` is set.
- **Security headers** on every response (`nosniff`, `DENY` framing, `no-referrer`, restrictive
  `Permissions-Policy`), `Strict-Transport-Security` in staging and production, and
  `Cache-Control: no-store` on all `/api/` responses. CORS allows only `FRONTEND_ORIGIN`, with
  credentials.
- **Logging** is structured JSON (`LOG_JSON=false` for plain text), one access line per request with
  the request id, status, duration and user id. Headers, bodies and query strings are never logged, the
  invitation token in the URL path is masked, and every record passes through a redactor for bearer
  tokens, JWTs and `password=`/`token=` style values. Unhandled errors return a generic 500 body.

## Frontend (local)

```bash
cd frontend && npm install && npm run dev
```
