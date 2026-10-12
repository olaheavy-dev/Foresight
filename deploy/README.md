# Deployment

Foresight runs on the owner's single-VPS platform (docs/05 §12). The platform's own configuration
lives in a separate private repository; nothing about the server is stored here.

## How a change goes live

1. A merge to `main` runs **CI** (`.github/workflows/ci.yml`): lint, types, Mesh-only contracts,
   unit and PostgreSQL integration tests, frontend build and tests, then Playwright journeys
   against the real Docker Compose stack.
2. Only if CI is green, **Publish images** pushes `ghcr.io/olaheavy-dev/foresight-backend` and
   `foresight-frontend` with tags `sha-<commit>` and `main`.
3. Watchtower on the server (scope `foresight-staging`) pulls the new `:main` images.
4. **Post-deploy smoke** waits until https://foresight.olaheavy.dev/healthz reports the new commit,
   then runs the Playwright smoke journey against the live site.

Rollback: pin both services in `docker-compose.prod.yml` to the last good `sha-<commit>` tag.

## Server-side files

- `docker-compose.prod.yml` (this folder): frontend on the Caddy network; backend and PostgreSQL
  on a private app network; no published ports.
- `.env` next to it, never committed. Use `.env.example` in the repo root as the template, with
  `DATABASE_URL=postgresql+psycopg://<user>:<password>@postgres:5432/<db>` (host `postgres`,
  not `localhost`).

Only demo workspaces are ever deployed. Real statements never go on the server.
