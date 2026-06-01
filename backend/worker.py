import os
import re
import time
from collections.abc import Callable
from typing import Any

from celery import Celery
from dotenv import load_dotenv
import httpx
from loguru import logger

from backend.classifier import diff_classifier
from backend.features import env_detector, issue_mover, self_reviewer

load_dotenv()

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
GITHUB_API_VERSION = "2022-11-28"

celery_app = Celery(
    "mergeflow",
    broker=redis_url,
    backend=redis_url,
)


@celery_app.task(name="run_pipeline")
def run_pipeline(
    repo_name: str,
    pr_number: int,
    pr_title: str,
    pr_body: str | None,
    branch_name: str,
    labels: list[str],
    diff_url: str,
    author: str,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    results: dict[str, Any] = {
        "status": "completed",
        "repo_name": repo_name,
        "pr_number": pr_number,
        "classification": None,
        "issue_number": None,
        "env_vars": [],
        "errors": {},
    }

    logger.info(
        "Starting pipeline repo_name={repo_name} pr_number={pr_number} pr_title={pr_title} "
        "branch_name={branch_name} labels={labels} diff_url={diff_url} author={author}",
        repo_name=repo_name,
        pr_number=pr_number,
        pr_title=pr_title,
        branch_name=branch_name,
        labels=labels,
        diff_url=diff_url,
        author=author,
    )

    diff_text = _run_pipeline_step(
        "fetch_diff",
        lambda: _fetch_pr_diff(diff_url),
        results,
        default="",
    )
    changed_files = _extract_changed_files(diff_text)

    classification = _run_pipeline_step(
        "classify_diff",
        lambda: diff_classifier.classify_diff(diff_text, changed_files),
        results,
    )
    results["classification"] = classification

    issue_number = _run_pipeline_step(
        "move_issue_to_done",
        lambda: issue_mover.move_issue_to_done(repo_name, pr_title, pr_body, branch_name),
        results,
    )
    results["issue_number"] = issue_number

    env_vars = _run_pipeline_step(
        "detect_new_env_vars",
        lambda: env_detector.detect_new_env_vars(diff_text, repo_name, pr_number),
        results,
        default=[],
    )
    results["env_vars"] = env_vars

    elapsed_seconds = time.perf_counter() - started_at
    results["elapsed_seconds"] = round(elapsed_seconds, 3)

    logger.info(
        "Completed pipeline repo_name={repo_name} pr_number={pr_number} elapsed_seconds={elapsed_seconds} "
        "classification={classification} issue_number={issue_number} env_var_count={env_var_count} error_count={error_count}",
        repo_name=repo_name,
        pr_number=pr_number,
        elapsed_seconds=results["elapsed_seconds"],
        classification=results["classification"],
        issue_number=results["issue_number"],
        env_var_count=len(results["env_vars"]),
        error_count=len(results["errors"]),
    )

    return results


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


def _run_pipeline_step(
    step_name: str,
    step: Callable[[], Any],
    results: dict[str, Any],
    default: Any = None,
) -> Any:
    started_at = time.perf_counter()

    try:
        result = step()
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        logger.info(
            "Completed pipeline step step={step} elapsed_seconds={elapsed_seconds}",
            step=step_name,
            elapsed_seconds=elapsed_seconds,
        )
        return result
    except Exception as error:
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        logger.exception(
            "Pipeline step failed step={step} elapsed_seconds={elapsed_seconds} error={error}",
            step=step_name,
            elapsed_seconds=elapsed_seconds,
            error=str(error),
        )
        results["errors"][step_name] = str(error)
        return default


def _fetch_pr_diff(diff_url: str) -> str:
    response = httpx.get(
        diff_url,
        headers=_github_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def _extract_changed_files(diff_text: str) -> list[str]:
    changed_files: list[str] = []
    seen_files: set[str] = set()

    for match in re.finditer(r"^diff --git a/.+ b/(?P<file_path>.+)$", diff_text, re.MULTILINE):
        file_path = match.group("file_path")
        if file_path not in seen_files:
            seen_files.add(file_path)
            changed_files.append(file_path)

    return changed_files


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers
