"""CHANGELOG update feature runner with GitHub commit and local backup fallback."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from backend.github_client import (
    GitHubCommitResult,
    commit_repository_file_text,
    fetch_repository_file_text,
    resolve_commit_branch,
    write_local_artifact_backup,
)

CHANGELOG_PATH = "CHANGELOG.md"


@dataclass(frozen=True)
class ChangelogUpdateResult:
    success: bool
    repository: str
    pr_number: int | None
    branch: str
    entry_markdown: str
    destination: str
    error_message: str | None = None
    local_backup_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_changelog_entry(
    pr_number: int | None,
    title: str,
    author: str = "",
    merged_at: str | None = None,
    change_types: list[str] | None = None,
    summary: str = "",
    changed_files: list[str] | None = None,
) -> str:
    date_str = (merged_at or datetime.now(timezone.utc).isoformat())[:10]
    pr_label = f"PR #{pr_number}" if pr_number is not None else "Merged PR"
    author_suffix = f" by @{author}" if author else ""
    categories = ", ".join(change_types or ["Backend Change"])
    files_list = ", ".join(f"`{f}`" for f in (changed_files or [])[:8])

    lines = [
        f"## [{pr_label}] - {date_str}",
        f"### {title}{author_suffix}",
        f"- **Category**: {categories}",
    ]
    if summary:
        lines.append(f"- **Summary**: {summary}")
    if files_list:
        lines.append(f"- **Changed Files**: {files_list}")
    return "\n".join(lines) + "\n"


def prepend_changelog_entry(existing_content: str, entry_markdown: str, pr_number: int | None) -> str:
    cleaned_existing = (existing_content or "").strip()
    pr_marker = f"## [PR #{pr_number}]" if pr_number is not None else None
    if pr_marker and pr_marker in cleaned_existing:
        return cleaned_existing + "\n"

    header = "# Changelog\n\nAll notable changes merged via MergeFlow AI are documented in this file.\n"
    if not cleaned_existing:
        return f"{header}\n{entry_markdown.strip()}\n"

    if cleaned_existing.startswith("# "):
        first_newline = cleaned_existing.find("\n")
        if first_newline != -1:
            title_line = cleaned_existing[:first_newline].strip()
            remainder = cleaned_existing[first_newline:].strip()
            return f"{title_line}\n\n{entry_markdown.strip()}\n\n{remainder}\n"

    return f"{header}\n{entry_markdown.strip()}\n\n{cleaned_existing}\n"


async def update_repository_changelog(
    repository: str,
    pr_number: int | None,
    title: str,
    author: str = "",
    merged_at: str | None = None,
    change_types: list[str] | None = None,
    summary: str = "",
    changed_files: list[str] | None = None,
    candidate_branches: list[str | None] | None = None,
) -> ChangelogUpdateResult:
    """Update CHANGELOG.md on GitHub or fall back to a local artifact backup if commit permissions are unavailable."""
    entry_markdown = build_changelog_entry(
        pr_number=pr_number,
        title=title,
        author=author,
        merged_at=merged_at,
        change_types=change_types,
        summary=summary,
        changed_files=changed_files,
    )

    try:
        branch = await resolve_commit_branch(repository, candidate_branches or ["main", "master"])
    except Exception:
        branch = "main"

    try:
        existing_changelog = await fetch_repository_file_text(repository, CHANGELOG_PATH, ref=branch)
    except Exception:
        existing_changelog = ""

    updated_changelog = prepend_changelog_entry(existing_changelog, entry_markdown, pr_number)
    commit_msg = f"Update CHANGELOG.md for PR #{pr_number}" if pr_number is not None else "Update CHANGELOG.md"

    try:
        commit_result: GitHubCommitResult = await commit_repository_file_text(
            repository=repository,
            branch=branch,
            file_path=CHANGELOG_PATH,
            content=updated_changelog,
            commit_message=commit_msg,
            pr_number=pr_number,
        )
        return ChangelogUpdateResult(
            success=commit_result.success,
            repository=repository,
            pr_number=pr_number,
            branch=branch,
            entry_markdown=entry_markdown,
            destination=commit_result.destination,
            error_message=commit_result.error_message,
            local_backup_path=commit_result.local_backup_path,
        )
    except Exception as error:
        logger.warning(
            "CHANGELOG.md remote update failed; saving local backup repo={repo} pr_number={pr_number} error={error}",
            repo=repository,
            pr_number=pr_number,
            error=str(error),
        )
        backup_path = write_local_artifact_backup(repository, pr_number, CHANGELOG_PATH, updated_changelog)
        return ChangelogUpdateResult(
            success=False,
            repository=repository,
            pr_number=pr_number,
            branch=branch,
            entry_markdown=entry_markdown,
            destination=f"Local backup at {backup_path}",
            error_message=str(error),
            local_backup_path=backup_path,
        )
