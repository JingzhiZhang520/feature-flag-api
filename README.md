# Feature Flag API

A FastAPI backend that stores flags in PostgreSQL and evaluates them for individual users. An explicit user override always wins over the global default, including an override of `false`. A bounded in-process cache avoids repeated evaluation queries.

## Run with Docker

Requires Docker with Compose. Copy `.env.example` to `.env`, choose an alphanumeric local password, and replace both occurrences of `replace_me`. Do not commit `.env`.

```sh
cp .env.example .env
# Edit .env before continuing.
docker compose up --build -d
```

PostgreSQL starts first, the migration job creates the schema, and one API worker starts on http://localhost:8000. Interactive API documentation: http://localhost:8000/docs. `docker compose logs api migrate` shows startup output.

Ports bind to localhost. Database data lives in a named Docker volume and survives `docker compose down` and API restarts. Do not use `docker compose down -v` unless you intend to delete the database.

On this Mac, Docker Desktop's credential helper was absent from PATH and the existing buildx lock was root-owned. The verified workaround uses an independent temporary build-cache directory:

```sh
BUILDX_CONFIG=/private/tmp/feature-flags-buildx \
PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH" \
docker compose up --build -d
```

During local verification, a `demo-checkout` flag was created with default disabled and an enabled override for `alice`. A fresh database starts empty; use the examples below to create your own flag.

## Try it

```sh
curl -i -X POST http://localhost:8000/flags \
  -H 'Content-Type: application/json' \
  -d '{"name":"new-checkout","description":"New checkout experience","default_enabled":false}'

curl 'http://localhost:8000/flags/new-checkout/evaluate?user_id=alice'
# enabled: false, source: default

curl -X PUT http://localhost:8000/flags/new-checkout/users/alice \
  -H 'Content-Type: application/json' -d '{"enabled":true}'

curl 'http://localhost:8000/flags/new-checkout/evaluate?user_id=alice'
# enabled: true, source: override

curl -X PUT http://localhost:8000/flags/new-checkout/default \
  -H 'Content-Type: application/json' -d '{"default_enabled":true}'
```

| Method and endpoint | Behavior |
|---|---|
| `POST /flags` | Create a flag, `201`; duplicate name, `409` |
| `GET /flags/{name}` | Read persisted configuration, `200` |
| `PUT /flags/{name}/default` | Set global fallback using `default_enabled`, `200` |
| `PUT /flags/{name}/users/{user_id}` | Create or replace override using `enabled`, `200` |
| `GET /flags/{name}/evaluate?user_id=...` | Return flag name, user ID, enabled state, and decision source |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | Database and application table availability |

Missing flags return `404`; invalid inputs return `422`. Booleans must be JSON `true` or `false`, not strings or integers. Unknown body fields are rejected. Names are case-sensitive, 1–100 ASCII letters/digits/underscores/hyphens, starting with a letter or digit. User IDs are opaque and case-sensitive, 1–128 characters, with letters/digits and `_.@:-`, starting with a letter or digit. Descriptions default to empty, allow at most 1,000 characters, and reject NUL.

Setting a default or override repeatedly is idempotent. Concurrent writes use PostgreSQL transactions and override upserts; the last database update wins. Flag creation is unique by name. User IDs do not imply accounts in this service.

## Architecture and consistency

```mermaid
flowchart TD
    Caller[Application or operator] --> API[FastAPI validation and routing]
    API -->|evaluate| Cache{In-process evaluation cache}
    Cache -->|hit| Answer[Enabled state and decision source]
    Cache -->|miss| Read[Single SQL query: default plus user override]
    Read --> DB[(PostgreSQL)]
    DB --> Decide[Override if present, otherwise default]
    Decide --> Fill[Cache result only if generation is unchanged]
    Fill --> Answer
    API -->|create or set state| Write[Database transaction]
    Write --> DB
    Write -->|after successful commit| Clear[Increment cache generation and clear cache]
    Clear --> Success[Success response]
    Answer --> Caller
    Success --> Caller
```

The cache stores up to 1,024 `(flag, user)` evaluations, evicts the least recently used entry, and expires entries after five seconds. False values are cached correctly. Writes clear the cache after commit and before returning success. A generation counter prevents an older in-flight read from refilling it after invalidation. Broad invalidation trades hit rate for simplicity. Database I/O runs outside the cache lock.

Run **one API worker and one instance**. Requests started after a successful write response see the new state. Reads overlapping a write may see the prior committed state. Other processes or direct SQL changes are visible only after expiration, so they are outside the immediate-invalidation guarantee. Restarting the API loses only cached copies, not configurations.

Database connection failures and timeouts return `503` with a generic error and `Retry-After`. A still-valid cached evaluation can be served during a database outage; a cache miss requires PostgreSQL. There is no fabricated enabled/disabled fallback. Callers must choose how their application behaves if evaluation fails.

## Local development and tests

Python 3.9+ is supported; Docker and CI use Python 3.12. Set up `.env` as above, then:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d --wait db
alembic upgrade head
uvicorn app.main:create_app --factory --workers 1
```

Configuration is read from environment variables or `.env`:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Required PostgreSQL URL; accepts `postgresql://`, `postgres://`, or `postgresql+psycopg://`; preserves TLS parameters |
| `POSTGRES_PASSWORD` | Compose database password; choose URL-safe alphanumeric text |
| `CACHE_MAX_ENTRIES` | Default `1024`, allowed `1–100000` |
| `CACHE_TTL_SECONDS` | Default `5`, greater than zero and at most `60` |
| `TEST_DATABASE_URL` | Explicit PostgreSQL URL for integration tests |
| `API_KEY` | Optional local API key, at least 32 characters; required for cloud deployment |
| `REQUIRE_API_KEY` | Set `true` in the cloud to reject startup without a key; default `false` for local use |

Use a separate test database:

```sh
docker compose exec db createdb -U flags flags_test
# Use the same local password chosen in .env; do not commit it.
export TEST_DATABASE_URL='postgresql+psycopg://flags:YOUR_LOCAL_PASSWORD@localhost:5433/flags_test'
pytest -q
ruff check .
ruff format --check .
alembic check
```

`pytest -q -m 'not integration'` runs cache unit tests without PostgreSQL. Without `TEST_DATABASE_URL`, integration tests are explicitly skipped. With it set, database errors fail the suite. Integration tests apply real migrations and use unique flag names, cleaning up only their own records. They check persistence across fresh app instances, both override values, updates, cache hits avoiding SQL, invalidation races, concurrent upserts, validation, and failure responses.

GitHub Actions installs dependencies, migrates PostgreSQL, checks schema drift, runs formatting/lint and the full test suite, and builds the Docker image. The repository is [JingzhiZhang520/feature-flag-api](https://github.com/JingzhiZhang520/feature-flag-api). Pushes and pull requests trigger the workflow; hosted verification status is recorded in `project-plan.md`.

## Scope and limitations

Flag endpoints support a shared API key. User accounts, granular authorization, rate limiting, and backup operations are not implemented. There is no UI, user registration, override deletion, audit history, percentage rollout, or flag listing.

Redis remains deferred. Moving to Redis would support a shared cache, but still needs coordinated invalidation and outage handling. Dependencies use bounded version ranges rather than a full lockfile. Production rollout would also require workload measurement and operational configuration.

## DigitalOcean demo deployment

Deployment configuration is in `.do/app.yaml`; live deployment status is recorded in `project-plan.md`. It specifies a single 512 MiB API instance and a PostgreSQL 16 development database, with a base cost of approximately $12/month before additional usage/tax. A development database is intended for demonstrations, not production use.

[Configure this app on DigitalOcean](https://cloud.digitalocean.com/apps/new?repo=https://github.com/JingzhiZhang520/feature-flag-api/tree/main) uses `.do/deploy.template.yaml`, the same spec wrapped for the public-repository deployment flow. Select the intended team and supply the key before deploying.

Deploy the public repository after GitHub Actions passes. Use the Dockerfile, port 8000, run command `sh deploy/start.sh`, and readiness path `/health/ready`. The startup command applies migrations before starting one worker. The app spec binds `DATABASE_URL` to `${db.DATABASE_URL}` and enables `REQUIRE_API_KEY=true`.

Before creating the app, add a randomly generated `API_KEY` of at least 32 characters as an **encrypted runtime environment variable**. The template intentionally contains no key, and the app will refuse to start without one. Keep keys out of Git, build arguments, URLs, and logs. App Platform provides the public HTTPS endpoint; use HTTPS when sending the key.

In `/docs`, click **Authorize** and supply the key. For curl, supply an `X-API-Key` header from a local environment variable. Missing or incorrect keys return `401` on every flag endpoint, including cached evaluations. `/health/live`, `/health/ready`, and `/docs` remain public. Configure a new key and redeploy to rotate it; this single-key demo does not provide a grace period for the old key.

Keep one instance and worker. During deployment, old and new instances may overlap briefly; cross-instance cache freshness is bounded by the five-second TTL. PostgreSQL data survives API redeployment. Deleting the app and its development database can destroy the stored flags; export needed data first. Billing continues while resources exist.

The preserved assignment is in `requirements.md`; approved decisions and implementation assumptions are in `decisions.md`; verification evidence is tracked in `project-plan.md`.
