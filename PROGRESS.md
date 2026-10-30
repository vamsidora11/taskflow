# Progress

Status of each phase in [PLAN.md](PLAN.md) section 12, and, just as important, what has **not** been
verified. Update this at the end of every session.

| Phase | Scope | State |
|---|---|---|
| 0 | Monorepo, health endpoints, Swagger config, compose, CI | Done |
| 1 | Models, migrations, roles, RLS, tenant session | Done |
| 2 | Auth: Argon2id, JWT, rotating refresh tokens with reuse detection | Done |
| 3 | RBAC, invitations, member management, last-admin guard | Done |
| 4 | Boards, columns, tasks, atomic moves, ownership rules, idempotency | Done |
| 5 | Comments, append-only audit log wired into every state change | Done |
| 6 | Rate limiting, security headers, CORS, structured redacted logging | Done |
| 7 | React frontend | See the frontend section of the final report |
| 8 | Coverage, seed, production compose, deployment docs, README | Written; not deployed |

## Verified (ran and passed)

- Backend: Ruff, mypy (strict) and the full pytest suite against a real PostgreSQL 16.
- Migrations run up, down and up again; the models match the migrations exactly.
- Tenant isolation, RBAC matrix (every role and permission), refresh-token reuse, audit
  append-only privileges, and secret hygiene have dedicated tests.
- Key behaviours were checked with deliberate mutations (breaking the code makes tests fail).

## Not verified

- **Docker.** `docker compose up`, the prod compose file and the image builds have never been run on
  the development machine (no Docker installed). The compose files were only YAML-validated.
- **Real Redis.** Local runs used an in-memory fake; the real-Redis variants of the limiter and
  idempotency tests run in CI.
- **Deployment.** Nothing is deployed; there is no live URL. `render.yaml` and
  `docs/DEPLOYMENT.md` are untested templates.
- **GitHub Actions.** The workflow was YAML-validated but has not run on GitHub.
- **Browser behaviour and Lighthouse** for the frontend (no browser was available).

## Known limitations

- The invitation token is in a URL path, so proxy access logs are sensitive.
- Pagination of task lists is keyset-based and not a snapshot under concurrent moves.
- Attachments (optional in the plan) are not implemented.
