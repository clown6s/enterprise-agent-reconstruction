"""Framework-agnostic request context for traceability and identity."""
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    """Carries tracing and identity across the chat application.

    Created by HTTP / MCP adapters from verified authentication; never derived
    from user input, document text, history, or LLM output.
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
    """Return trusted (tenant_id, user_id), raising if absent or unauthenticated."""
    if ctx is None or not getattr(ctx, "authenticated", False):
        from ..domain.exceptions import ValidationError
        raise ValidationError("请求未认证，无法访问数据")
    tenant_id = getattr(ctx, "tenant_id", "") or ""
    user_id = getattr(ctx, "user_id", "") or ""
    if not tenant_id or not user_id:
        from ..domain.exceptions import ValidationError
        raise ValidationError("请求缺少租户或用户身份")
    return tenant_id, user_id