import asyncio
import os
import time
from typing import Any

from celery import Celery
from dotenv import load_dotenv
from loguru import logger

from backend.features import self_reviewer
from backend.pipeline import PullRequestContext, run_post_merge_pipeline

load_dotenv()

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "mergeflow",
    broker=redis_url,
    backend=redis_url,
)


@celery_app.task(name="run_post_merge_pipeline")
def run_post_merge_pipeline_task(pr_context_payload: dict[str, Any]) -> dict[str, Any]:
    started_at = time.perf_counter()
    pr_context = PullRequestContext(
        repository=pr_context_payload.get("repository", ""),
        pr_number=pr_context_payload.get("pr_number"),
        title=pr_context_payload.get("title", ""),
        merged_at=pr_context_payload.get("merged_at"),
        author=pr_context_payload.get("author", ""),
        changed_files=list(pr_context_payload.get("changed_files") or []),
        base_branch=pr_context_payload.get("base_branch", ""),
        head_branch=pr_context_payload.get("head_branch", ""),
        default_branch=pr_context_payload.get("default_branch", ""),
    )

    logger.info(
        "Worker picked up post-merge pipeline repo={repo} pr_number={pr_number}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
    )

    try:
        accepted = asyncio.run(run_post_merge_pipeline(pr_context))
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        status = "accepted" if accepted else "failed"
        logger.info(
            "Worker completed post-merge pipeline repo={repo} pr_number={pr_number} status={status} elapsed_seconds={elapsed_seconds}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            status=status,
            elapsed_seconds=elapsed_seconds,
        )
        return {
            "status": status,
            "repository": pr_context.repository,
            "pr_number": pr_context.pr_number,
            "elapsed_seconds": elapsed_seconds,
        }
    except Exception as error:
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        logger.exception(
            "Worker post-merge pipeline failed repo={repo} pr_number={pr_number} elapsed_seconds={elapsed_seconds} error={error}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            elapsed_seconds=elapsed_seconds,
            error=str(error),
        )
        return {
            "status": "failed",
            "repository": pr_context.repository,
            "pr_number": pr_context.pr_number,
            "elapsed_seconds": elapsed_seconds,
            "error": str(error),
        }


@celery_app.task(name="run_pre_merge_review")
def run_pre_merge_review(repo: str, pr_number: int, diff_text: str) -> dict[str, Any]:
    started_at = time.perf_counter()

    try:
        findings = self_reviewer.run_self_review(repo, pr_number, diff_text)
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        logger.info(
            "Completed pre-merge self review repo={repo} pr_number={pr_number} finding_count={finding_count} "
            "elapsed_seconds={elapsed_seconds}",
            repo=repo,
            pr_number=pr_number,
            finding_count=len(findings),
            elapsed_seconds=elapsed_seconds,
        )
        return {
            "status": "completed",
            "repo": repo,
            "pr_number": pr_number,
            "finding_count": len(findings),
            "elapsed_seconds": elapsed_seconds,
        }
    except Exception as error:
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        logger.exception(
            "Pre-merge self review failed repo={repo} pr_number={pr_number} elapsed_seconds={elapsed_seconds} error={error}",
            repo=repo,
            pr_number=pr_number,
            elapsed_seconds=elapsed_seconds,
            error=str(error),
        )
        return {
            "status": "failed",
            "repo": repo,
            "pr_number": pr_number,
            "error": str(error),
            "elapsed_seconds": elapsed_seconds,
        }
