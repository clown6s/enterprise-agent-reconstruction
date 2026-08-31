"""Framework-agnostic request context for traceability and identity."""
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class RequestContext:
    """Carries tracing and (optional) identity across the chat application.

    Created by HTTP / MCP / script adapters; never derived from user input.
    ``tenant_id``/``user_id`` are reserved until real authentication lands.
    """
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    user_id: str = ""
    roles: tuple[str, ...] = ()