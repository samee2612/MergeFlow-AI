"""GitHub issue movement feature runner."""

from __future__ import annotations

import os
import re

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

PR_BODY_ISSUE_PATTERN = re.compile(r"\b(?:closes|fixes)\s+#(?P<issue_number>\d+)\b", re.IGNORECASE)
BRANCH_ISSUE_PATTERN = re.compile(r"^(?:feat|fix)/(?P<issue_number>\d+)(?:[-/].*)?$", re.IGNORECASE)
TITLE_ISSUE_PATTERN = re.compile(r"\[#(?P<issue_number>\d+)\]")


def move_issue_to_done(
    repo: str,
    pr_title: str,
    pr_body: str | None,
    branch_name: str,
) -> int | None:
    """Move the linked GitHub issue to Done and return its number when found."""
    issue_number = _extract_issue_number(pr_title, pr_body, branch_name)

    if issue_number is None:
        logger.info(
            "No linked GitHub issue found repo={repo} pr_title={pr_title} branch_name={branch_name}",
            repo=repo,
            pr_title=pr_title,
            branch_name=branch_name,
        )
        return None

    logger.info(
        "Moving linked GitHub issue to Done repo={repo} issue_number={issue_number}",
        repo=repo,
        issue_number=issue_number,
    )
    _close_issue_as_completed(repo, issue_number)

    logger.info(
        "Moved linked GitHub issue to Done repo={repo} issue_number={issue_number}",
        repo=repo,
        issue_number=issue_number,
    )
    return issue_number


def _extract_issue_number(pr_title: str, pr_body: str | None, branch_name: str) -> int | None:
    body_match = PR_BODY_ISSUE_PATTERN.search(pr_body or "")
    if body_match:
        return int(body_match.group("issue_number"))

    branch_match = BRANCH_ISSUE_PATTERN.search(branch_name)
    if branch_match:
        return int(branch_match.group("issue_number"))

    title_match = TITLE_ISSUE_PATTERN.search(pr_title)
    if title_match:
        return int(title_match.group("issue_number"))

    return None


def _close_issue_as_completed(repo: str, issue_number: int) -> None:
    token = _get_github_token()
    url = f"{GITHUB_API_BASE_URL}/repos/{repo}/issues/{issue_number}"

    try:
        response = httpx.patch(
            url,
            headers=_github_headers(token),
            json={"state": "closed", "state_reason": "completed"},
            timeout=15,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        logger.error(
            "Failed to move GitHub issue to Done repo={repo} issue_number={issue_number} error={error}",
            repo=repo,
            issue_number=issue_number,
            error=str(error),
        )
        raise


def _get_github_token() -> str:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")

    return token


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
