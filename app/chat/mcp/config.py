"""MCP server policy/transport settings (no construction here)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class McpPolicy:
    name: str = "enterprise-agent"
    version: str = "0.1.0"
    auth_enabled: bool = False
    enabled_tools: tuple[str, ...] = (
        "chat_ask", "document_search", "sop_get_step", "readonly_sql_query",
    )


def build_policy(*, auth_enabled: bool = False,
                 enabled_tools: tuple[str, ...] | None = None) -> McpPolicy:
    return McpPolicy(
        auth_enabled=auth_enabled,
        enabled_tools=enabled_tools or McpPolicy.enabled_tools,
    )
