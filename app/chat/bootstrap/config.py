"""Chat configuration; no adapter construction belongs here."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatSettings:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    temperature: float = 0.2
    max_tokens: int = 1024
    top_k: int = 5


@dataclass(frozen=True)
class McpSettings:
    """MCP transport and exposed-tool policy."""
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8001
    auth_enabled: bool = False
    enabled_tools: tuple[str, ...] = (
        "chat_ask", "document_search", "sop_get_step", "readonly_sql_query",
    )


def read_settings() -> ChatSettings:
    return ChatSettings(
        api_key=os.getenv("DEEPSEEK_API_KEY", os.getenv("SILICONFLOW_API_KEY", "")),
        base_url=os.getenv("CHAT_BASE_URL", "https://api.deepseek.com/v1"),
        model=os.getenv("CHAT_MODEL", "deepseek-chat"),
        temperature=float(os.getenv("CHAT_TEMPERATURE", "0.2")),
        max_tokens=int(os.getenv("CHAT_MAX_TOKENS", "1024")),
        top_k=max(1, int(os.getenv("CHAT_TOP_K", "5"))),
    )


def read_mcp_settings() -> McpSettings:
    raw_tools = os.getenv(
        "CHAT_MCP_TOOLS",
        "chat_ask,document_search,sop_get_step,readonly_sql_query",
    )
    return McpSettings(
        transport=os.getenv("CHAT_MCP_TRANSPORT", "stdio"),
        host=os.getenv("CHAT_MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("CHAT_MCP_PORT", "8001")),
        auth_enabled=os.getenv("CHAT_MCP_AUTH_ENABLED", "false").lower() == "true",
        enabled_tools=tuple(item.strip() for item in raw_tools.split(",") if item.strip()),
    )
