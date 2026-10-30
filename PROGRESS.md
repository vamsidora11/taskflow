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
| 7 | React frontend (kanban, drawer, members, activity, org switcher) | Done; tested with a mocked API only |
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
- **The frontend in a real browser, and against the real backend.** Its 103 tests, lint, type check
  and build pass, but they use a mocked `fetch` in jsdom. Not exercised: cookie behaviour end to end,
  pointer-based drag positions (only synthetic drag events were tested), the nginx SPA fallback.
- **Lighthouse accessibility score.** The Phase 7 target (above 90) has not been measured. axe finds
  no violations on the main pages in jsdom, but axe's colour-contrast rule does not run there.

## Known limitations

- `npm audit` reports advisories in the frontend's dev tooling (vitest 2 pulls in a vulnerable
  `tinypool`; vitest is pinned to 2 because newer releases conflict with Vite 5). They are
  development-only and not in the shipped bundle; upgrade Vite and vitest together to clear them.
- `jsdom` declares a Node engine range that older 22.x images may warn about on `npm install`.
- The API has no endpoint for user lookups or board totals, so the UI resolves names from the members
  list and loads a board by following `next_cursor`; very large boards cost many requests.

- The invitation token is in a URL path, so proxy access logs are sensitive.
- Pagination of task lists is keyset-based and not a snapshot under concurrent moves.
- Attachments (optional in the plan) are not implemented.
