import hashlib
import hmac
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
import httpx
from loguru import logger

from backend.worker import run_pipeline, run_pre_merge_review

load_dotenv()

app = FastAPI(title="MergeFlow AI")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
GITHUB_API_VERSION = "2022-11-28"
PRE_MERGE_REVIEW_ACTIONS = {"opened", "synchronize", "reopened"}


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


def extract_mergeflow_labels(labels: list[dict[str, Any]]) -> list[str]:
    return [
        label.get("name", "")
        for label in labels
        if label.get("name", "").startswith("mergeflow:")
    ]


def should_run_pre_merge_review(action: str | None, payload: dict[str, Any]) -> bool:
    if action in PRE_MERGE_REVIEW_ACTIONS:
        return True

    if action == "edited":
        return _pull_request_body_changed(payload)

    return False


def _pull_request_body_changed(payload: dict[str, Any]) -> bool:
    changes = payload.get("changes", {})
    body_change = changes.get("body")
    if not isinstance(body_change, dict):
        return False

    previous_body = body_change.get("from")
    current_body = payload.get("pull_request", {}).get("body")
    return previous_body != current_body


def enqueue_post_merge_job(payload: dict[str, Any], mergeflow_labels: list[str]) -> None:
    pull_request = payload["pull_request"]
    repository = payload.get("repository", {})
    head = pull_request.get("head", {})
    author = pull_request.get("user", {})

    repo_name = repository.get("full_name", "")
    pr_number = pull_request.get("number")
    pr_title = pull_request.get("title", "")
    pr_body = pull_request.get("body")
    branch_name = head.get("ref", "")
    diff_url = pull_request.get("diff_url", "")
    author_login = author.get("login", "")

    logger.info(
        "Enqueuing post-merge pipeline job repo={repo} pr_number={pr_number} labels={labels}",
        repo=repo_name,
        pr_number=pr_number,
        labels=mergeflow_labels,
    )
    run_pipeline.delay(
        repo_name,
        pr_number,
        pr_title,
        pr_body,
        branch_name,
        mergeflow_labels,
        diff_url,
        author_login,
    )


async def fetch_pr_diff(diff_url: str) -> str:
    if not diff_url:
        raise HTTPException(status_code=400, detail="Pull request diff URL is missing")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(diff_url, headers=github_diff_headers())
        response.raise_for_status()
        return response.text


def github_diff_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


async def enqueue_pre_merge_review(payload: dict[str, Any], mergeflow_labels: list[str]) -> bool:
    pull_request = payload["pull_request"]
    repository = payload.get("repository", {})

    repo_name = repository.get("full_name", "")
    pr_number = pull_request.get("number")
    diff_url = pull_request.get("diff_url", "")

    logger.info(
        "Fetching diff for pre-merge self review repo={repo} pr_number={pr_number} labels={labels}",
        repo=repo_name,
        pr_number=pr_number,
        labels=mergeflow_labels,
    )
    diff_text = await fetch_pr_diff(diff_url)
    if not diff_text.strip():
        logger.info(
            "Skipping pre-merge self review because PR diff is empty repo={repo} pr_number={pr_number}",
            repo=repo_name,
            pr_number=pr_number,
        )
        return False

    logger.info(
        "Enqueuing pre-merge self review job repo={repo} pr_number={pr_number} labels={labels}",
        repo=repo_name,
        pr_number=pr_number,
        labels=mergeflow_labels,
    )
    run_pre_merge_review.delay(repo_name, pr_number, diff_text)
    return True


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}

print("headers:", dict(request.headers))
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

    mergeflow_labels = extract_mergeflow_labels(pull_request.get("labels", []))

    if should_run_pre_merge_review(action, payload):
        logger.info(
            "Accepted pre-merge self review webhook repo={repo} pr_number={pr_number} action={action} labels={labels}",
            repo=repository.get("full_name"),
            pr_number=pr_number,
            action=action,
            labels=mergeflow_labels,
        )
        enqueued = await enqueue_pre_merge_review(payload, mergeflow_labels)
        return {"status": "accepted" if enqueued else "ignored"}

    if action != "closed" or pull_request.get("merged") is not True:
        logger.info(
            "Ignoring pull request event because it is not a merged PR action={action} merged={merged}",
            action=action,
            merged=pull_request.get("merged"),
        )
        return {"status": "ignored"}

    if not mergeflow_labels:
        logger.info("Ignoring merged PR without mergeflow labels pr_number={pr_number}", pr_number=pr_number)
        return {"status": "ignored"}

    logger.info(
        "Accepted MergeFlow post-merge webhook repo={repo} pr_number={pr_number} labels={labels}",
        repo=repository.get("full_name"),
        pr_number=pr_number,
        labels=mergeflow_labels,
    )
    enqueue_post_merge_job(payload, mergeflow_labels)

    return {"status": "accepted"}
