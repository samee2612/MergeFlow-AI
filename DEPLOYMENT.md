# MergeFlow Production Deployment

Deploy the validated post-merge flow: GitHub webhook -> Celery worker -> Notion + SendGrid, with the React dashboard reading shared run metadata from Redis.

## Architecture

- **Railway API service**: FastAPI webhook + dashboard REST API (`uvicorn backend.main:app`)
- **Railway Worker service**: Celery worker (`celery -A backend.worker.celery_app worker --loglevel=info`)
- **Railway Redis plugin**: shared broker, result backend, and run metadata store
- **Vercel frontend**: React dashboard (`frontend/`)

## Railway Backend + Worker

Create one Railway project with three services:

1. **Redis**
   - Add the Railway Redis plugin
   - Copy the generated `REDIS_URL`

2. **API**
   - Root directory: repository root
   - Start command:
     ```bash
     uvicorn backend.main:app --host 0.0.0.0 --port $PORT
     ```
   - Health check path: `/health`

3. **Worker**
   - Root directory: repository root
   - Start command:
     ```bash
     celery -A backend.worker.celery_app worker --loglevel=info
     ```

### Required environment variables (API + Worker)

```env
MERGEFLOW_RUNS_BACKEND=redis
REDIS_URL=<railway-redis-url>
CELERY_BROKER_URL=<railway-redis-url>
CELERY_RESULT_BACKEND=<railway-redis-url>

GITHUB_TOKEN=
GITHUB_WEBHOOK_SECRET=

GEMINI_API_KEY=
GEMINI_API_VERSION=v1beta
GEMINI_MODEL=gemini-2.5-flash-lite
GEMINI_FALLBACK_MODEL=gemini-2.5-flash

NOTION_API_KEY=
NOTION_ROOT_PAGE_ID=

SENDGRID_API_KEY=
SENDGRID_FROM_EMAIL=
SENDGRID_FROM_NAME=MergeFlow
SENDGRID_RECIPIENT_EMAILS=

CORS_ALLOW_ORIGINS=https://your-vercel-app.vercel.app,http://localhost:5173
```

## GitHub Webhook

In the monitored repository (for example `samee2612/order-service`):

1. Settings -> Webhooks -> Add webhook
2. Payload URL: `https://<railway-api-domain>/webhook`
3. Content type: `application/json`
4. Secret: same value as `GITHUB_WEBHOOK_SECRET`
5. Events: **Pull requests**

The webhook returns `{"status":"accepted"}` immediately after enqueueing the Celery job.

## Vercel Frontend

1. Import the GitHub repo into Vercel
2. Set root directory to `frontend`
3. Build command: `npm run build`
4. Output directory: `dist`
5. Environment variable:
   ```env
   VITE_BACKEND_URL=https://<railway-api-domain>
   ```

## Local Docker Compose

```bash
cp .env.example .env
# fill secrets in .env
docker compose up --build
```

Local defaults:

- API: `http://localhost:8000`
- Frontend dev server: `npm run dev` in `frontend/`
- Run metadata backend: filesystem (`MERGEFLOW_RUNS_BACKEND=filesystem`)

To test Redis locally, set:

```env
MERGEFLOW_RUNS_BACKEND=redis
REDIS_URL=redis://localhost:6379/0
```

## Post-Deploy Verification

1. Merge a backend PR in `samee2612/order-service`
2. Confirm worker logs:
   - `Worker picked up post-merge pipeline`
   - `Notion documentation updated`
   - `Email sent successfully`
3. Open the Vercel dashboard and verify:
   - run status is `SUCCESS`
   - Notion service page link works
   - Notion PR documentation link works
   - GitHub PR link works

## Notes

- OpenAPI, Postman, and markdown test plans are embedded in Notion; they are not committed to the target repository.
- MCP, RAG, WebSockets, React Flow, and CHANGELOG automation remain roadmap items and are not required for today's deployment.
