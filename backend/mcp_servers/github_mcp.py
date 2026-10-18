"""MCP server entry point and tool dispatcher for GitHub operations with automatic fallbacks."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from backend.features.changelog_updater import ChangelogUpdateResult, update_repository_changelog
from backend.features.env_detector import detect_new_env_vars
from backend.features.issue_mover import move_issue_to_done
from backend.github_client import (
    GitHubCommitResult,
    GitHubDeleteResult,
    commit_repository_file_text,
    delete_repository_file,
    fetch_pull_request_changed_files,
    fetch_pull_request_diff,
    fetch_repository_file_text,
    write_local_artifact_backup,
)

SERVER_NAME = "mergeflow-github-mcp"


def get_mcp_tool_definitions() -> list[dict[str, Any]]:
    """Return MCP tool schemas exposed by the GitHub MCP server."""
    return [
        {
            "name": "fetch_pr_diff",
            "description": "Fetch the unified diff text for a pull request from GitHub.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string"},
                    "pr_number": {"type": "integer"},
                },
                "required": ["repository", "pr_number"],
            },
        },
        {
            "name": "fetch_pr_changed_files",
            "description": "Fetch the list of changed file paths for a pull request from GitHub.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string"},
                    "pr_number": {"type": "integer"},
                },
                "required": ["repository", "pr_number"],
            },
        },
        {
            "name": "fetch_file_content",
            "description": "Fetch file text from a GitHub repository at an optional ref.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string"},
                    "file_path": {"type": "string"},
                    "ref": {"type": ["string", "null"]},
                },
                "required": ["repository", "file_path"],
            },
        },
        {
            "name": "commit_file",
            "description": "Commit a file to a GitHub repository branch with local artifact backup fallback.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string"},
                    "branch": {"type": "string"},
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                    "commit_message": {"type": "string"},
                    "pr_number": {"type": ["integer", "null"]},
                },
                "required": ["repository", "branch", "file_path", "content", "commit_message"],
            },
        },
        {
            "name": "move_issue_to_done",
            "description": "Close a linked GitHub issue as completed when a PR is merged.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string"},
                    "pr_title": {"type": "string"},
                    "pr_body": {"type": ["string", "null"]},
                    "branch_name": {"type": "string"},
                },
                "required": ["repository", "pr_title", "branch_name"],
            },
        },
        {
            "name": "detect_and_update_env_example",
            "description": "Detect newly added environment variables in a PR diff and update .env.example.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "diff_text": {"type": "string"},
                    "repository": {"type": "string"},
                    "pr_number": {"type": "integer"},
                },
                "required": ["diff_text", "repository", "pr_number"],
            },
        },
        {
            "name": "update_changelog",
            "description": "Prepend a structured release entry to CHANGELOG.md with local backup fallback.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string"},
                    "pr_number": {"type": ["integer", "null"]},
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "merged_at": {"type": ["string", "null"]},
                    "change_types": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                    "changed_files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["repository", "title"],
            },
        },
    ]


async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a GitHub MCP tool with automatic fallback handling."""
    try:
        if tool_name == "fetch_pr_diff":
            diff_text = await fetch_pull_request_diff(
                str(arguments["repository"]),
                int(arguments["pr_number"]),
            )
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {"diff_text": diff_text, "char_count": len(diff_text)},
            }

        if tool_name == "fetch_pr_changed_files":
            changed_files = await fetch_pull_request_changed_files(
                str(arguments["repository"]),
                int(arguments["pr_number"]),
            )
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {"changed_files": changed_files},
            }

        if tool_name == "fetch_file_content":
            content = await fetch_repository_file_text(
                str(arguments["repository"]),
                str(arguments["file_path"]),
                ref=arguments.get("ref"),
            )
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {"content": content},
            }

        if tool_name == "commit_file":
            commit_result = await commit_repository_file_text(
                repository=str(arguments["repository"]),
                branch=str(arguments.get("branch") or "main"),
                file_path=str(arguments["file_path"]),
                content=str(arguments["content"]),
                commit_message=str(arguments["commit_message"]),
                pr_number=arguments.get("pr_number"),
            )
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok" if commit_result.success else "fallback",
                "result": {
                    "success": commit_result.success,
                    "destination": commit_result.destination,
                    "local_backup_path": commit_result.local_backup_path,
                    "error_message": commit_result.error_message,
                },
            }

        if tool_name == "move_issue_to_done":
            issue_number = await asyncio.to_thread(
                move_issue_to_done,
                str(arguments["repository"]),
                str(arguments.get("pr_title") or ""),
                arguments.get("pr_body"),
                str(arguments.get("branch_name") or ""),
            )
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {"closed_issue_number": issue_number},
            }

        if tool_name == "detect_and_update_env_example":
            new_vars = await asyncio.to_thread(
                detect_new_env_vars,
                str(arguments.get("diff_text") or ""),
                str(arguments["repository"]),
                int(arguments["pr_number"]),
            )
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {"new_env_vars": new_vars},
            }

        if tool_name == "update_changelog":
            changelog_result = await update_repository_changelog(
                repository=str(arguments["repository"]),
                pr_number=arguments.get("pr_number"),
                title=str(arguments.get("title") or ""),
                author=str(arguments.get("author") or ""),
                merged_at=arguments.get("merged_at"),
                change_types=list(arguments.get("change_types") or []),
                summary=str(arguments.get("summary") or ""),
                changed_files=list(arguments.get("changed_files") or []),
            )
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok" if changelog_result.success else "fallback",
                "result": changelog_result.as_dict(),
            }

        raise ValueError(f"Unknown GitHub MCP tool: {tool_name}")
    except Exception as error:
        logger.warning(
            "GitHub MCP tool execution failed; returning fallback response tool={tool} error={error}",
            tool=tool_name,
            error=str(error),
        )
        return {
            "server": SERVER_NAME,
            "tool": tool_name,
            "status": "fallback",
            "error": str(error),
            "result": {},
        }


async def mcp_fetch_pr_diff(repository: str, pr_number: int) -> str:
    """Fetch PR diff via GitHub MCP tool with direct fallback."""
    response = await call_mcp_tool(
        "fetch_pr_diff",
        {"repository": repository, "pr_number": pr_number},
    )
    diff_text = response.get("result", {}).get("diff_text")
    if isinstance(diff_text, str) and diff_text:
        return diff_text
    return await fetch_pull_request_diff(repository, pr_number)


async def mcp_fetch_file_content(repository: str, file_path: str) -> str:
    """Fetch repository file content via GitHub MCP tool with direct fallback."""
    response = await call_mcp_tool(
        "fetch_file_content",
        {"repository": repository, "file_path": file_path},
    )
    content = response.get("result", {}).get("content")
    if isinstance(content, str) and content:
        return content
    return await fetch_repository_file_text(repository, file_path)


async def mcp_run_github_side_effects(
    repository: str,
    pr_number: int | None,
    title: str,
    author: str,
    merged_at: str | None,
    head_branch: str,
    base_branch: str,
    default_branch: str,
    diff_text: str,
    change_types: list[str],
    summary: str,
    changed_files: list[str],
) -> dict[str, Any]:
    """Run non-blocking GitHub MCP side effects (issue movement, env var detection, changelog update) with fallbacks."""
    side_effects: dict[str, Any] = {}

    # 1. Move linked GitHub issue to Done (with safe fallback)
    try:
        issue_resp = await call_mcp_tool(
            "move_issue_to_done",
            {
                "repository": repository,
                "pr_title": title,
                "pr_body": None,
                "branch_name": head_branch,
            },
        )
        side_effects["issueMover"] = issue_resp
    except Exception as error:
        logger.warning("GitHub MCP issue_mover skipped error={error}", error=str(error))
        side_effects["issueMover"] = {"status": "fallback", "error": str(error)}

    # 2. Detect new environment variables (with safe fallback if token is read-only)
    if pr_number is not None:
        try:
            env_resp = await call_mcp_tool(
                "detect_and_update_env_example",
                {
                    "diff_text": diff_text,
                    "repository": repository,
                    "pr_number": pr_number,
                },
            )
            side_effects["envDetector"] = env_resp
        except Exception as error:
            logger.warning("GitHub MCP env_detector skipped error={error}", error=str(error))
            side_effects["envDetector"] = {"status": "fallback", "error": str(error)}

    # 3. Update CHANGELOG.md (commits to GitHub or saves local backup if token is read-only)
    try:
        changelog_result: ChangelogUpdateResult = await update_repository_changelog(
            repository=repository,
            pr_number=pr_number,
            title=title,
            author=author,
            merged_at=merged_at,
            change_types=change_types,
            summary=summary,
            changed_files=changed_files,
            candidate_branches=[base_branch, default_branch, head_branch],
        )
        side_effects["changelog"] = {
            "server": SERVER_NAME,
            "tool": "update_changelog",
            "status": "ok" if changelog_result.success else "fallback",
            "result": changelog_result.as_dict(),
        }
    except Exception as error:
        logger.warning("GitHub MCP changelog update failed error={error}", error=str(error))
        side_effects["changelog"] = {"status": "fallback", "error": str(error)}

    return side_effects


async def mcp_delete_repository_file(
    repository: str,
    branch: str,
    file_path: str,
    commit_message: str,
    pr_number: int | None = None,
) -> GitHubDeleteResult:
    """Delete temporary repository artifact via GitHub client with safe fallback."""
    return await delete_repository_file(
        repository=repository,
        branch=branch,
        file_path=file_path,
        commit_message=commit_message,
        pr_number=pr_number,
    )


def create_mcp_stdio_server() -> Any:
    """Create a standard MCP Server instance for stdio execution."""
    from mcp.server import Server
    import mcp.types as mcp_types

    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=tool_def["name"],
                description=tool_def["description"],
                inputSchema=tool_def["inputSchema"],
            )
            for tool_def in get_mcp_tool_definitions()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[mcp_types.TextContent]:
        response = await call_mcp_tool(name, arguments or {})
        return [mcp_types.TextContent(type="text", text=json.dumps(response, indent=2))]

    return server


async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server

    server = create_mcp_stdio_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_run_stdio())
