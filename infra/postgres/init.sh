#!/bin/sh
# Runs inside the postgres container on first start (docker-entrypoint-initdb.d).
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v db="$POSTGRES_DB" \
  -v owner_password="$DB_OWNER_PASSWORD" \
  -v app_user_password="$DB_APP_USER_PASSWORD" \
  -f /opt/taskflow/init.sql
