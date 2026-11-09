# Railway Development Environment

**Status:** Planned; not yet deployed. This runbook is the intended setup. Update the status and verification log after the first successful deployment.

**Purpose:** end-to-end Telegram testing and engine timing on reliable disk and bandwidth. This environment is **not production-ready** and does not choose the production host (D-12).

Railway was selected because it runs long-lived polling and worker processes, uses the project Dockerfile with ffmpeg/FFprobe/Deno, supports a persistent worker volume, and has no serverless duration limit. Vercel cannot run this topology.

## Topology

| Service | Start command | Public | Volume | Replicas |
|---|---|---|---|---|
| `api` | `svdb-api` | yes, `/health/live` | — | 1 |
| `bot` | `svdb-bot` | no | — | 1 |
| `worker` | `svdb-worker` | no | `/app/storage` (10 GB) | 1 |
| `Postgres` | managed | private | — | — |
| `Redis` | managed | private | — | — |

One bot replica is mandatory: two pollers cause Telegram `getUpdates` conflicts. One worker replica keeps the ARQ cron jobs single-runner.

## Prerequisites

- Railway Hobby plan (paid, usage-based) and GitHub access to `bread0xf/SocialsVideoDownloaderBot`.
- Railway CLI: `curl -fsSL agents.railway.com | sh` (or `bash <(curl -fsSL https://railway.com/install.sh)`).
- A `dev` branch pushed to GitHub. Railway deploys from that branch.

## Create the project and resources

```bash
railway login
railway init --name socialsvideodownloaderbot-dev
railway add --database postgres --json
railway add --database redis --json
railway add --service api --json
railway add --service bot --json
railway add --service worker --json
railway service list --json
```

Confirm the exact `Postgres` and `Redis` service names; variable references are case-sensitive.

## Configure each app service

```bash
railway environment edit --service-config <svc> source.repo https://github.com/bread0xf/SocialsVideoDownloaderBot.git
railway environment edit --service-config <svc> source.branch dev
railway environment edit --service-config <svc> build.builder DOCKERFILE
railway environment edit --service-config <svc> build.watchPatterns '["backend/**","apps/**","migrations/**","alembic.ini","pyproject.toml","uv.lock","Dockerfile"]'
railway environment edit --service-config <svc> deploy.startCommand <svdb-api|svdb-bot|svdb-worker>
railway environment edit --service-config <svc> deploy.numReplicas 1
railway environment edit --service-config <svc> deploy.restartPolicyType ON_FAILURE
```

API only:

```bash
railway environment edit --service-config api deploy.preDeployCommand "alembic upgrade head"
railway environment edit --service-config api deploy.healthcheckPath /health/live
railway environment edit --service-config api deploy.healthcheckTimeout 300
```

Verify `preDeployCommand` syntax with `railway environment edit --help`. If the CLI rejects the string form, use the API start command `sh -c "alembic upgrade head && svdb-api"` instead; with one API replica it is idempotent.

Worker volume:

```bash
railway volume add --service worker --mount-path /app/storage
```

If the CLI does not support this, create and attach the volume in the dashboard at `/app/storage`.

## Environment variables

| Variable | api | bot | worker |
|---|---|---|---|
| `APP_ENV` | `development` | `development` | `development` |
| `LOG_JSON` | `true` | `true` | `true` |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | same | same |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | same | same |
| `TELEGRAM_BOT_TOKEN` | — | secret | secret |
| `TELEGRAM_POLLING` | — | `true` | — |
| `MEDIA_ROOT` | — | — | `/app/storage` |
| `MEDIA_CACHE_MAX_BYTES` | — | — | `8589934592` (8 GiB) |
| `WORKER_CONCURRENCY` | — | — | `1` |
| `RAILWAY_RUN_UID` | — | — | `0` |

```bash
railway variable set APP_ENV=development LOG_JSON=true \
  DATABASE_URL='${{Postgres.DATABASE_URL}}' REDIS_URL='${{Redis.REDIS_URL}}' --service api
```

Repeat for `bot` and `worker`, adding their extra keys. Single quotes are required around references. Set `TELEGRAM_BOT_TOKEN` directly in the Railway dashboard so the secret is never pasted into chat, logs or the repository.

Do not use `APP_ENV=production`: the settings model currently requires a Telegram token for every process, including the API.

## Deploy

Deploy the API first so the pre-deploy migration runs, then the bot and worker:

```bash
railway up --service api --detach -m "Railway API initial deploy"
railway deployment list --service api --json        # require SUCCESS
railway up --service bot --detach -m "Railway bot initial deploy"
railway up --service worker --detach -m "Railway worker initial deploy"
railway deployment list --service worker --json     # require SUCCESS
railway domain --service api --port 8000 --json
```

Do not report success until `railway deployment list` shows `SUCCESS` for each service.

## Verify

1. `railway logs --service api --lines 200 --json` — Alembic upgraded and the app started.
2. `curl -fsS https://<api-domain>/health/live` — 200.
3. `curl -fsS https://<api-domain>/health/ready` — 200 (PostgreSQL and Redis reachable).
4. `railway logs --service bot --lines 100 --json` — polling started; no `Conflict`.
5. `railway logs --service worker --lines 100 --json` — ARQ started; `outbox_dispatched` events.
6. Send a public video URL to the bot; confirm Telegram delivery and a worker `download_completed` event with `elapsed_ms`.
7. Send the same URL again; confirm `cache_hit=true` and a shorter `elapsed_ms`.
8. Check `/status` quota decrement, and that a failed download releases the reservation.

## Operate

- Push to `dev` to rebuild the app services; watch patterns limit unrelated deploys.
- Roll back from the dashboard's previous deployment, or `railway redeploy --service <svc>` for the latest.
- Migrations are forward-only; back up Railway Postgres before the first migration.
- Teardown is destructive and owner-only: delete services, volume and project from the dashboard.

## Security notes

- `RAILWAY_RUN_UID=0` runs the worker as root inside the container so it can write the root-owned volume. Development only; production should chown/drop privileges at startup or use object storage.
- Only the API has a public domain. Postgres and Redis stay on private networking.
- The bot token lives only in Railway variables. Never add it to the API service or to source.
- Railway logs are third-party; structured logging already avoids tokens, credentials and full sensitive URLs.

## Cost and limits

Railway bills usage on the Hobby plan. Three always-on app services plus managed Postgres, Redis and a 10 GB volume are a small but non-zero monthly cost. Shared CPU and network mean timings are indicative, not a clean benchmark. Cloud Bot API delivery remains capped at 48 MiB, so Premium 4K cannot be validated here.
