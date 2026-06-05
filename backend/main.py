import hashlib
import hmac
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from loguru import logger

from backend.github_client import fetch_pull_request_changed_files
from backend.pipeline import PullRequestContext, run_post_merge_pipeline

load_dotenv()

app = FastAPI(title="MergeFlow AI")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


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

    changed_files = await fetch_pull_request_changed_files(repo_name, pr_number)
    pr_context = build_pull_request_context(payload, changed_files)
    accepted = await run_post_merge_pipeline(pr_context)

    return {"status": "accepted" if accepted else "ignored"}
