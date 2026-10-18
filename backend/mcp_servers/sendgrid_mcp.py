"""MCP server entry point and tool dispatcher for SendGrid release email notifications with local fallbacks."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.generators.email_generator import (
    EmailSendResult,
    ReleaseEmail,
    SendGridReleaseEmailClient,
    generate_and_send_release_email,
    get_email_settings,
)
from backend.github_client import write_local_artifact_backup

if TYPE_CHECKING:
    from backend.classifier.diff_classifier import BackendDiffClassification
    from backend.generators.api_spec_generator import ApiSpecGenerationResult
    from backend.generators.notion_draft_generator import NotionDocumentationResult
    from backend.generators.notion_generator import NotionSyncResult
    from backend.generators.openapi_generator import OpenApiGenerationResult
    from backend.generators.postman_generator import PostmanGenerationResult
    from backend.pipeline import PullRequestContext

SERVER_NAME = "mergeflow-sendgrid-mcp"


def get_mcp_tool_definitions() -> list[dict[str, Any]]:
    """Return MCP tool schemas exposed by the SendGrid MCP server."""
    return [
        {
            "name": "send_email",
            "description": "Send a plain-text and HTML email via SendGrid to configured or specified recipients.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "plain_text": {"type": "string"},
                    "html": {"type": "string"},
                    "recipients": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["subject", "plain_text", "html"],
            },
        },
    ]


async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a SendGrid MCP tool with automatic local backup fallback."""
    try:
        if tool_name == "send_email":
            settings = get_email_settings()
            recipients = list(arguments.get("recipients") or settings.recipients)
            email = ReleaseEmail(
                subject=str(arguments["subject"]),
                plain_text=str(arguments["plain_text"]),
                html=str(arguments["html"]),
                recipients=recipients,
            )
            client = SendGridReleaseEmailClient()
            status_code = await client.send_email(settings, email)
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {
                    "success": True,
                    "recipients": recipients,
                    "subject": email.subject,
                    "status_code": status_code,
                },
            }

        raise ValueError(f"Unknown SendGrid MCP tool: {tool_name}")
    except Exception as error:
        logger.warning(
            "SendGrid MCP tool execution failed; returning fallback response tool={tool} error={error}",
            tool=tool_name,
            error=str(error),
        )
        return {
            "server": SERVER_NAME,
            "tool": tool_name,
            "status": "fallback",
            "error": str(error),
            "result": {"success": False, "error_message": str(error)},
        }


async def mcp_generate_and_send_release_email(
    pr_context: PullRequestContext,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
    notion_result: NotionDocumentationResult | NotionSyncResult,
) -> EmailSendResult:
    """Generate and send the release email via the SendGrid MCP layer with local HTML backup fallback."""
    try:
        result = await generate_and_send_release_email(
            pr_context,
            classification,
            api_spec_result,
            openapi_result,
            postman_result,
            notion_result,
        )
        if not result.success:
            _save_local_email_fallback(pr_context, result.subject or pr_context.title, result.error_message)
        return result
    except Exception as error:
        logger.exception(
            "SendGrid MCP email notification failed; saving local fallback repo={repo} pr_number={pr_number} error={error}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            error=str(error),
        )
        _save_local_email_fallback(pr_context, pr_context.title, str(error))
        return EmailSendResult(
            success=False,
            recipients=[],
            subject=pr_context.title,
            error_message=str(error),
        )


def _save_local_email_fallback(
    pr_context: PullRequestContext,
    subject: str,
    error_message: str | None,
) -> str | None:
    try:
        payload = json.dumps(
            {
                "repository": pr_context.repository,
                "pr_number": pr_context.pr_number,
                "subject": subject,
                "error_message": error_message,
            },
            indent=2,
        )
        return write_local_artifact_backup(
            pr_context.repository,
            pr_context.pr_number,
            "notifications/release_email_fallback.json",
            payload + "\n",
        )
    except Exception:
        return None


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
