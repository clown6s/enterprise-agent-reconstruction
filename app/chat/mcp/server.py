"""Build an MCP server exposing chat capabilities as tools.

The server is a pure adapter: mounting it must not construct live services.
Authentication is resolved from the MCP transport headers, never tool arguments.
"""
from ..application.chat_service import ChatService
from ..application.context import RequestContext
from ..mcp.bridge import run_sync
from .config import McpPolicy
from .tools import ChatTools


def _request_context(ctx, auth) -> RequestContext:
    if auth is None:
        raise PermissionError("MCP 未配置认证服务")
    headers = getattr(ctx, "headers", None) or {}
    authorization = headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise PermissionError("MCP 请求缺少 Bearer Token")
    token = authorization[7:].strip()
    if not token:
        raise PermissionError("MCP Bearer Token 为空")
    principal = auth.verify_access(token)
    return RequestContext(
        trace_id=str(getattr(ctx, "request_id", "")),
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        roles=principal.roles,
        permissions=principal.permissions,
        authenticated=True,
        expires_at=(principal.expires_at.isoformat() if principal.expires_at else None),
        department_ids=principal.department_ids,
    )


def build_server(service, *, auth=None, policy: McpPolicy | None = None,
                rate_limiter=None) -> "MCPServer":
    """Create an MCP server with verified identity and optional rate limiting."""
    from mcp.server.mcpserver import Context, MCPServer

    def request_context_and_limit(ctx, tool_name):
        context = _request_context(ctx, auth)
        if rate_limiter is not None:
            key = f"{context.tenant_id}:{context.user_id}:{tool_name}"
            if not rate_limiter.allow(key):
                raise PermissionError("MCP 请求过于频繁，请稍后重试")
        return context

    policy = policy or McpPolicy()
    tools = ChatTools(service)
    server = MCPServer(name=policy.name, version=policy.version)

    if "chat_ask" in policy.enabled_tools:
        @server.tool()
        async def chat_ask(question: str, conversation_id: str,
                           confirmed: bool = False, ctx: Context | None = None) -> dict:
            return await tools.chat_ask(
                question, conversation_id, confirmed,
                context=request_context_and_limit(ctx, "chat_ask"),
            )

    if "document_search" in policy.enabled_tools:
        @server.tool()
        async def document_search(query: str, top_k: int = 5,
                                  ctx: Context | None = None) -> dict:
            return await tools.document_search(
                query, top_k, context=request_context_and_limit(ctx, "document_search"))

    if "sop_get_step" in policy.enabled_tools:
        @server.tool()
        async def sop_get_step(query: str, conversation_id: str,
                               confirmed: bool = False,
                               ctx: Context | None = None) -> dict:
            return await tools.sop_get_step(
                query, conversation_id, confirmed,
                context=request_context_and_limit(ctx, "sop_get_step"),
            )

    if "readonly_sql_query" in policy.enabled_tools:
        @server.tool()
        async def readonly_sql_query(question: str,
                                     ctx: Context | None = None) -> dict:
            return await tools.readonly_sql_query(
                question, context=request_context_and_limit(ctx, "readonly_sql_query"))

    return server


def build_http_app(service, *, auth=None, policy: McpPolicy | None = None,
                   rate_limiter=None, path: str = "/", stateless: bool = False,
                   host: str = "127.0.0.1", max_request_body_size: int = 4 * 1024 * 1024):
    """Return a Streamable HTTP ASGI app for mounting under ``/mcp``."""
    server = build_server(service, auth=auth, policy=policy,
                          rate_limiter=rate_limiter)
    return server.streamable_http_app(
        streamable_http_path=path,
        stateless_http=stateless,
        host=host,
        max_request_body_size=max_request_body_size,
    )
