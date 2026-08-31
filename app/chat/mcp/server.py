"""Build an MCP server exposing chat capabilities as tools."""
from ..application.chat_service import ChatService
from .config import McpPolicy
from .tools import ChatTools


def build_server(service: ChatService, *, policy: McpPolicy | None = None) -> "MCPServer":
    """Create an MCP server bound to a ChatService.

    Tools live at the adapter boundary; the chat application stays synchronous
    and decoupled from MCP. Identity is currently caller-supplied per tool
    (tenant_id/user_id) until real authentication is wired; the policy's
    auth_enabled flag reserves the boundary for a future token verifier.
    """
    from mcp.server.mcpserver import MCPServer

    policy = policy or McpPolicy()
    tools = ChatTools(service)
    server = MCPServer(name=policy.name, version=policy.version)
    if "chat_ask" in policy.enabled_tools:
        @server.tool()
        async def chat_ask(question: str, conversation_id: str,
                           tenant_id: str, user_id: str,
                           confirmed: bool = False) -> dict:
            return await tools.chat_ask(question, conversation_id,
                                        tenant_id, user_id, confirmed)

    if "document_search" in policy.enabled_tools:
        @server.tool()
        async def document_search(query: str, top_k: int,
                                  tenant_id: str, user_id: str) -> dict:
            return await tools.document_search(query, top_k, tenant_id, user_id)

    if "sop_get_step" in policy.enabled_tools:
        @server.tool()
        async def sop_get_step(query: str, conversation_id: str,
                               tenant_id: str, user_id: str,
                               confirmed: bool = False) -> dict:
            return await tools.sop_get_step(query, conversation_id,
                                            tenant_id, user_id, confirmed)

    if "readonly_sql_query" in policy.enabled_tools:
        @server.tool()
        async def readonly_sql_query(question: str, tenant_id: str,
                                     user_id: str) -> dict:
            return await tools.readonly_sql_query(question, tenant_id, user_id)

    return server
