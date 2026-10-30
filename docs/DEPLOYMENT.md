# Deployment

TaskFlow is four containers behind one reverse proxy: PostgreSQL 16, Redis 7, the FastAPI backend
and the static frontend, with nginx in front. The SPA and the API share a single origin, which is
what makes the HttpOnly refresh cookie and Swagger's Authorize button work without CORS.

> **Status:** these files and steps are written and the backend is fully tested, but **nothing here
> has been deployed**, and the Docker images and compose files have not been run on the machine they
> were written on. Treat the first deployment as a verification step and expect small fixes.

## 1. Choose a path

| Path | Good for | Notes |
|---|---|---|
| Single VM (AWS EC2, any VPS) with `docker-compose.prod.yml` | Full control, cheapest | You manage TLS, backups and updates |
| Render / Railway with managed Postgres and Redis | Least operations | You must create the database roles by hand (section 3) |

## 2. Single VM with Docker Compose

1. Install Docker and Compose, point a DNS name at the VM, open ports 80 and 443 only.
2. Obtain a certificate and place `fullchain.pem` and `privkey.pem` in `./certs`
   (for Let's Encrypt: `certbot certonly --standalone -d your.domain`, then copy or symlink).
3. Create `.env.prod` (never commit it). Generate each secret independently:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET_KEY
   python -c "import secrets; print(secrets.token_urlsafe(24))"   # each database password
   ```
   ```dotenv
   POSTGRES_DB=taskflow
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=...
   DB_OWNER_PASSWORD=...
   DB_APP_USER_PASSWORD=...
   JWT_SECRET_KEY=...
   FRONTEND_ORIGIN=https://your.domain
   EMAIL_FROM=TaskFlow <no-reply@your.domain>
   SMTP_HOST=smtp.yourprovider.com
   SMTP_USER=...
   SMTP_PASSWORD=...
   ENABLE_DOCS=false
   ```
4. `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`
5. Check: `curl -I https://your.domain/health` and `https://your.domain/health/ready` return 200.
6. Optional demo data (never on a real tenant database):
   `docker compose -f docker-compose.prod.yml exec backend python -m scripts.seed`
   (the seed script needs `DATABASE_URL`, which the backend service already has).

The compose file starts the API only after the one-shot `migrate` service has succeeded, and the
API container never receives the owner password.

## 3. Managed platforms (Render, Railway)

`render.yaml` is a starting blueprint for Render. Three things need manual work on any managed
platform, because they require privileges a blueprint does not have:

1. **Database roles.** The app depends on two roles: `owner` (runs migrations, owns the tables) and
   `app_user` (runs the API, no DDL, subject to row-level security). Connect to the managed database
   with the admin URL and run [`infra/postgres/init.sql`](../infra/postgres/init.sql) using psql
   variables:
   ```bash
   psql "$ADMIN_DATABASE_URL" -v db=taskflow -v owner_password=... -v app_user_password=... \
     -f infra/postgres/init.sql
   ```
   If the platform's default user is the database owner and you cannot reassign ownership, create
   the roles anyway and run the migration as the default owner with `app_role=app_user`; the point is
   that **the API connects as a role that does not own the tables**, otherwise RLS is bypassed.
2. **Migrations.** Run `alembic upgrade head` as a release/pre-deploy command with
   `MIGRATION_DATABASE_URL` set to the owner role.
3. **Secrets.** Set `JWT_SECRET_KEY` (production refuses to start with the default), `DATABASE_URL`
   (the `app_user` URL), `REDIS_URL`, `FRONTEND_ORIGIN`, `COOKIE_SECURE=true`, `APP_ENV=production`
   and the SMTP settings in the platform's secret store.

If the platform terminates TLS and proxies to your containers, keep the backend private and make sure
the proxy overwrites `X-Forwarded-For` with the real client address. The backend trusts that header
(`--forwarded-allow-ips=*`), which is only safe when it is not reachable directly.

## 4. Production checklist

- [ ] `APP_ENV=production` (enables HSTS; startup fails on the default JWT secret)
- [ ] `ENABLE_DOCS=false`, or enabled deliberately for a public demo (then consider Basic Auth)
- [ ] `COOKIE_SECURE=true` and HTTPS everywhere
- [ ] Postgres and Redis not reachable from the internet; only nginx publishes ports
- [ ] The API connects as `app_user`; `SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='app_user'` is `f | f`
- [ ] Automated Postgres backups, and a restore you have actually tried
- [ ] Redis alerting: a Redis outage disables rate limiting (the limiter fails open) and idempotency checks
- [ ] Log shipping for the JSON logs, and alerts on `auth.refresh_reuse_detected` audit entries
- [ ] Access logs for the proxy treated as sensitive (invitation tokens travel in a URL path)

## 5. Scaling notes (what to change at 10x and 100x)

- Read replicas for list endpoints; PgBouncer in transaction mode (the code sets RLS context with
  transaction-local `set_config`, so it is compatible).
- Partition `audit_logs` by month; archive old partitions to cold storage.
- Move rate limiting to the gateway (nginx/Cloudflare) and keep the Redis limiter as a backstop.
- Cache hot reads (board detail) in Redis with short TTLs and invalidate on write.
- Split background work (email) out of the request process into a queue.
