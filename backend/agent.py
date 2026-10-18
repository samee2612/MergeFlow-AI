"""Claude + Gemini dual-provider MCP agent orchestrator with automatic fallback."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger

from backend.gemini_config import get_anthropic_api_key, get_claude_model, get_gemini_model
from backend.mcp_servers import chromadb_mcp, github_mcp, notion_mcp, sendgrid_mcp


@dataclass(frozen=True)
class AgentProviderStatus:
    active_provider: str
    active_model: str
    claude_configured: bool
    fallback_provider: str
    mcp_servers: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_agent_provider_status() -> AgentProviderStatus:
    """Return current LLM provider configuration and registered MCP servers."""
    claude_key = get_anthropic_api_key()
    claude_configured = bool(claude_key)
    active_provider = "anthropic_claude" if claude_configured else "google_gemini"
    active_model = get_claude_model() if claude_configured else get_gemini_model()
    return AgentProviderStatus(
        active_provider=active_provider,
        active_model=active_model,
        claude_configured=claude_configured,
        fallback_provider="google_gemini",
        mcp_servers=[
            github_mcp.SERVER_NAME,
            chromadb_mcp.SERVER_NAME,
            notion_mcp.SERVER_NAME,
            sendgrid_mcp.SERVER_NAME,
        ],
    )


def get_all_mcp_tools_for_claude() -> list[dict[str, Any]]:
    """Aggregate all MCP tool definitions in Anthropic tool-use format."""
    all_defs = (
        github_mcp.get_mcp_tool_definitions()
        + chromadb_mcp.get_mcp_tool_definitions()
        + notion_mcp.get_mcp_tool_definitions()
        + sendgrid_mcp.get_mcp_tool_definitions()
    )
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["inputSchema"],
        }
        for tool in all_defs
    ]


async def dispatch_mcp_tool_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route a tool call from the agent to the appropriate MergeFlow MCP server."""
    github_tools = {t["name"] for t in github_mcp.get_mcp_tool_definitions()}
    chroma_tools = {t["name"] for t in chromadb_mcp.get_mcp_tool_definitions()}
    notion_tools = {t["name"] for t in notion_mcp.get_mcp_tool_definitions()}
    sendgrid_tools = {t["name"] for t in sendgrid_mcp.get_mcp_tool_definitions()}

    if tool_name in github_tools:
        return await github_mcp.call_mcp_tool(tool_name, arguments)
    if tool_name in chroma_tools:
        return await chromadb_mcp.call_mcp_tool(tool_name, arguments)
    if tool_name in notion_tools:
        return await notion_mcp.call_mcp_tool(tool_name, arguments)
    if tool_name in sendgrid_tools:
        return await sendgrid_mcp.call_mcp_tool(tool_name, arguments)

    logger.warning("Unknown MCP tool requested by agent tool={tool}", tool=tool_name)
    return {"status": "fallback", "error": f"Unknown MCP tool: {tool_name}", "result": {}}
