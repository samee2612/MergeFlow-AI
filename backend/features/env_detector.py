"""Environment variable detection feature runner."""

from __future__ import annotations

import base64
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
ENV_EXAMPLE_PATH = ".env.example"

ENV_VAR_NAME = r"(?P<key>[A-Z][A-Z0-9_]+)"
ENV_REFERENCE_PATTERNS = (
    re.compile(rf"os\.getenv\(\s*['\"]{ENV_VAR_NAME}['\"]"),
    re.compile(rf"os\.environ(?:\.get\(\s*|\[\s*)['\"]{ENV_VAR_NAME}['\"]"),
    re.compile(rf"process\.env\.{ENV_VAR_NAME}\b"),
    re.compile(rf"process\.env\[\s*['\"]{ENV_VAR_NAME}['\"]\s*\]"),
    re.compile(rf"dotenv_values\([^)]*\)(?:\.get\(\s*|\[\s*)['\"]{ENV_VAR_NAME}['\"]"),
)
ENV_ASSIGNMENT_PATTERN = re.compile(rf"^(?:export\s+)?{ENV_VAR_NAME}\s*=")


def detect_new_env_vars(diff_text: str, repo: str, pr_number: int) -> list[str]:
    """Detect new env vars, comment on the PR, and update .env.example."""
    referenced_vars = _extract_env_vars_from_diff(diff_text)
    if not referenced_vars:
        return []

    token = _get_github_token()
    pull_request = _get_pull_request(repo, pr_number, token)
    head = pull_request.get("head", {})
    head_repo = head.get("repo") or {}
    target_repo = head_repo.get("full_name") or repo
    target_branch = head.get("ref")

    env_example = _get_env_example(target_repo, target_branch, token)
    existing_vars = _extract_existing_env_vars(env_example["content"])
    new_vars = sorted(referenced_vars - existing_vars)

    if not new_vars:
        return []

    logger.info(
        "Detected new environment variables repo={repo} pr_number={pr_number} vars={vars}",
        repo=repo,
        pr_number=pr_number,
        vars=new_vars,
    )
    _commit_env_example_update(target_repo, target_branch, env_example, new_vars, token)
    _post_pr_comment(repo, pr_number, new_vars, token)

    return new_vars


def _extract_env_vars_from_diff(diff_text: str) -> set[str]:
    env_vars: set[str] = set()

    for line in diff_text.splitlines():
        if not _is_added_diff_line(line):
            continue

        added_line = line[1:].strip()
        for pattern in ENV_REFERENCE_PATTERNS:
            env_vars.update(match.group("key") for match in pattern.finditer(added_line))

        assignment_match = ENV_ASSIGNMENT_PATTERN.search(added_line)
        if assignment_match:
            env_vars.add(assignment_match.group("key"))

    return env_vars


def _is_added_diff_line(line: str) -> bool:
    return line.startswith("+") and not line.startswith("+++")


def _get_pull_request(repo: str, pr_number: int, token: str) -> dict[str, Any]:
    response = httpx.get(
        f"{GITHUB_API_BASE_URL}/repos/{repo}/pulls/{pr_number}",
        headers=_github_headers(token),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _get_env_example(repo: str, branch: str | None, token: str) -> dict[str, str | None]:
    params = {"ref": branch} if branch else None
    response = httpx.get(
        f"{GITHUB_API_BASE_URL}/repos/{repo}/contents/{ENV_EXAMPLE_PATH}",
        headers=_github_headers(token),
        params=params,
        timeout=15,
    )

    if response.status_code == 404:
        return {"content": "", "sha": None}

    response.raise_for_status()
    payload = response.json()
    encoded_content = payload.get("content", "")
    content = base64.b64decode(encoded_content).decode("utf-8") if encoded_content else ""

    return {"content": content, "sha": payload.get("sha")}


def _extract_existing_env_vars(env_example_content: str) -> set[str]:
    existing_vars: set[str] = set()

    for line in env_example_content.splitlines():
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue

        assignment_match = ENV_ASSIGNMENT_PATTERN.search(stripped_line)
        if assignment_match:
            existing_vars.add(assignment_match.group("key"))

    return existing_vars


def _post_pr_comment(repo: str, pr_number: int, new_vars: list[str], token: str) -> None:
    formatted_vars = "\n".join(f"- `{env_var}`" for env_var in new_vars)
    body = (
        "## MergeFlow AI: New Environment Variables Detected\n\n"
        "These variables are referenced in this PR but were missing from `.env.example`:\n\n"
        f"{formatted_vars}\n\n"
        "I also committed empty placeholders for them to `.env.example`."
    )

    response = httpx.post(
        f"{GITHUB_API_BASE_URL}/repos/{repo}/issues/{pr_number}/comments",
        headers=_github_headers(token),
        json={"body": body},
        timeout=15,
    )
    response.raise_for_status()


def _commit_env_example_update(
    repo: str,
    branch: str | None,
    env_example: dict[str, str | None],
    new_vars: list[str],
    token: str,
) -> None:
    updated_content = _append_env_vars(env_example["content"] or "", new_vars)
    payload: dict[str, Any] = {
        "message": "Add new environment variables to .env.example",
        "content": base64.b64encode(updated_content.encode("utf-8")).decode("utf-8"),
    }

    if branch:
        payload["branch"] = branch
    if env_example["sha"]:
        payload["sha"] = env_example["sha"]

    response = httpx.put(
        f"{GITHUB_API_BASE_URL}/repos/{repo}/contents/{ENV_EXAMPLE_PATH}",
        headers=_github_headers(token),
        json=payload,
        timeout=15,
    )
    response.raise_for_status()


def _append_env_vars(env_example_content: str, new_vars: list[str]) -> str:
    content = env_example_content.rstrip()
    new_lines = "\n".join(f"{env_var}=" for env_var in new_vars)

    if not content:
        return f"{new_lines}\n"

    return f"{content}\n\n# Added by MergeFlow AI\n{new_lines}\n"


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
