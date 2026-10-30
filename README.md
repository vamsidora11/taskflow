# TaskFlow

Multi-tenant SaaS task management platform. See [PLAN.md](PLAN.md) for the full specification and
[CLAUDE.md](CLAUDE.md) for contributor conventions. Current state: Phase 0 (skeleton).

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
ruff check . && ruff format --check . && mypy app scripts && pytest
uvicorn app.main:app --reload
```

## Frontend (local)

```bash
cd frontend && npm install && npm run dev
```
