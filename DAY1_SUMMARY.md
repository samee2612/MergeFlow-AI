# Day 1 Summary

This document explains the Day 1 foundation for MergeFlow AI. It is written for someone opening the repo for the first time.

## What Day 1 Built

Day 1 created the backend foundation for receiving GitHub pull request webhooks and handing accepted post-merge events to a Celery worker through Redis.

The working path is:

1. GitHub sends a pull request webhook to FastAPI.
2. FastAPI validates the GitHub webhook signature.
3. FastAPI checks that the event is a merged pull request.
4. FastAPI checks that the PR has a label starting with `mergeflow:`.
5. FastAPI extracts PR metadata.
6. FastAPI enqueues a Celery task.
7. The Celery worker receives the task and logs the parameters.

Actual pipeline steps will be added after this foundation.

## Files Created

### Root Files

`Design.md`

Product design document for MergeFlow AI. It defines the problem, feature set, architecture, tech stack, folder structure, timeline, and deployment approach.

`README.md`

Initial project README with a short description of MergeFlow AI.

`requirements.txt`

Python dependencies for the backend, worker, integrations, RAG, graph computation, and email support.

Packages included:

- `fastapi`
- `uvicorn`
- `celery`
- `redis`
- `python-dotenv`
- `loguru`
- `httpx`
- `google-generativeai`
- `chromadb`
- `sentence-transformers`
- `networkx`
- `sendgrid`

`.env.example`

Template for required configuration values. It includes backend settings, GitHub credentials, Gemini settings, Redis/Celery URLs, Notion settings, SendGrid settings, ChromaDB settings, and the frontend backend URL.

`docker-compose.yml`

Defines three services:

- `api`: FastAPI app served by Uvicorn on port `8000`
- `worker`: Celery worker that consumes pipeline tasks
- `redis`: Redis broker/result backend for Celery

`Dockerfile`

Builds the Python backend image from `python:3.11-slim`, installs `requirements.txt`, and copies the project into `/app`.

This was added so Docker installs dependencies during image build instead of reinstalling packages every time `docker compose up` runs.

`DAY1_SUMMARY.md`

This summary file.

### Backend Files

`backend/__init__.py`

Marks `backend` as a Python package so imports like `backend.worker` work reliably.

`backend/main.py`

FastAPI application. It contains the health endpoint, GitHub webhook endpoint, signature validation, PR filtering, MergeFlow label detection, PR metadata extraction, and Celery task enqueueing.

`backend/worker.py`

Celery worker entry point. It creates the Celery app connected to Redis and defines the `run_pipeline` task.

`backend/classifier/diff_classifier.py`

Placeholder for future diff classification logic. This will classify PRs as API, frontend, database, infra/config, or mixed.

`backend/features/issue_mover.py`

Placeholder for moving linked GitHub issues to Done after a qualifying PR is merged.

`backend/features/qa_generator.py`

Placeholder for generating QA artifacts such as Postman collections, Playwright scaffolds, and markdown test plans.

`backend/features/swagger_generator.py`

Placeholder for generating OpenAPI specs and Swagger UI documentation.

`backend/features/notion_updater.py`

Placeholder for creating or updating Notion pages with API docs, QA plans, release logs, and feature summaries.

`backend/features/changelog_updater.py`

Placeholder for appending AI-generated release entries to `CHANGELOG.md`.

`backend/features/email_sender.py`

Placeholder for sending post-merge summary emails through SendGrid.

`backend/features/env_detector.py`

Placeholder for detecting new environment variables in PR diffs and updating `.env.example`.

`backend/features/self_reviewer.py`

Placeholder for pre-merge review comments that flag missing env vars, hardcoded values, TODOs, and missing tests.

`backend/features/graph_builder.py`

Placeholder for building dependency graphs from changed files using NetworkX.

`backend/mcp_servers/github_mcp.py`

Placeholder for future GitHub MCP tools such as issue movement, PR comments, file commits, and env example updates.

`backend/mcp_servers/notion_mcp.py`

Placeholder for future Notion MCP tools such as page creation, page lookup, and page appends.

`backend/mcp_servers/sendgrid_mcp.py`

Placeholder for future SendGrid MCP email tools.

`backend/mcp_servers/chromadb_mcp.py`

Placeholder for future ChromaDB MCP tools used by the RAG layer.

`backend/rag/embedder.py`

Placeholder for embedding PR context with `sentence-transformers`.

`backend/rag/retriever.py`

Placeholder for retrieving similar past PRs from ChromaDB.

`backend/websocket/broadcaster.py`

Placeholder for broadcasting pipeline status updates to the dashboard over WebSockets.

### Frontend Files

`frontend/src/components/PipelineRun.tsx`

Placeholder React component for showing one pipeline run in the dashboard.

`frontend/src/components/DependencyGraph.tsx`

Placeholder React component for showing the dependency graph with React Flow later.

`frontend/src/components/ArtifactLinks.tsx`

Placeholder React component for showing generated artifact links such as QA docs, Swagger UI, Notion pages, and Postman files.

`frontend/src/pages/Dashboard.tsx`

Placeholder React page for the main dashboard.

`frontend/src/pages/Settings.tsx`

Placeholder React page for repository and integration configuration.

`frontend/src/hooks/useWebSocket.ts`

Placeholder React hook for connecting the dashboard to backend WebSocket updates.

### Local Runtime Files

`.venv/`

Local Python virtual environment created during testing because Docker Desktop was not responding correctly. This is a development artifact, not application source code.

## Functions and Endpoints Written

### `backend/main.py`

`validate_github_signature(payload_body, signature_header)`

Validates that a webhook really came from GitHub. It reads `GITHUB_WEBHOOK_SECRET`, computes an HMAC SHA-256 signature from the raw request body, and compares it to the `X-Hub-Signature-256` header. If the secret is missing, the request fails with `500`. If the signature is missing or wrong, the request fails with `401`.

`extract_mergeflow_labels(labels)`

Receives the PR labels from GitHub and returns only labels whose names start with `mergeflow:`. Examples include `mergeflow: full`, `mergeflow: qa-only`, `mergeflow: docs-only`, and `mergeflow: notify`.

`enqueue_post_merge_job(payload, mergeflow_labels)`

Extracts the fields the worker needs from the webhook payload:

- repository full name
- PR number
- PR title
- PR body
- source branch name
- MergeFlow labels
- diff URL
- author login

It then calls `run_pipeline.delay(...)` to enqueue the Celery task.

`GET /health`

Simple health check endpoint. Returns `{"status": "ok"}` when FastAPI is running.

`POST /webhook`

Main GitHub webhook endpoint. It validates the signature, logs the event, ignores unsupported events, ignores PRs that were not merged, ignores merged PRs without a `mergeflow:` label, and enqueues accepted merged PRs for the worker.

### `backend/worker.py`

`celery_app`

Celery application configured to use Redis as both the broker and result backend. It reads `REDIS_URL`, defaulting to `redis://redis:6379/0` for Docker.

`run_pipeline(...)`

Celery task that accepts PR metadata from the webhook:

- `repo_name`
- `pr_number`
- `pr_title`
- `pr_body`
- `branch_name`
- `labels`
- `diff_url`
- `author`

For now, it logs all received values and returns `{"status": "logged"}`. Real pipeline steps will be added next.

### Frontend Placeholders

`PipelineRun()`

Placeholder component for rendering one pipeline run later.

`DependencyGraph()`

Placeholder component for rendering a dependency graph later.

`ArtifactLinks()`

Placeholder component for rendering links to generated artifacts later.

`Dashboard()`

Placeholder page for the main dashboard later.

`Settings()`

Placeholder page for integration settings later.

`useWebSocket()`

Placeholder hook for WebSocket status updates later.

## Complete Webhook to Celery Flow

1. A GitHub pull request webhook hits `POST /webhook`.
2. FastAPI reads the raw request body.
3. `validate_github_signature` computes the expected `sha256=` HMAC signature using `GITHUB_WEBHOOK_SECRET`.
4. FastAPI compares the expected signature with the `X-Hub-Signature-256` header.
5. If the signature is missing or invalid, the request is rejected.
6. FastAPI parses the JSON payload.
7. FastAPI checks `X-GitHub-Event`.
8. If the event is not `pull_request`, the request is logged and ignored.
9. FastAPI checks `action`.
10. If `action` is not `closed`, the request is logged and ignored.
11. FastAPI checks `pull_request.merged`.
12. If `merged` is not `true`, the request is logged and ignored.
13. `extract_mergeflow_labels` checks the PR labels for any label starting with `mergeflow:`.
14. If no MergeFlow label exists, the request is logged and ignored.
15. FastAPI logs that the merged PR was accepted.
16. `enqueue_post_merge_job` extracts PR metadata from the payload.
17. `run_pipeline.delay(...)` sends a task to Redis.
18. FastAPI immediately returns `{"status": "accepted"}` with HTTP 200.
19. The Celery worker receives the `run_pipeline` task from Redis.
20. `run_pipeline` logs all received parameters.
21. The task returns `{"status": "logged"}`.

## Environment Variables

`APP_ENV`

Names the runtime environment. Currently defaults to `local`.

`BACKEND_HOST`

Host the backend should bind to. In local and Docker development this is `0.0.0.0`.

`BACKEND_PORT`

Port the backend should listen on. Day 1 uses `8000`.

`GITHUB_PERSONAL_ACCESS_TOKEN`

GitHub token for future GitHub API operations such as comments, issue movement, and file commits.

`GITHUB_WEBHOOK_SECRET`

Shared secret used to verify GitHub webhook signatures. This prevents random callers from triggering the webhook endpoint.

`GITHUB_REPO_URL`

Repository URL for the connected GitHub repo. This will be used by setup/config flows later.

`GEMINI_API_KEY`

API key for Gemini. This will be used by AI classification, QA generation, documentation, and summaries.

`GEMINI_MODEL`

Gemini model name. The current implementation uses `gemini-2.5-pro`.

`REDIS_URL`

Redis connection URL used by Celery. In Docker this is `redis://redis:6379/0`; in local non-Docker testing this was overridden to `redis://localhost:6379/0`.

`CELERY_BROKER_URL`

Celery broker URL. It points to Redis and is available for explicit Celery configuration later.

`CELERY_RESULT_BACKEND`

Celery result backend URL. It points to Redis and stores task results.

`NOTION_API_KEY`

Notion integration API key for future Notion workspace updates.

`NOTION_WORKSPACE_ID`

Notion workspace identifier for future workspace-level configuration.

`NOTION_DATABASE_ID`

Notion database identifier for finding or creating MergeFlow pages.

`SENDGRID_API_KEY`

SendGrid API key for future post-merge summary emails.

`SENDGRID_FROM_EMAIL`

Email address that future SendGrid summaries will be sent from.

`SENDGRID_RECIPIENT_EMAILS`

Comma-separated list of recipients for future post-merge summary emails.

`CHROMA_PERSIST_DIRECTORY`

Directory where ChromaDB will persist vector data for RAG.

`EMBEDDING_MODEL`

Sentence-transformers model used to embed PR context. The design doc uses `all-MiniLM-L6-v2`.

`VITE_BACKEND_URL`

Frontend environment variable pointing the React app to the backend API.

## Design Decisions

### GitHub Labels Are the Trigger

The webhook only accepts merged PRs that have at least one label starting with `mergeflow:`. This follows the design doc and avoids running automation on every PR merge by accident.

### Signature Validation Happens Before JSON Parsing

The webhook validates the raw request body before trusting the payload. This is the correct order because GitHub signs the raw body, not the parsed JSON.

### Ignored Events Still Return 200

Unsupported events, unmerged PRs, and merged PRs without MergeFlow labels return `{"status": "ignored"}` with HTTP 200. This prevents GitHub from retrying webhooks that MergeFlow intentionally chose not to process.

### Accepted Webhooks Return Immediately

The endpoint enqueues work and returns `{"status": "accepted"}` right away. This matches the design requirement that GitHub webhooks should not wait for the full pipeline.

### Redis + Celery Are Used for Async Work

Celery gives MergeFlow a clear background processing boundary. FastAPI handles the webhook quickly, while the worker handles the longer-running pipeline.

### Loguru Is Used Everywhere

Day 1 uses Loguru for clear logs across FastAPI and Celery. This makes local debugging straightforward before adding more complex observability.

### Dockerfile Was Added After the Initial Compose File

The first Compose setup installed dependencies on every container start. That made startup slow and hard to debug because packages like `chromadb` and `sentence-transformers` are heavy. The Dockerfile moves dependency installation into image build time.

### Local Non-Docker Run Was Used for Testing

Docker Desktop was present but its daemon API was hanging. To keep Day 1 moving, Redis was installed locally with Homebrew, a Python virtual environment was created, and FastAPI/Celery were run directly. This confirmed the webhook-to-worker path works independently of Docker Desktop.

### Placeholder Files Match the Product Architecture

Many files are placeholders today because Section 8 of the design doc defines the final architecture. Creating them now makes the project structure visible and gives future work obvious homes without mixing unrelated feature code into `main.py` or `worker.py`.

## Verified Locally

The local non-Docker path was tested successfully:

- `GET /health` returned `{"status":"ok"}`
- A signed merged-PR webhook returned `{"status":"accepted"}`
- FastAPI logged receipt, acceptance, and queueing of the webhook
- Celery received `run_pipeline`, logged all PR metadata, and completed the task
