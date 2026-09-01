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
    llm_timeout: float = 90.0
    llm_max_retries: int = 2
    max_concurrency: int = 16
    rate_limit: int = 60
    rate_window_seconds: int = 60


@dataclass(frozen=True)
class StorageSettings:
    """Where conversation/SOP/schema state lives.

    ``backend`` is ``memory`` or ``mysql``. Defaults to ``memory`` until
    authentication supplies a trusted tenant/user; switching to ``mysql``
    before that exposes cross-tenant risk.
    """
    backend: str = "mysql"
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "enterprise_agent"


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
    settings = ChatSettings(
        api_key=os.getenv("DEEPSEEK_API_KEY", os.getenv("SILICONFLOW_API_KEY", "")),
        base_url=os.getenv("CHAT_BASE_URL", "https://api.deepseek.com/v1"),
        model=os.getenv("CHAT_MODEL", "deepseek-chat"),
        temperature=float(os.getenv("CHAT_TEMPERATURE", "0.2")),
        max_tokens=int(os.getenv("CHAT_MAX_TOKENS", "1024")),
        top_k=max(1, int(os.getenv("CHAT_TOP_K", "5"))),
        llm_timeout=float(os.getenv("CHAT_LLM_TIMEOUT", "90")),
        llm_max_retries=max(0, int(os.getenv("CHAT_LLM_MAX_RETRIES", "2"))),
        max_concurrency=max(1, int(os.getenv("CHAT_MAX_CONCURRENCY", "16"))),
        rate_limit=max(1, int(os.getenv("CHAT_RATE_LIMIT", "60"))),
        rate_window_seconds=max(1, int(os.getenv("CHAT_RATE_WINDOW", "60"))),
    )
    if not 0 <= settings.temperature <= 2:
        raise ValueError("CHAT_TEMPERATURE 必须在 0 到 2 之间")
    if settings.max_tokens < 1 or settings.max_tokens > 100000:
        raise ValueError("CHAT_MAX_TOKENS 超出范围")
    if settings.llm_timeout <= 0 or settings.llm_timeout > 600:
        raise ValueError("CHAT_LLM_TIMEOUT 必须在 0 到 600 秒之间")
    return settings


def read_storage_settings() -> StorageSettings:
    backend = os.getenv("CHAT_STORAGE", "memory").strip().lower()
    if backend not in {"memory", "mysql"}:
        raise ValueError("CHAT_STORAGE 必须为 memory 或 mysql")
    return StorageSettings(
        backend=backend,
        mysql_host=os.getenv("CHAT_MYSQL_HOST", os.getenv("MYSQL_HOST", "")),
        mysql_port=int(os.getenv("CHAT_MYSQL_PORT", os.getenv("MYSQL_PORT", "3306"))),
        mysql_user=os.getenv("CHAT_MYSQL_USER", os.getenv("MYSQL_USER", "root")),
        mysql_password=os.getenv(
            "CHAT_MYSQL_PASSWORD",
            os.getenv("MYSQL_PASSWORD", os.getenv("MYSQL_ROOT_PASSWORD", "")),
        ),
        mysql_database=os.getenv("CHAT_MYSQL_DB", os.getenv("MYSQL_DB", "enterprise_agent")),
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
