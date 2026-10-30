# TaskFlow

A multi-tenant SaaS task-management platform in the style of Trello and Jira. Organizations sign up,
get fully isolated data, role-based access, kanban boards, tasks, comments and an audit trail.

The specification is [PLAN.md](PLAN.md); contributor conventions are in [CLAUDE.md](CLAUDE.md);
build status and what is verified is in [PROGRESS.md](PROGRESS.md).

## Features

- Organization signup; the creator becomes admin. Invitations by email (single-use, expiring).
- Roles per organization: **admin**, **manager**, **member**, enforced by one permission matrix.
- Boards, columns, tasks (assignee, priority, due date), drag-and-drop ordering, comments.
- Append-only audit log of every significant action.
- JWT access tokens with rotating, reuse-detecting refresh tokens.
- Rate limiting, security headers, structured logging, idempotent task creation.
- React SPA: login, org switcher, kanban board, task drawer, members, activity feed.

Out of scope for v1 (future work): real-time collaboration over WebSockets, billing, SSO/SAML/OAuth
login, a mobile app, file attachments (planned with S3-compatible storage).

## Architecture

```
          +-------------------+
          |  React SPA (Vite) |
          +---------+---------+
                    | HTTPS, JSON, Bearer JWT (+ HttpOnly refresh cookie)
          +---------v---------+
          |  Nginx (TLS, one  |   SPA and API share one origin
          |  origin, proxy)   |
          +---------+---------+
                    |
          +---------v--------------------------------+
          |              FastAPI                     |
          |  middleware: CORS, security headers,     |
          |              request id, access log      |
          |  routers  ->  services  ->  repositories |
          |  (HTTP)       (rules)       (SQL only)   |
          +----+------------------------+------------+
               |                        |
     +---------v--------+      +--------v--------+
     |  PostgreSQL 16   |      |     Redis 7     |
     |  RLS on every    |      |  rate limits,   |
     |  tenant table    |      |  idempotency    |
     +------------------+      +-----------------+
```

Layering rules (enforced by review and by the tests): routers only handle HTTP; services hold the
business rules and never import FastAPI; repositories are the only place that writes SQL; Pydantic
schemas are separate from ORM models and ORM objects are never returned.

## Quick start

**Everything in containers** (needs Docker):

```bash
cp .env.example .env          # then set the passwords and JWT_SECRET_KEY
docker compose up --build     # app at http://localhost:8080
docker compose exec backend python -m scripts.seed   # optional demo data
```

- App: http://localhost:8080 · API docs: http://localhost:8080/docs · Health: `/health`, `/health/ready`

**Backend only** (Python 3.12, a PostgreSQL 16 and a Redis 7 reachable):

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head                                       # as the owner role, see below
uvicorn app.main:app --reload
```

**Frontend only:** `cd frontend && npm install && npm run dev` (proxies `/api` to `localhost:8000`).

### Demo accounts

After `python -m scripts.seed` (demo data only, never run it against production). Every account uses
the password **`demo-password-123`**.

| Organization | Role | Email |
|---|---|---|
| Acme Corp | admin | `ada@acme.example` |
| Acme Corp | manager | `grace@acme.example` |
| Acme Corp **and** Globex Inc | member | `alan@acme.example` (shows the org switcher) |
| Globex Inc | admin | `hank@globex.example` |

> No live deployment exists yet, so there is no public demo URL. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Testing and CI

```bash
cd backend
ruff check . && ruff format --check . && mypy app scripts tests
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres  # superuser
pytest                       # unit, integration and security suites; about 8 minutes
pytest tests/security        # the security suite alone
pytest --cov=app --cov-fail-under=80
```

Tests run against a **real PostgreSQL** (no database mocking). The suite creates its own roles
(`tf_test_owner`, `tf_test_app`) and a throwaway database, applies the real migrations, connects as
the unprivileged runtime role, and drops everything afterwards. Without a reachable server the
database tests are skipped locally and **fail** in CI. A reachable Redis (`REDIS_URL`) additionally
enables the real-Redis variants of the limiter and idempotency tests; everything else uses an
in-memory fake.

GitHub Actions (`.github/workflows/ci.yml`) runs on every push: Ruff, mypy, the OpenAPI drift check,
the full backend suite with coverage against Postgres and Redis service containers, the frontend
lint, type check, tests and build, and a Docker build of both images.

`docs/openapi.json` is the committed API contract. After changing a route or schema run
`cd backend && python -m scripts.export_openapi`; a test and CI fail if it is stale. The frontend's
types are generated from it (`cd frontend && npm run gen:api`).

## Design decisions and trade-offs

**Shared-schema multi-tenancy with Row-Level Security.** Every tenant table carries
`organization_id`. PostgreSQL itself filters rows by a transaction-local `app.current_org_id`, so an
application bug cannot leak another tenant's data. The API connects as `app_user`, a role that does
not own the tables, is not a superuser and lacks `BYPASSRLS`; migrations run as `owner`. Policies are
`FORCE`d and fail closed (an unset setting matches nothing). *Trade-off:* cheap to operate and the
most common SaaS shape, but tenants share a database; a regulated customer would justify
schema- or database-per-tenant. Another tenant's resource answers **404, not 403**, so existence is
not revealed.

**Pre-tenant lookups through two narrow `SECURITY DEFINER` functions.** Login must find a user's
organizations before any is chosen, which RLS blocks. Rather than widening a policy, the lookups are
functions that return only what that step needs (the membership function takes no argument and reads
the caller's own id), with execute rights revoked from `PUBLIC`.

**Short-lived JWT access tokens and rotating refresh tokens.** A 15-minute HS256 access token lives
only in browser memory. The refresh token is opaque, stored only as a SHA-256 hash, and travels in an
`HttpOnly`, `SameSite=Strict`, `Secure` cookie scoped to `/api/v1/auth`. Each refresh token works once;
presenting a rotated one revokes the whole token family (the attack this stops: a stolen refresh token
being used silently alongside the real one). *Trade-off:* HS256 means every service that verifies
tokens holds the signing secret; RS256 would remove that at the cost of key management.
The role used on each request is read from the database, not the token, so demotion and removal take
effect immediately instead of when a token expires.

**Audit log is append-only in the database.** `app_user` holds `INSERT` and `SELECT` on `audit_logs`
and nothing else, so history cannot be rewritten even by a bug or SQL injection in the API. Rows are
written in the same transaction as the change they describe (the row exists if and only if the change
committed), carry the request id for correlation with logs, store field diffs rather than whole
records, and pass through a redactor so passwords and tokens never reach them.

**Rate limiting fails open.** Counters are atomic in Redis (`MULTI/EXEC`). If Redis is down the
limiter lets requests through and logs a warning, so a cache outage cannot take the API down.
*Trade-off:* during an outage there is no throttling, so alert on that warning. Idempotency is
deliberately the opposite: a request that sends an `Idempotency-Key` gets 503 rather than risking a
silent duplicate.

**Idempotent task creation.** Retrying `POST /boards/{id}/tasks` with the same `Idempotency-Key`
replays the original response for 24 hours. A different body with the same key is 409; concurrent
duplicates get 409 while the first runs; a failed request releases its key. The stored response is
written only after the transaction commits.

**Writes are durable before the response.** FastAPI runs a `yield` dependency's cleanup after the
response is sent by default, which would put the commit after the client's 201. The session
dependencies use `scope="function"` so the commit happens first, and a test proves it.

**Task order is exact, not approximate.** Positions are dense per column and renumbered in one
transaction under a row lock on the board, so concurrent moves cannot interleave and a failed move
changes nothing. *Trade-off:* writes to one board serialize; fine for human-scale boards.
List pagination is keyset-based, stable for a static board but not a snapshot.

**Invitations require a password.** Following the emailed link alone never grants access to an
existing account: new accounts choose a password, existing accounts must supply theirs.
The token travels in the URL path, as specified, so treat proxy access logs as sensitive.

**Behind a proxy.** The backend runs with `--proxy-headers`, so per-IP limits and audit rows see the
client address from `X-Forwarded-For`. nginx overwrites that header with the real peer address and
the backend port is not published; never expose the backend directly while it trusts that header.

**Hardening.** Security headers on every response, HSTS in staging and production,
`Cache-Control: no-store` under `/api/`, CORS limited to `FRONTEND_ORIGIN`, one structured JSON access
line per request (no headers, bodies or query strings; the invitation token in the path is masked),
and a redactor on every log record.

## What to change at 10x and 100x

Read replicas for lists, PgBouncer (compatible: RLS context is transaction-local), monthly
partitioning of `audit_logs`, rate limiting moved to the gateway with Redis as backstop, Redis caching
of hot reads, and email moved to a queue. Details in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Repository layout

```
backend/   FastAPI app (app/), Alembic migrations, tests (unit, integration, security), scripts
frontend/  React + Vite + TypeScript SPA
infra/     nginx and postgres configuration
docs/      openapi.json (the contract), DEPLOYMENT.md
```

Configuration is environment-driven; every variable is documented in [.env.example](.env.example).
Never commit real secrets.
