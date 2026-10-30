-- Bootstrap roles and database ownership. Run by init.sh as the postgres superuser, on the
-- first start of an empty data volume. Passwords arrive as psql variables, never literals.
--
--   owner     owns the schema and runs migrations
--   app_user  runs the API: DML grants only (granted by migrations), not a superuser, not an
--             owner, and without BYPASSRLS, so row-level security always applies to it
CREATE ROLE owner LOGIN PASSWORD :'owner_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE app_user LOGIN PASSWORD :'app_user_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

-- :"db" is the identifier-quoted database name
ALTER DATABASE :"db" OWNER TO owner;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO owner, app_user;
GRANT USAGE ON SCHEMA public TO app_user;
