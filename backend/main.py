import asyncio
import hashlib
import hmac
import os
from dataclasses import asdict
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.dashboard_runs import get_dashboard_run, list_dashboard_runs, list_dashboard_runs_for_service, list_dashboard_runs_for_team
from backend.github_client import fetch_pull_request_changed_files
from backend.organization import get_organization
from backend.pipeline import PullRequestContext, run_post_merge_pipeline
from backend.run_store import create_run
from backend.worker import run_post_merge_pipeline_task

load_dotenv()

app = FastAPI(title="MergeFlow AI")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",") if origin.strip()],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def validate_github_signature(payload_body: bytes, signature_header: str | None) -> None:
    if not GITHUB_WEBHOOK_SECRET:
        logger.error("GITHUB_WEBHOOK_SECRET is not configured")
        raise HTTPException(status_code=500, detail="Webhook secret is not configured")

    if not signature_header:
        logger.warning("Rejected webhook without X-Hub-Signature-256 header")
        raise HTTPException(status_code=401, detail="Missing signature")

    expected_signature = (
        "sha256="
        + hmac.new(
            GITHUB_WEBHOOK_SECRET.encode("utf-8"),
            payload_body,
            hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(expected_signature, signature_header):
        logger.warning("Rejected webhook with invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")


def build_pull_request_context(payload: dict[str, Any], changed_files: list[str]) -> PullRequestContext:
    pull_request = payload["pull_request"]
    repository = payload.get("repository", {})
    author = pull_request.get("user", {})
    base = pull_request.get("base", {})
    head = pull_request.get("head", {})

    return PullRequestContext(
        repository=repository.get("full_name", ""),
        pr_number=pull_request.get("number"),
        title=pull_request.get("title", ""),
        merged_at=pull_request.get("merged_at"),
        author=author.get("login", ""),
        changed_files=changed_files,
        base_branch=base.get("ref", ""),
        head_branch=head.get("ref", ""),
        default_branch=repository.get("default_branch", ""),
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/runs")
async def runs() -> list[dict[str, Any]]:
    return list_dashboard_runs()


@app.get("/organization")
async def organization() -> dict[str, Any]:
    return get_organization()


@app.get("/teams/{team_id}/runs")
async def team_runs(team_id: str) -> list[dict[str, Any]]:
    return list_dashboard_runs_for_team(team_id)


@app.get("/services/{service_id}/runs")
async def service_runs(service_id: str) -> list[dict[str, Any]]:
    return list_dashboard_runs_for_service(service_id)


@app.get("/runs/{run_id}")
async def run_detail(run_id: str) -> dict[str, Any]:
    run = get_dashboard_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


async def _process_merged_pr_webhook(payload: dict[str, Any], repo_name: str, pr_number: int) -> None:
    # Yield to let Uvicorn finish sending the HTTP 200 response to GitHub before starting processing
    await asyncio.sleep(0.05)
    try:
        changed_files = await fetch_pull_request_changed_files(repo_name, pr_number)
    except Exception as exc:
        logger.warning(
            "Failed fetching changed files from GitHub repo={repo} pr_number={pr_number} error={error}",
            repo=repo_name,
            pr_number=pr_number,
            error=exc,
        )
        changed_files = []

    pr_context = build_pull_request_context(payload, changed_files)
    # Immediately record the run so it displays on the dashboard without waiting for heavy processing
    create_run(pr_context)

    enqueued = False
    try:
        run_post_merge_pipeline_task.apply_async(args=[asdict(pr_context)], retry=False)
        enqueued = True
        logger.info(
            "Enqueued post-merge pipeline to Celery repo={repo} pr_number={pr_number}",
            repo=repo_name,
            pr_number=pr_number,
        )
    except Exception as exc:
        logger.warning(
            "Celery dispatch unavailable error={error}; running pipeline directly in background repo={repo} pr_number={pr_number}",
            error=exc,
            repo=repo_name,
            pr_number=pr_number,
        )

    if not enqueued:
        asyncio.create_task(run_post_merge_pipeline(pr_context))
        await asyncio.sleep(0)



@app.post("/webhook")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    payload_body = await request.body()
    validate_github_signature(payload_body, x_hub_signature_256)

    payload = await request.json()
    action = payload.get("action")
    pull_request = payload.get("pull_request", {})
    repository = payload.get("repository", {})
    pr_number = pull_request.get("number")

    logger.info(
        "Received GitHub webhook event={event} action={action} repo={repo} pr_number={pr_number}",
        event=x_github_event,
        action=action,
        repo=repository.get("full_name"),
        pr_number=pr_number,
    )

    if x_github_event != "pull_request":
        logger.info("Ignoring unsupported GitHub event={event}", event=x_github_event)
        return {"status": "ignored"}

    if action != "closed" or pull_request.get("merged") is not True:
        logger.info(
            "Ignoring pull request event because it is not a merged PR action={action} merged={merged}",
            action=action,
            merged=pull_request.get("merged"),
        )
        return {"status": "ignored"}

    repo_name = repository.get("full_name", "")
    if not repo_name or not isinstance(pr_number, int):
        logger.warning("Ignoring merged PR because repository or PR number is missing")
        return {"status": "ignored"}

    asyncio.create_task(_process_merged_pr_webhook(payload, repo_name, pr_number))
    return {"status": "accepted"}




if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port)
