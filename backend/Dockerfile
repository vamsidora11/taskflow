FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir .

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Behind nginx: trust X-Forwarded-For so per-IP rate limits and audit rows see the real client.
# Safe only because the backend port is not published; see docs on production deployment.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
