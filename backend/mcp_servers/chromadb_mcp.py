"""MCP server entry point and tool dispatcher for ChromaDB RAG tools with local fallback."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from backend.rag.retriever import (
    RAGRetrievalResult,
    RAGStoreResult,
    format_rag_context_for_prompt,
    retrieve_similar_prs,
    store_pr_context,
)

SERVER_NAME = "mergeflow-chromadb-mcp"


def get_mcp_tool_definitions() -> list[dict[str, Any]]:
    """Return MCP tool schemas exposed by the ChromaDB RAG server."""
    return [
        {
            "name": "store_pr_context",
            "description": "Embed and store a merged pull request in ChromaDB (with local JSON fallback).",
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
                    "diff_excerpt": {"type": "string"},
                    "endpoints": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["repository", "title"],
            },
        },
        {
            "name": "retrieve_similar_prs",
            "description": "Retrieve top-K semantically similar historical PRs from ChromaDB or local fallback.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repository": {"type": "string"},
                    "query_text": {"type": "string"},
                    "exclude_pr_number": {"type": ["integer", "null"]},
                    "top_k": {"type": "integer", "default": 3},
                },
                "required": ["repository", "query_text"],
            },
        },
    ]


async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a ChromaDB MCP tool with automatic fallback handling."""
    try:
        if tool_name == "store_pr_context":
            store_result = await asyncio.to_thread(
                store_pr_context,
                repository=str(arguments.get("repository") or ""),
                pr_number=arguments.get("pr_number"),
                title=str(arguments.get("title") or ""),
                author=str(arguments.get("author") or ""),
                merged_at=arguments.get("merged_at"),
                change_types=list(arguments.get("change_types") or []),
                summary=str(arguments.get("summary") or ""),
                changed_files=list(arguments.get("changed_files") or []),
                diff_excerpt=str(arguments.get("diff_excerpt") or ""),
                endpoints=list(arguments.get("endpoints") or []),
            )
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": store_result.as_dict(),
            }

        if tool_name == "retrieve_similar_prs":
            retrieval_result = await asyncio.to_thread(
                retrieve_similar_prs,
                repository=str(arguments.get("repository") or ""),
                query_text=str(arguments.get("query_text") or ""),
                exclude_pr_number=arguments.get("exclude_pr_number"),
                top_k=int(arguments.get("top_k") or 3),
            )
            return {
                "server": SERVER_NAME,
                "tool": tool_name,
                "status": "ok",
                "result": {
                    **retrieval_result.as_dict(),
                    "formattedPromptContext": format_rag_context_for_prompt(retrieval_result),
                },
            }

        raise ValueError(f"Unknown ChromaDB MCP tool: {tool_name}")
    except Exception as error:
        logger.warning(
            "ChromaDB MCP tool execution failed; returning safe fallback tool={tool} error={error}",
            tool=tool_name,
            error=str(error),
        )
        return {
            "server": SERVER_NAME,
            "tool": tool_name,
            "status": "fallback",
            "error": str(error),
            "result": {
                "success": False,
                "similarPrs": [],
                "formattedPromptContext": "No similar past PRs found in repository history.",
            },
        }


async def mcp_retrieve_similar_prs(
    repository: str,
    query_text: str,
    exclude_pr_number: int | None = None,
    top_k: int = 3,
) -> tuple[RAGRetrievalResult, str]:
    """High-level helper used by the MergeFlow pipeline to query RAG via the ChromaDB MCP layer."""
    try:
        retrieval_result = await asyncio.to_thread(
            retrieve_similar_prs,
            repository=repository,
            query_text=query_text,
            exclude_pr_number=exclude_pr_number,
            top_k=top_k,
        )
        formatted = format_rag_context_for_prompt(retrieval_result)
        return retrieval_result, formatted
    except Exception as error:
        logger.warning("mcp_retrieve_similar_prs fallback triggered error={error}", error=str(error))
        empty = RAGRetrievalResult(
            success=False,
            repository=repository,
            similar_prs=[],
            backend="fallback_empty",
            error_message=str(error),
        )
        return empty, "No similar past PRs found in repository history."


async def mcp_store_pr_context(
    repository: str,
    pr_number: int | None,
    title: str,
    author: str = "",
    merged_at: str | None = None,
    change_types: list[str] | None = None,
    summary: str = "",
    changed_files: list[str] | None = None,
    diff_excerpt: str = "",
    endpoints: list[str] | None = None,
) -> RAGStoreResult:
    """High-level helper used by the MergeFlow pipeline to index a PR via the ChromaDB MCP layer."""
    try:
        return await asyncio.to_thread(
            store_pr_context,
            repository=repository,
            pr_number=pr_number,
            title=title,
            author=author,
            merged_at=merged_at,
            change_types=change_types,
            summary=summary,
            changed_files=changed_files,
            diff_excerpt=diff_excerpt,
            endpoints=endpoints,
        )
    except Exception as error:
        logger.warning("mcp_store_pr_context fallback triggered error={error}", error=str(error))
        return RAGStoreResult(
            success=False,
            pr_id=f"{repository}__{pr_number}",
            repository=repository,
            pr_number=pr_number,
            backend="fallback_error",
            error_message=str(error),
        )


def create_mcp_stdio_server() -> Any:
    """Create a standard MCP Server instance if the `mcp` package is installed."""
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
