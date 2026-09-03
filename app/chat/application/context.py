"""与框架无关的请求上下文，用于追踪和身份传递。"""
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    """在聊天应用各层之间传递追踪信息和身份。

    由 HTTP / MCP 适配器根据已验证的认证信息创建，绝不从用户输入、文档文本、
    历史记录或 LLM 输出中推导。
    """
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    user_id: str = ""
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    authenticated: bool = False
    expires_at: str | None = None
    department_ids: tuple[str, ...] = ()

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def identity(ctx) -> tuple[str, str]:
    """返回可信的（tenant_id、user_id），缺失或未认证时抛出异常。"""
    if ctx is None or not getattr(ctx, "authenticated", False):
        from ..domain.exceptions import ValidationError
        raise ValidationError("请求未认证，无法访问数据")
    tenant_id = getattr(ctx, "tenant_id", "") or ""
    user_id = getattr(ctx, "user_id", "") or ""
    if not tenant_id or not user_id:
        from ..domain.exceptions import ValidationError
        raise ValidationError("请求缺少租户或用户身份")
    return tenant_id, user_id