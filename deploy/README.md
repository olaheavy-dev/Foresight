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

Live since 12 Oct 2026 at https://foresight.olaheavy.dev. `/healthz` reports the deployed commit
(baked into the image as `FORESIGHT_BUILD_SHA`; no runtime setting can override it) and returns
503 if the database is unreachable.

## Images are public, and checked before publishing

Both GHCR packages are **public** so the server pulls them without credentials. This is safe
because the repository is already public and images contain code only:
- runtime secrets live only in the server's `.env` and are passed at runtime, never at build;
- `frontend/.dockerignore` and the root `.dockerignore` keep `.env*`, keys and statement files out;
- `tools/check_image_secrets.py` scans every candidate image (secret-like variable names and values,
  `.env` files, private keys, statement files) in CI and again in **Publish images**, which pushes
  exactly the scanned image or nothing.

## Checking a deploy by hand

```bash
curl -s https://foresight.olaheavy.dev/healthz          # status, deployed sha, database
gh workflow run "Post-deploy smoke" --ref main          # Playwright smoke against the live site
```

## Server-side files

- `docker-compose.prod.yml` (this folder): frontend on the Caddy network; backend and PostgreSQL
  on a private app network; no published ports.
- `.env` next to it, never committed. Use `.env.example` in the repo root as the template, with
  `DATABASE_URL=postgresql+psycopg://<user>:<password>@postgres:5432/<db>` (host `postgres`,
  not `localhost`).

Only demo workspaces are ever deployed. Real statements never go on the server.

## Operating the server

Server operations live in the platform's private operator wiki (its "Foresight Deployment" page):
first deploy, updating the server `.env` (for example adding the Mesh model IDs in Stage 2),
rotating the Postgres password, switching DNS to proxied mode, troubleshooting a failed health
check or a stuck auto-update, and decommissioning after the hackathon. They're kept there because
they involve server details that don't belong in this public repository.
