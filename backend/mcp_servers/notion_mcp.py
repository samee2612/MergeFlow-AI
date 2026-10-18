"""MCP server entry point and tool dispatcher for Notion documentation tools with local fallbacks."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.generators.notion_draft_generator import (
    NotionDocumentationHierarchyClient,
    NotionDocumentationResult,
    update_notion_documentation,
)
from backend.generators.notion_generator import (
    _paragraphs,
    get_notion_settings,
    safe_write_notion_run_metadata,
)

if TYPE_CHECKING:
    from backend.classifier.diff_classifier import BackendDiffClassification
    from backend.generators.api_spec_generator import ApiSpecGenerationResult
    from backend.generators.openapi_generator import OpenApiGenerationResult
    from backend.generators.postman_generator import PostmanGenerationResult
    from backend.pipeline import PullRequestContext
    from backend.service_resolver import ServiceResolution

SERVER_NAME = "mergeflow-notion-mcp"


def get_mcp_tool_definitions() -> list[dict[str, Any]]:
    """Return MCP tool schemas exposed by the Notion MCP server."""
    return [
        {
            "name": "find_page_by_title",
            "description": "Search for a child Notion page under a parent page by exact title.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "parent_page_id": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["parent_page_id", "title"],
            },
        },
        {
            "name": "create_page",
            "description": "Create a new child Notion page under a parent page.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "parent_page_id": {"type": "string"},
                    "title": {"type": "string"},
                    "markdown_text": {"type": "string"},
                },
                "required": ["parent_page_id", "title"],
            },
        },
        {
            "name": "update_page",
            "description": "Replace the content blocks of an existing Notion page.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "markdown_text": {"type": "string"},
                },
                "required": ["page_id", "markdown_text"],
            },
        },
    ]


async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a Notion MCP tool with automatic fallback handling."""
    try:
        settings = get_notion_settings()
        client = NotionDocumentationHierarchyClient(settings)

        if tool_name == "find_page_by_title":
            parent_id = str(arguments.get("parent_page_id") or settings.root_page_id)
            title = str(arguments["title"])
            page_ref = await client.find_child_page_by_title(parent_id, title)
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {
                    "found": page_ref is not None,
                    "page_id": page_ref.page_id if page_ref else None,
                    "page_url": page_ref.page_url if page_ref else None,
                },
            }

        if tool_name == "create_page":
            parent_id = str(arguments.get("parent_page_id") or settings.root_page_id)
            title = str(arguments["title"])
            blocks = _paragraphs(str(arguments.get("markdown_text") or ""))
            page_ref = await client.create_child_page(parent_id, title, blocks)
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {"page_id": page_ref.page_id, "page_url": page_ref.page_url},
            }

        if tool_name == "update_page":
            page_id = str(arguments["page_id"])
            blocks = _paragraphs(str(arguments.get("markdown_text") or ""))
            page_ref = await client.update_child_page(page_id, blocks)
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {"page_id": page_ref.page_id, "page_url": page_ref.page_url},
            }

        raise ValueError(f"Unknown Notion MCP tool: {tool_name}")
    except Exception as error:
        logger.warning(
            "Notion MCP tool execution failed; returning fallback response tool={tool} error={error}",
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


async def mcp_update_notion_documentation(
    pr_context: PullRequestContext,
    service: ServiceResolution,
    classification: BackendDiffClassification,
    api_spec_result: ApiSpecGenerationResult,
    openapi_result: OpenApiGenerationResult,
    postman_result: PostmanGenerationResult,
) -> NotionDocumentationResult:
    """Update Notion PR review and service pages via the Notion MCP layer with local metadata fallback."""
    try:
        result = await update_notion_documentation(
            pr_context,
            service,
            classification,
            api_spec_result,
            openapi_result,
            postman_result,
        )
        return result
    except Exception as error:
        logger.exception(
            "Notion MCP documentation sync failed; writing local fallback metadata repo={repo} pr_number={pr_number} error={error}",
            repo=pr_context.repository,
            pr_number=pr_context.pr_number,
            error=str(error),
        )
        metadata_path = safe_write_notion_run_metadata(
            pr_context,
            status="FAILED",
            page_id=None,
            page_url=None,
            service_page_id=None,
            service_page_url=None,
            error_message=str(error),
        )
        return NotionDocumentationResult(
            success=False,
            action="fallback_local_metadata",
            error_message=str(error),
            metadata_path=metadata_path,
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
