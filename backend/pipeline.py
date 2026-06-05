from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from backend.classifier.diff_classifier import BackendDiffClassification, classify_backend_diff
from backend.generators.api_spec_generator import generate_api_spec_and_test_cases
from backend.github_client import fetch_pull_request_diff


BACKEND_PATH_MARKERS = (
    "api/",
    "routes/",
    "controllers/",
    "services/",
    "models/",
    "schemas/",
    "migrations/",
    "backend/",
)


@dataclass(frozen=True)
class PullRequestContext:
    repository: str
    pr_number: int | None
    title: str
    merged_at: str | None
    author: str
    changed_files: list[str]
    base_branch: str = ""
    head_branch: str = ""
    default_branch: str = ""


async def run_post_merge_pipeline(pr_context: PullRequestContext) -> bool:
    """Entry point for merged backend PR processing.

    Future artifact generators should hang off this function after the PR has
    been accepted as backend-relevant.
    """
    logger.info(
        "Post-merge pipeline received repo={repo} pr_number={pr_number} title={title} "
        "merged_at={merged_at} author={author} changed_files={changed_files}",
        repo=pr_context.repository,
        pr_number=pr_context.pr_number,
        title=pr_context.title,
        merged_at=pr_context.merged_at,
        author=pr_context.author,
        changed_files=pr_context.changed_files,
    )

    if is_backend_relevant_pr(pr_context.changed_files):
        logger.info("Backend PR accepted for MergeFlow")
        await classify_accepted_backend_pr(pr_context)
        return True

    logger.info("PR ignored - not backend related")
    return False


async def classify_accepted_backend_pr(pr_context: PullRequestContext) -> BackendDiffClassification:
    if pr_context.pr_number is None:
        logger.warning("Skipping PR classification because PR number is missing")
        return BackendDiffClassification(
            change_types=["Unknown"],
            summary="Unable to classify backend change.",
        )

    diff_text = await fetch_pull_request_diff(pr_context.repository, pr_context.pr_number)
    classification = classify_backend_diff(diff_text, pr_context.changed_files)
    log_pr_classification(classification)
    await generate_api_spec_and_test_cases(pr_context, classification, diff_text)
    return classification


def log_pr_classification(classification: BackendDiffClassification) -> None:
    change_types = "\n".join(f"* {change_type}" for change_type in classification.change_types)
    logger.info(
        "PR Classification:\n\n{change_types}\n\nSummary:\n{summary}",
        change_types=change_types,
        summary=classification.summary,
    )


def is_backend_relevant_pr(changed_files: list[str]) -> bool:
    return any(_is_backend_path(file_path) for file_path in changed_files)


def _is_backend_path(file_path: str) -> bool:
    normalized_path = file_path.replace("\\", "/").lstrip("/").lower()
    return any(marker in normalized_path for marker in BACKEND_PATH_MARKERS)
