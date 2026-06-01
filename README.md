# MergeFlow AI

MergeFlow AI is an AI-powered post-merge automation agent for GitHub pull requests.

It listens to GitHub webhook events, runs a Celery-based automation pipeline, and helps teams handle repetitive post-merge work such as pull request review, diff classification, issue updates, environment variable detection, and generated documentation tasks.

## What It Does

- Listens for GitHub pull request webhook events
- Runs pre-merge AI self-review when a PR is opened
- Runs post-merge automation when a PR is merged
- Classifies changed code as API, frontend, database, infrastructure, or mixed
- Moves linked GitHub issues to done by closing completed issues
- Detects new environment variables and updates `.env.example`
- Provides foundation for changelog, Swagger, Notion, SendGrid, RAG, and dependency graph features

## Tech Stack

- Python
- FastAPI
- Celery
- Redis
- Docker / Docker Compose
- GitHub API
- Gemini API
- ChromaDB-ready RAG modules

## Project Structure

```text
MergeFlow-AI/
├── backend/
│   ├── main.py
│   ├── worker.py
│   ├── classifier/
│   ├── features/
│   ├── mcp_servers/
│   ├── rag/
│   └── websocket/
├── frontend/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
