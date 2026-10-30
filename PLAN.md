# Multi-Tenant SaaS Task Management Platform: Implementation Plan

A Trello/Jira-style platform where multiple organizations sign up, each with fully isolated data, role-based access, boards, tasks, comments, and an audit trail.

---

## 1. Goals and Scope

### Goals
- Demonstrate production-grade backend engineering: multi-tenancy, security, and clean architecture.
- Ship a working full-stack app that can be deployed and demoed in a portfolio or interview.
- Keep the codebase small enough to finish, but structured like a real company's service.

### In Scope (MVP)
- Organization signup and onboarding (creator becomes admin)
- User invitations to an organization by email
- Roles: Admin, Manager, Member
- Boards, columns (status lists), and tasks with assignees, priority, and due dates
- Comments on tasks
- Activity log (audit trail) for every significant action
- JWT access tokens with rotating refresh tokens
- Rate limiting on auth and write endpoints
- Web UI: login, org switcher, board view (kanban), task detail, activity feed, member management

### Out of Scope (for v1, mention as "future work" in README)
- Real-time collaboration via WebSockets
- Billing and subscriptions
- SSO / SAML / OAuth login with Google or GitHub
- Mobile app
- File attachments (can be added in phase 8 if time allows)

---

## 2. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend framework | FastAPI | Async, automatic OpenAPI docs, Pydantic validation, popular in industry |
| ORM | SQLAlchemy 2.0 (typed style) | Industry standard, explicit control over queries and transactions |
| Migrations | Alembic | Standard companion to SQLAlchemy |
| Database | PostgreSQL 16 | Row-Level Security, JSONB, strong constraints |
| Cache / rate limit store | Redis 7 | Fast counters for rate limiting, optional caching |
| Auth | JWT (PyJWT) + passlib[argon2] | Stateless access tokens, strong password hashing |
| Validation/settings | Pydantic v2, pydantic-settings | Typed config from environment variables |
| Testing | pytest, pytest-asyncio, httpx, testcontainers (optional) | Realistic integration tests against real Postgres |
| Frontend | React 18 + Vite + TypeScript | Fast dev loop, simpler than Next.js for an SPA dashboard |
| Frontend state/data | TanStack Query + React Router | Server-state caching, standard routing |
| Styling | Tailwind CSS (or Chakra UI) | Fast, consistent UI |
| Containers | Docker, Docker Compose | Reproducible local and deployed environments |
| CI/CD | GitHub Actions | Lint, type check, test, build images on every push |
| Lint/format | Ruff, mypy (backend); ESLint, Prettier (frontend) | Code quality signals for reviewers |

---

## 3. High-Level Architecture

```
          +-------------------+
          |  React SPA (Vite) |
          +---------+---------+
                    | HTTPS (JSON, Bearer JWT)
          +---------v---------+
          |   Nginx (reverse  |
          |   proxy / static) |
          +---------+---------+
                    |
          +---------v-----------------------------+
          |          FastAPI application          |
          |  +------------------------------+     |
          |  | Middleware                   |     |
          |  |  - Request ID / logging      |     |
          |  |  - Rate limiter (Redis)      |     |
          |  |  - Tenant context resolver   |     |
          |  +------------------------------+     |
          |  | Routers (HTTP layer)         |     |
          |  | Services (business logic)    |     |
          |  | Repositories (DB access)     |     |
          |  +------------------------------+     |
          +----+---------------------+------------+
               |                     |
     +---------v--------+   +--------v--------+
     |  PostgreSQL      |   |     Redis       |
     |  (RLS enabled)   |   | rate limits,    |
     +------------------+   | optional cache  |
                            +-----------------+
```

### Layering rules (enforce these; reviewers look for them)
- **Routers** handle HTTP only: parse input, call a service, return a response schema.
- **Services** hold business rules (e.g., "only managers can reassign tasks"). They do not import FastAPI.
- **Repositories** are the only place that writes SQLAlchemy queries.
- **Schemas** (Pydantic) are separate from **ORM models**. Never return ORM objects directly.

---

## 4. Multi-Tenancy Design

### Strategy: shared database, shared schema, `organization_id` on every tenant-owned table, plus Postgres Row-Level Security (RLS)

Why this approach: it is the most common SaaS pattern, cheap to operate, and RLS gives a database-level safety net so a bug in application code cannot leak another tenant's data.

### Rules
1. Every tenant-owned table has a non-null `organization_id` column with an index.
2. The tenant is resolved from the JWT claim `org_id` (the active organization for that session), never from a client-supplied header alone.
3. The request's `org_id` is verified against the user's active membership on every request.
4. A FastAPI dependency `get_tenant_session` opens a DB session and runs:
   ```sql
   SELECT set_config('app.current_org_id', :org_id, true);
   ```
   so RLS policies can filter rows.
5. RLS policy example for `tasks`:
   ```sql
   ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
   CREATE POLICY tenant_isolation ON tasks
     USING (organization_id = current_setting('app.current_org_id')::uuid);
   ```
6. The application DB role must **not** be a superuser or table owner, otherwise RLS is bypassed. Create a separate `app_user` role for the running service and keep migrations on an `owner` role.

### Tests that prove isolation (must exist)
- User A in Org 1 cannot read, update, or delete Org 2's boards, tasks, or comments (expect 404, not 403, to avoid leaking existence).
- Listing endpoints never return rows from another org even with a crafted `org_id`.
- Direct SQL as `app_user` without setting `app.current_org_id` returns zero rows.

---

## 5. Role-Based Access Control (RBAC)

Roles are scoped per organization. A user can be Admin in one org and Member in another.

### Permissions matrix

| Action | Admin | Manager | Member |
|---|:---:|:---:|:---:|
| Update organization settings | yes | no | no |
| Invite / remove users, change roles | yes | no | no |
| Create / archive boards | yes | yes | no |
| Create tasks | yes | yes | yes |
| Edit any task | yes | yes | no |
| Edit tasks assigned to self | yes | yes | yes |
| Delete tasks | yes | yes | no |
| Comment on tasks | yes | yes | yes |
| View activity log | yes | yes | no |
| View boards and tasks | yes | yes | yes |

### Implementation
- Define permissions as an enum (e.g., `TASK_DELETE`, `MEMBER_INVITE`) and map roles to permission sets in one file: `app/core/permissions.py`.
- Create a dependency `require_permission(Permission.TASK_DELETE)` used on routes.
- Business rules that depend on ownership (e.g., "member edits own task") live in the service layer, not in the router.
- Always keep at least one admin per organization (block the last admin from demoting themselves).

---

## 6. Data Model

All tenant-owned tables include `organization_id`. Primary keys are UUIDs. All timestamps are `timestamptz` in UTC.

```
organizations
  id, name, slug (unique), created_at, updated_at

users
  id, email (unique, lowercased), password_hash, full_name,
  is_active, created_at, updated_at

memberships
  id, organization_id -> organizations, user_id -> users,
  role (enum: admin|manager|member), created_at
  UNIQUE (organization_id, user_id)

invitations
  id, organization_id, email, role, token_hash, invited_by,
  expires_at, accepted_at, created_at

refresh_tokens
  id, user_id, organization_id, token_hash (unique), family_id,
  expires_at, revoked_at, replaced_by_id, created_at, user_agent, ip_address

boards
  id, organization_id, name, description, is_archived,
  created_by, created_at, updated_at

board_columns
  id, organization_id, board_id, name, position, created_at
  UNIQUE (board_id, position) DEFERRABLE

tasks
  id, organization_id, board_id, column_id, title, description,
  priority (enum: low|medium|high|urgent), status_position (int),
  assignee_id (nullable), due_date (nullable), created_by,
  created_at, updated_at, deleted_at (soft delete)

comments
  id, organization_id, task_id, author_id, body,
  created_at, updated_at, deleted_at

audit_logs
  id (bigserial), organization_id, actor_user_id (nullable),
  action (e.g., "task.updated"), entity_type, entity_id,
  metadata (JSONB, diff of changed fields), ip_address,
  request_id, created_at
  -- append-only: app role has INSERT and SELECT only, no UPDATE/DELETE
```

### Important constraints and indexes
- `memberships(organization_id, user_id)` unique.
- Composite indexes: `tasks(organization_id, board_id)`, `tasks(organization_id, assignee_id)`, `audit_logs(organization_id, created_at DESC)`.
- Foreign keys with explicit `ON DELETE` behavior.
- CHECK constraints on enums where practical.
- Use `Numeric` for any money field if you add one later (never float).

---

## 7. Authentication Design (JWT + Refresh Tokens)

### Tokens
- **Access token**: JWT, HS256 (or RS256 for bonus points), lifetime 15 minutes. Claims: `sub` (user id), `org_id`, `role`, `iat`, `exp`, `jti`, `type: "access"`.
- **Refresh token**: opaque random string (32+ bytes from `secrets.token_urlsafe`), lifetime 14 days. Stored only as a SHA-256 hash in `refresh_tokens`. Sent to the client in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie scoped to `/api/v1/auth`.

### Flows
1. **Signup** (`POST /auth/signup`): creates org + user + admin membership, returns tokens.
2. **Login** (`POST /auth/login`): verify password (constant-time), return access token and refresh cookie. Return the same generic error for unknown email and wrong password.
3. **Refresh** (`POST /auth/refresh`):
   - Look up the hashed refresh token.
   - If it is already revoked or replaced, this is **token reuse**: revoke the entire `family_id` and return 401. Log an audit event `auth.refresh_reuse_detected`.
   - Otherwise, issue a new refresh token in the same family, mark the old one with `replaced_by_id`, and issue a new access token.
4. **Logout** (`POST /auth/logout`): revoke the current family.
5. **Switch organization** (`POST /auth/switch-org`): verify membership, issue new access token with the new `org_id`.

### Security checklist
- Passwords hashed with Argon2id. Enforce minimum length 12.
- Login and refresh endpoints rate-limited per IP and per account.
- Account lockout is not required; rate limiting plus generic errors is enough for v1.
- Never log tokens or passwords. Redact the `Authorization` header in logs.
- CORS restricted to the frontend origin from settings.
- Security headers via middleware (`X-Content-Type-Options`, `Frame-Options`, `Strict-Transport-Security` in prod).

---

## 8. Audit Logs

### What to log
Every state-changing action writes one row to `audit_logs` inside the same DB transaction as the change:
- `auth.login`, `auth.login_failed`, `auth.refresh_reuse_detected`
- `org.updated`
- `member.invited`, `member.joined`, `member.role_changed`, `member.removed`
- `board.created`, `board.updated`, `board.archived`
- `task.created`, `task.updated`, `task.moved`, `task.deleted`
- `comment.created`, `comment.deleted`

### Implementation
- A single `AuditService.record(...)` method. Services call it, routers do not.
- `metadata` stores a before/after diff of changed fields only. Redact sensitive fields.
- Use `request_id` (from middleware) to correlate audit rows with application logs.
- Expose `GET /api/v1/audit-logs` with filters: `action`, `entity_type`, `actor_user_id`, date range, and cursor pagination. Admin and Manager only.
- Make the table append-only at the DB level (revoke UPDATE and DELETE from `app_user`).

---

## 9. Rate Limiting

### Approach
Redis-backed fixed or sliding window counter, implemented as a FastAPI dependency or middleware.

| Scope | Limit (example) |
|---|---|
| `POST /auth/login` per IP | 10 per minute |
| `POST /auth/login` per email | 5 per 15 minutes |
| `POST /auth/refresh` per IP | 30 per minute |
| Authenticated write endpoints per user | 120 per minute |
| Authenticated read endpoints per user | 600 per minute |

- Return `429 Too Many Requests` with `Retry-After` and `X-RateLimit-Limit` / `X-RateLimit-Remaining` headers.
- Use a Lua script or `INCR` + `EXPIRE` in a pipeline so the check is atomic.
- Make the limiter fail open if Redis is down (log a warning) so the app stays available. Document this trade-off in the README.
- Limits live in config, not hard-coded.

---

## 10. API Design

Base path: `/api/v1`. Responses use a consistent error envelope:
```json
{ "error": { "code": "TASK_NOT_FOUND", "message": "Task not found", "request_id": "..." } }
```

### Endpoints

**Auth**
- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `POST /auth/switch-org`
- `GET /auth/me`

**Organization and members**
- `GET /org`, `PATCH /org` (admin)
- `GET /org/members`
- `POST /org/invitations` (admin)
- `POST /org/invitations/{token}/accept`
- `PATCH /org/members/{user_id}` (change role, admin)
- `DELETE /org/members/{user_id}` (admin)

**Boards and columns**
- `GET /boards`, `POST /boards` (manager+)
- `GET /boards/{id}`, `PATCH /boards/{id}`, `DELETE /boards/{id}` (archive)
- `POST /boards/{id}/columns`, `PATCH /columns/{id}`, `DELETE /columns/{id}`

**Tasks**
- `GET /boards/{id}/tasks?column_id=&assignee_id=&priority=&cursor=&limit=`
- `POST /boards/{id}/tasks`
- `GET /tasks/{id}`, `PATCH /tasks/{id}`, `DELETE /tasks/{id}`
- `POST /tasks/{id}/move` (body: column_id, position)

**Comments**
- `GET /tasks/{id}/comments`, `POST /tasks/{id}/comments`
- `DELETE /comments/{id}` (author or manager+)

**Audit**
- `GET /audit-logs` (admin, manager)

**System**
- `GET /health` (liveness), `GET /health/ready` (checks DB and Redis)

### API conventions to implement
- Cursor-based pagination on lists (`next_cursor` in response).
- Filtering and sorting via query params, validated by Pydantic.
- `PATCH` for partial updates; `PUT` not used.
- `Idempotency-Key` header support on `POST /boards/{id}/tasks` (store key and response for 24 hours in Redis). Good talking point in interviews.
- OpenAPI docs at `/docs` with examples and tag groupings.

---

## 10A. Swagger / OpenAPI Documentation

FastAPI generates an OpenAPI 3.1 spec automatically from route definitions and Pydantic schemas. This section defines how to configure, enrich, test, and export it so the documentation is accurate, useful to frontend developers, and something you can show in interviews.

### 10A.1 Goals
- Interactive API explorer at `/docs` (Swagger UI) and a readable reference at `/redoc`.
- Every endpoint documented with summary, description, request examples, response schemas, and error responses.
- Working "Authorize" button so testers can call protected endpoints directly from Swagger.
- A versioned `openapi.json` committed to the repo, used to generate the typed TypeScript client for the frontend.
- A CI check that fails if the API changes without updating the spec.

### 10A.2 App-Level Configuration

Configure metadata, tags, and UI options in the app factory (`app/main.py`). Read the toggle from settings so docs can be disabled in production.

```python
from fastapi import FastAPI
from app.core.config import settings

TAGS_METADATA = [
    {"name": "auth", "description": "Signup, login, token refresh, logout, and organization switching."},
    {"name": "organization", "description": "Organization settings, members, and invitations."},
    {"name": "boards", "description": "Boards and their columns."},
    {"name": "tasks", "description": "Task CRUD, filtering, and moving between columns."},
    {"name": "comments", "description": "Comments on tasks."},
    {"name": "audit", "description": "Append-only activity log for compliance review."},
    {"name": "health", "description": "Liveness and readiness probes."},
]

app = FastAPI(
    title="TaskFlow API",
    version="1.0.0",
    summary="Multi-tenant task management platform",
    description=(
        "REST API for organizations, role-based boards and tasks, comments, and audit logs.\n\n"
        "**Authentication:** call `POST /api/v1/auth/login`, copy the `access_token`, "
        "and paste it into the Authorize dialog. Access tokens expire after 15 minutes; "
        "use `POST /api/v1/auth/refresh` to rotate them.\n\n"
        "**Tenancy:** the active organization is embedded in the access token. "
        "Use `POST /api/v1/auth/switch-org` to change it."
    ),
    contact={"name": "TaskFlow Team", "email": "support@example.com"},
    license_info={"name": "MIT"},
    openapi_tags=TAGS_METADATA,
    openapi_url="/api/v1/openapi.json" if settings.enable_docs else None,
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    swagger_ui_parameters={
        "persistAuthorization": True,   # keep the token after page refresh
        "docExpansion": "none",         # collapse operations by default
        "defaultModelsExpandDepth": -1, # hide the schemas section
        "displayRequestDuration": True,
    },
)
```

Config values to add to `core/config.py`:
- `enable_docs: bool` (default `True` in dev, `False` in production)
- `docs_basic_auth_user` and `docs_basic_auth_password` (optional; see 10A.8)

### 10A.3 Authentication Shown in Swagger

Declare the bearer scheme once so Swagger shows the Authorize button and a lock icon on protected routes.

```python
# app/core/security_scheme.py
from fastapi.security import HTTPBearer

bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description="Access token from `POST /api/v1/auth/login` or `/auth/refresh`. Expires after 15 minutes.",
    auto_error=True,
)
```

Use it inside `get_current_user` (`api/deps.py`) by depending on `bearer_scheme`. Because every protected route depends on `get_current_user`, Swagger marks them automatically without per-route changes.

Notes:
- The refresh token lives in an HttpOnly cookie. Swagger UI works with it only when served from the same origin as the API (the nginx setup in `docker-compose.yml` makes this true). Document this in the route description.
- Keep the `persistAuthorization` setting so testers do not log in again after every page refresh.

### 10A.4 Documenting Each Endpoint

Every route must declare these attributes. They are not optional; a test enforces them (see 10A.9).

| Attribute | Rule |
|---|---|
| `tags` | One of the tags in `TAGS_METADATA` |
| `summary` | Short imperative phrase, under 60 characters ("Create a task") |
| `description` | What it does, who can call it (roles), side effects (audit log), and important errors |
| `operation_id` | Stable snake_case name, e.g. `create_task`. Used by client generators and must never change once published |
| `response_model` | Pydantic schema, never a raw dict or ORM object |
| `status_code` | Explicit (`201` for creates, `204` for deletes with no body) |
| `responses` | Document each error code the route can return, using the shared error model |

Example route:

```python
# app/api/v1/tasks.py
from fastapi import APIRouter, Depends, Header, status
from app.schemas.task import TaskCreate, TaskRead
from app.schemas.errors import ErrorResponse
from app.api.deps import get_current_user, get_tenant_session, require_permission
from app.core.permissions import Permission

router = APIRouter(prefix="/api/v1", tags=["tasks"])

@router.post(
    "/boards/{board_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_task",
    summary="Create a task",
    description=(
        "Creates a task in the board's first column unless `column_id` is supplied.\n\n"
        "**Roles:** Admin, Manager, Member.\n\n"
        "**Idempotency:** send the same `Idempotency-Key` within 24 hours to receive the "
        "original response instead of creating a duplicate.\n\n"
        "**Audit:** writes a `task.created` entry."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Missing, expired, or invalid access token"},
        403: {"model": ErrorResponse, "description": "Caller lacks TASK_CREATE permission"},
        404: {"model": ErrorResponse, "description": "Board not found in the active organization"},
        409: {"model": ErrorResponse, "description": "Idempotency key reused with a different payload"},
        422: {"model": ErrorResponse, "description": "Request body failed validation"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
    dependencies=[Depends(require_permission(Permission.TASK_CREATE))],
)
async def create_task(
    board_id: UUID,
    payload: TaskCreate,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Unique key (max 128 chars) that makes retries safe.",
        max_length=128,
        examples=["6f1c2a8e-4b7d-4e9a-9d1f-2b3c4d5e6f70"],
    ),
    session=Depends(get_tenant_session),
    current_user=Depends(get_current_user),
) -> TaskRead:
    ...
```

Rules:
- Routers stay thin: the docstring-style text lives in `description`, and the logic lives in the service.
- Keep long descriptions in Markdown. Swagger renders it.
- Path, query, and header parameters get a `description` and, where useful, an `examples` value.

### 10A.5 Schema Examples in Pydantic Models

Every request and response schema includes at least one realistic example so Swagger's "Example Value" panel is useful.

```python
# app/schemas/task.py
from pydantic import BaseModel, ConfigDict, Field

class TaskCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "Prepare Q4 board deck",
                    "description": "Include revenue forecast and hiring plan.",
                    "priority": "high",
                    "assignee_id": "0b7c1f2e-9a3d-4c5b-8e7f-1a2b3c4d5e6f",
                    "due_date": "2026-11-15",
                }
            ]
        }
    )

    title: str = Field(min_length=1, max_length=200, description="Short task title.")
    description: str | None = Field(default=None, max_length=5000, description="Markdown body.")
    priority: Priority = Field(default=Priority.MEDIUM, description="Task priority.")
    assignee_id: UUID | None = Field(default=None, description="Must be a member of the same organization.")
    due_date: date | None = Field(default=None, description="ISO 8601 date (YYYY-MM-DD).")
```

Also apply:
- `Field(description=...)` on every field
- Enums for fixed values (`Priority`, `Role`) so the spec lists allowed values
- `Literal` or `Enum` in responses, never free-form strings for states
- Separate schemas for `Create`, `Update` (all fields optional), and `Read`

### 10A.6 Shared Error Model and Pagination Model

Define once, reuse everywhere.

```python
# app/schemas/errors.py
from pydantic import BaseModel, Field

class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable code, e.g. TASK_NOT_FOUND", examples=["TASK_NOT_FOUND"])
    message: str = Field(description="Human-readable message", examples=["Task not found"])
    request_id: str = Field(description="Correlates with server logs and audit rows", examples=["req_8f3a2c"])

class ErrorResponse(BaseModel):
    error: ErrorDetail
```

```python
# app/schemas/common.py
class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = Field(description="Pass as `cursor` to fetch the next page. Null on the last page.")
```

Also override the default FastAPI 422 response so validation errors use the same envelope. Register a handler in `main.py` that converts `RequestValidationError` into `ErrorResponse` with code `VALIDATION_ERROR`, and document this in the app `description`.

### 10A.7 Tags, Grouping, and Ordering

- Use exactly the tags in `TAGS_METADATA`. A test fails if a route uses an undeclared tag.
- Order tags in the list the way a new developer would learn the API: auth, organization, boards, tasks, comments, audit, health.
- Group by resource, not by HTTP method.

### 10A.8 Environment Control and Protecting Docs

| Environment | `/docs`, `/redoc`, `/openapi.json` |
|---|---|
| Local / dev | Enabled, no auth |
| CI | Enabled (needed for spec export) |
| Staging | Enabled behind HTTP Basic Auth (`docs_basic_auth_user` / `_password`) |
| Production | Disabled by default (`ENABLE_DOCS=false`). Enable only for a public demo, and then behind Basic Auth |

Implement Basic Auth as a small dependency applied to the docs routes. For the public portfolio demo, either keep docs enabled (it is a showcase) or document the choice in the README. Write the decision into the README's "design decisions" section.

### 10A.9 Testing the Documentation

Add these tests to `tests/integration/test_openapi.py`:

1. **Every operation has a summary, a tag from `TAGS_METADATA`, an `operation_id`, and a `response_model` or explicit 204.**
2. **Every protected route declares a `BearerAuth` security requirement** (catches routes accidentally left public).
3. **Every `operation_id` is unique** across the spec.
4. **Every route documents 401 and 422**, plus 403/404 where applicable.
5. **Every schema field has a description** (checks the `components/schemas` section).
6. **Docs are disabled when `ENABLE_DOCS=false`**: `/docs` and `/api/v1/openapi.json` return 404.
7. **Example request bodies validate against their own schemas** (parse each `examples` entry with the Pydantic model).

Sketch:

```python
def test_every_operation_has_summary_and_tag(client, valid_tags):
    spec = client.get("/api/v1/openapi.json").json()
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            assert op.get("summary"), f"{method.upper()} {path} missing summary"
            assert set(op.get("tags", [])) <= valid_tags, f"{method.upper()} {path} has unknown tag"
            assert op.get("operationId"), f"{method.upper()} {path} missing operationId"

def test_operation_ids_are_unique(client):
    spec = client.get("/api/v1/openapi.json").json()
    ids = [op["operationId"] for methods in spec["paths"].values() for op in methods.values()]
    assert len(ids) == len(set(ids))
```

### 10A.10 Exporting the Spec and Keeping It in Sync

1. **Export script** `backend/scripts/export_openapi.py`:
   ```python
   import json
   from pathlib import Path
   from app.main import app

   out = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
   out.parent.mkdir(exist_ok=True)
   out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
   print(f"Wrote {out}")
   ```
   Run with `python -m scripts.export_openapi`. Sorting keys keeps diffs readable.

2. **Commit `docs/openapi.json`** to the repo. It is the public contract.

3. **CI drift check** in `.github/workflows/ci.yml`:
   ```yaml
   - name: Verify OpenAPI spec is up to date
     run: |
       cd backend && python -m scripts.export_openapi
       git diff --exit-code ../docs/openapi.json
   ```
   If an endpoint changes, the developer must re-run the export and commit the updated spec. This is a strong talking point for reviewers.

4. **Generate the frontend client types** from the committed spec:
   ```bash
   cd frontend && npx openapi-typescript ../docs/openapi.json -o src/api/schema.ts
   ```
   Use the generated `paths` and `components` types in the typed API client (phase 7). Optional: generate a full client with `orval` for typed hooks with TanStack Query.

5. **Optional: export a Postman collection** from the spec (`openapi-to-postman` or Postman's import feature) and link it in the README.

### 10A.11 Swagger Acceptance Criteria

- `/docs` loads and lists all tags in the declared order.
- Login through Swagger's "Try it out" returns tokens, and the Authorize button then unlocks protected routes.
- Every operation shows a summary, description, example request body, and documented error responses.
- `docs/openapi.json` is committed, and CI fails when it drifts from the code.
- Docs can be disabled with `ENABLE_DOCS=false`.
- The 7 documentation tests in 10A.9 pass.
- Frontend `schema.ts` is generated from the committed spec.

---

## 11. Repository Structure

```
taskflow/
├── backend/
│   ├── app/
│   │   ├── main.py                  # app factory, middleware, router registration
│   │   ├── core/
│   │   │   ├── config.py            # pydantic-settings
│   │   │   ├── security.py          # hashing, JWT encode/decode
│   │   │   ├── permissions.py       # Permission enum + role map
│   │   │   ├── rate_limit.py        # Redis limiter
│   │   │   ├── logging.py           # structured JSON logs
│   │   │   └── exceptions.py        # domain errors -> HTTP mapping
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── session.py           # engine, session, tenant-scoped session
│   │   │   └── models/              # one file per model group
│   │   ├── schemas/                 # Pydantic request/response models
│   │   ├── repositories/            # DB queries
│   │   ├── services/                # business logic (auth, org, board, task, audit)
│   │   ├── api/
│   │   │   ├── deps.py              # get_current_user, get_tenant_session, require_permission
│   │   │   └── v1/                  # routers: auth, org, boards, tasks, comments, audit, health
│   │   └── middleware/              # request_id, security headers, rate limit
│   ├── migrations/                  # Alembic
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── security/                # tenant isolation and RBAC tests
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/                     # typed API client
│   │   ├── auth/                    # auth context, protected routes
│   │   ├── features/                # boards, tasks, comments, members, audit
│   │   ├── components/
│   │   └── pages/
│   ├── package.json
│   └── Dockerfile
├── infra/
│   ├── nginx/nginx.conf
│   └── postgres/init.sql            # roles: owner, app_user
├── docker-compose.yml
├── docker-compose.prod.yml
├── .github/workflows/ci.yml
├── .env.example
├── CLAUDE.md                        # instructions for Claude Code (see section 14)
└── README.md
```

---

## 12. Phased Implementation Plan

Each phase ends with a working, tested, committed state. Do not start a phase until the previous one passes its acceptance criteria.

### Phase 0: Setup (1 to 2 days)
**Tasks**
- Create monorepo, git init, `.gitignore`, `.editorconfig`.
- Backend: Python 3.12, `uv` or Poetry, FastAPI, SQLAlchemy, Alembic, pydantic-settings, pytest, Ruff, mypy.
- Frontend: Vite + React + TypeScript scaffold.
- `docker-compose.yml` with `postgres`, `redis`, `backend`, `frontend`, `nginx`.
- FastAPI app metadata, tag definitions, and Swagger UI options configured (section 10A.2); `ENABLE_DOCS` setting added.
- Bearer security scheme declared (section 10A.3).
- Health endpoints working.
- GitHub Actions running lint and tests on push.

**Acceptance criteria**
- `docker compose up` starts all services.
- `GET /health` and `GET /health/ready` return 200.
- CI is green on an empty test suite.

**Claude Code prompt example**
> Read CLAUDE.md and PLAN.md. Execute Phase 0. Set up the monorepo structure in section 11, create docker-compose.yml with postgres, redis, backend, and frontend, and implement the two health endpoints. Add a GitHub Actions workflow that runs ruff, mypy, and pytest. Stop after Phase 0 and summarize what was created.

### Phase 1: Database and Multi-Tenancy Foundation (3 to 4 days)
**Tasks**
- Implement SQLAlchemy models for organizations, users, memberships.
- Alembic setup and initial migration.
- Create Postgres roles (`owner`, `app_user`) in `infra/postgres/init.sql`.
- Implement `get_tenant_session` that sets `app.current_org_id`.
- Enable RLS on tenant tables created so far (memberships).
- Base repository class with tenant-aware query helpers.

**Acceptance criteria**
- Migrations run up and down cleanly.
- Test proves `app_user` without the org setting returns zero rows.
- Test proves setting org A returns only org A rows.

### Phase 2: Authentication (4 to 5 days)
**Tasks**
- Password hashing (Argon2id), JWT access tokens, refresh tokens with hashing and families.
- Endpoints: signup, login, refresh (with reuse detection), logout, switch-org, me.
- `get_current_user` dependency.
- Cookie handling for refresh tokens.
- Generic error messages for auth failures.

**Acceptance criteria**
- Full auth flow works via Swagger.
- Reusing a rotated refresh token revokes the whole family (test it).
- Expired access token returns 401; invalid signature returns 401.
- Login failure messages are identical for unknown email and wrong password.

### Phase 3: RBAC and Organization Management (3 to 4 days)
**Tasks**
- Permissions enum and role mapping.
- `require_permission` dependency.
- Invitations: create invite with hashed token, email link (console email backend in dev), accept endpoint.
- Member management: list, change role, remove.
- Guard: cannot remove or demote the last admin.

**Acceptance criteria**
- Parametrized test covering every cell in the RBAC matrix (section 5).
- Invitation token is single-use and expires.
- Last-admin protection works.

### Phase 4: Boards, Columns, Tasks (5 to 6 days)
**Tasks**
- Models and migrations for boards, columns, tasks.
- CRUD endpoints with pagination and filters.
- Task move endpoint (change column and position) in a transaction.
- Soft delete for tasks.
- Ownership rules: members edit only tasks assigned to them.
- Idempotency-Key support on task creation.

**Acceptance criteria**
- Moving a task updates column and position atomically.
- Filters work with combinations (column + assignee + priority).
- Cross-tenant access returns 404 (test it).

### Phase 5: Comments and Audit Logs (3 to 4 days)
**Tasks**
- Comments CRUD with permission checks.
- `AuditService` and audit log table with restricted DB privileges.
- Wire audit calls into every service method that changes state.
- Diff generation for `metadata` with sensitive field redaction.
- Audit log listing endpoint with filters and cursor pagination.

**Acceptance criteria**
- Every endpoint in section 6's action list writes exactly one audit row (test it).
- `app_user` cannot UPDATE or DELETE from `audit_logs` (test it).
- Audit rows never contain password or token values (test it).

### Phase 6: Rate Limiting and Security Hardening (2 to 3 days)
**Tasks**
- Redis-backed rate limiter with atomic counters.
- Per-IP and per-user limits per section 9.
- `429` responses with headers.
- Security headers middleware.
- Structured JSON logging with request IDs.
- Global exception handler that never leaks stack traces.

**Acceptance criteria**
- Login brute-force test is blocked after threshold.
- Rate limit headers present on responses.
- Redis outage does not take down the API (test with Redis stopped).

### Phase 7: Frontend (6 to 8 days)
**Tasks**
- Typed API client with automatic access-token refresh on 401 (single in-flight refresh promise).
- Pages: signup, login, accept invite, org dashboard, board (kanban with columns), task detail drawer, members page, activity log page.
- Org switcher in the header.
- Role-aware UI: hide buttons the user cannot use (backend remains the source of truth).
- Loading, empty, and error states on every data view.

**Acceptance criteria**
- A user can sign up, create a board, add tasks, drag tasks between columns, comment, invite a teammate, and see the activity log.
- Token refresh happens transparently when the access token expires.
- Lighthouse accessibility score above 90 on main pages.

### Phase 8: Quality, Deployment, and Polish (4 to 5 days)
**Tasks**
- Coverage target: 80%+ backend, with security tests as a separate suite.
- Seed script that creates two demo organizations with sample data.
- Production compose file with Nginx, HTTPS config notes, and env-based secrets.
- Deploy to Render, Railway, or an AWS free-tier EC2 instance.
- README with architecture diagram, setup steps, screenshots, and a "design decisions" section.
- Optional: attachments with S3-compatible storage (MinIO locally).

**Acceptance criteria**
- Live URL works and demo credentials are in the README.
- CI runs lint, type check, tests, and builds Docker images.
- README explains every enterprise feature and its trade-offs.

**Total estimate:** about 6 to 8 weeks part-time (3 to 4 hours a day), or 3 to 4 weeks full-time.

---

## 13. Testing Strategy

| Level | Tool | What it covers |
|---|---|---|
| Unit | pytest | Pure functions: permission map, token logic, diff generation, rate limit math |
| Integration | pytest + real Postgres and Redis (docker service or testcontainers) | Repositories, services, migrations |
| API | pytest + httpx `AsyncClient` | Every endpoint: happy path, validation error, auth error, permission error |
| Security | pytest, dedicated `tests/security/` | Tenant isolation, RBAC matrix, token reuse, audit immutability, no secrets in logs |
| Frontend | Vitest + React Testing Library | Auth interceptor, kanban move logic, role-based rendering |
| E2E (optional) | Playwright | Signup to invite to task to comment flow |

Rules:
- Tests use a fresh database per test session with migrations applied.
- No mocking of the database in integration tests.
- Factories (e.g., `factory-boy` or simple fixtures) for orgs, users, memberships, and tasks.

---

## 14. Working With Claude Code

### Create a `CLAUDE.md` at the repo root
Claude Code reads this file automatically. Put the following in it so every session follows the same conventions:

```markdown
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
```

### Tips for using Claude Code on this project
- Start each session with: "Read CLAUDE.md and PLAN.md, then continue from the current phase."
- Ask for a plan before code on each phase: "Propose the file changes for this step and wait for approval."
- Review the migrations and RLS policies by hand. Security-critical code deserves a human read.
- Keep a `PROGRESS.md` checklist and ask Claude Code to update it at the end of each session.
- If Claude Code drifts from the layering rules, point it back to section 3 of this file.

---

## 15. Definition of Done (whole project)

- [ ] All MVP features in section 1 work end to end in the UI
- [ ] Tenant isolation tests pass
- [ ] RBAC matrix tests pass
- [ ] Refresh token rotation and reuse detection tested
- [ ] Audit log written for every state change and append-only at DB level
- [ ] Rate limiting active on auth and write endpoints
- [ ] Backend coverage 80%+ and CI green
- [ ] `docker compose up` runs the full stack locally
- [ ] Deployed with a public URL
- [ ] Swagger UI at `/docs` documents every endpoint with examples, error responses, and a working Authorize flow
- [ ] `docs/openapi.json` committed, CI drift check passing, frontend types generated from it
- [ ] README includes architecture, setup, demo credentials, and design decisions
- [ ] Can explain every trade-off in section 16 out loud

---

## 16. Interview Talking Points

Be ready to explain:
1. **Why shared-schema multi-tenancy** instead of schema-per-tenant or database-per-tenant, and when you would change that.
2. **How RLS protects against application bugs**, and why the app role must not own the tables.
3. **Refresh token rotation and reuse detection**: what attack it stops and what happens on detection.
4. **Why 404 instead of 403** for cross-tenant access.
5. **Why audit logs are append-only** and how you enforce it.
6. **Why rate limiting fails open** and what the trade-off is.
7. **Idempotency keys**: what problem they solve for clients that retry.
8. **What you would change at 10x or 100x scale**: caching, read replicas, partitioning audit logs by month, moving rate limits to a gateway, splitting services.

---

## 17. Open Decisions (defaults used unless changed)

| Decision | Default in this plan | Alternative |
|---|---|---|
| Backend framework | FastAPI | Django REST Framework |
| Frontend | React + Vite SPA | Next.js |
| JWT algorithm | HS256 | RS256 with key pair |
| Email delivery | Console backend in dev, SMTP in prod | SendGrid, SES |
| Tenant identification | Active org in JWT (`org_id`) | Subdomain per org (e.g., acme.taskflow.app) |
| Deployment target | Render or Railway | AWS EC2 / ECS |
