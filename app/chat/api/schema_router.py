"""HTTP adapter for governed SQL schema administration.

The application service is injected by the composition root.  This keeps the
HTTP adapter independent of storage (and allows the service/port to be added
without changing this API contract).
"""
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..application.context import RequestContext


class SchemaAdminService(Protocol):
    """Port expected by this router (implementations belong to application)."""

    def list_domains(self, *, context: RequestContext) -> Any: ...
    def create_domain(self, request: "DomainCreateRequest", *, context: RequestContext) -> Any: ...
    def list_tables(self, domain: str, *, context: RequestContext) -> Any: ...
    def register_table(self, domain: str, request: "TableRequest",
                       *, context: RequestContext) -> Any: ...
    def introspect(self, domain: str, request: "IntrospectRequest | None" = None,
                   *, context: RequestContext) -> Any: ...
    def list_columns(self, domain: str, table: str, *, context: RequestContext) -> Any: ...
    def list_joins(self, domain: str, *, context: RequestContext) -> Any: ...
    def register_columns(self, domain: str, request: "ColumnsRequest",
                         *, context: RequestContext) -> Any: ...
    def register_joins(self, domain: str, request: "JoinsRequest",
                       *, context: RequestContext) -> Any: ...
    def publish(self, domain: str, request: "PublishRequest | None" = None,
                *, context: RequestContext) -> Any: ...


class DomainCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4000)
    keywords: list[str] = Field(default_factory=list, max_length=100)


class TableRequest(BaseModel):
    table: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4000)
    required_tenant_filter: bool = True


class IntrospectRequest(BaseModel):
    tables: list[str] = Field(default_factory=list, max_length=500)
    include_columns: bool = True


class PublishRequest(BaseModel):
    version: str | None = Field(default=None, max_length=64)
    comment: str = Field(default="", max_length=4000)


class ColumnsRequest(BaseModel):
    table: str = Field(min_length=1, max_length=128)
    columns: list[dict] = Field(min_length=1, max_length=500)


class JoinsRequest(BaseModel):
    table: str = Field(min_length=1, max_length=128)
    joins: list[dict] = Field(default_factory=list, max_length=100)


class _AnonymousPrincipal:
    tenant_id = ""
    user_id = ""
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    expires_at = None
    department_ids: tuple[str, ...] = ()


def _context(request: Request, principal: object) -> RequestContext:
    """Build trusted context from the authenticated principal, never the body."""
    return RequestContext(
        trace_id=request.headers.get("X-Trace-Id", "") or "",
        tenant_id=getattr(principal, "tenant_id", ""),
        user_id=getattr(principal, "user_id", ""),
        roles=tuple(getattr(principal, "roles", ()) or ()),
        permissions=tuple(getattr(principal, "permissions", ()) or ()),
        authenticated=True,
        expires_at=(getattr(principal, "expires_at", None).isoformat()
                    if getattr(principal, "expires_at", None) else None),
        department_ids=tuple(getattr(principal, "department_ids", ()) or ()),
    )


def _anonymous(_request: Request) -> object:
    """Only useful for direct construction in unit tests."""
    return _AnonymousPrincipal()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def create_router(service_provider: Callable[[], SchemaAdminService],
                  principal_provider: Callable[[Request], object] | None = None) -> APIRouter:
    """Create the ``/admin/schema`` router.

    ``principal_provider`` should normally be created with
    ``make_principal_provider(auth, "schema:admin")`` by ``main.py``.  It is
    intentionally injected so this module does not own authentication policy.
    """
    router = APIRouter(prefix="/admin/schema", tags=["schema-admin"])
    dependency = principal_provider or _anonymous

    def principal(request: Request) -> object:
        # Keep the FastAPI signature stable even when callers inject a simple
        # unannotated callable (common in unit tests).
        return dependency(request)

    def service() -> SchemaAdminService:
        return service_provider()

    @router.get("/domains")
    def domains(request: Request, schema: SchemaAdminService = Depends(service),
                principal: object = Depends(principal)):
        return _jsonable(schema.list_domains(context=_context(request, principal)))

    @router.post("/domains")
    def create_domain(body: DomainCreateRequest, request: Request,
                      schema: SchemaAdminService = Depends(service),
                      principal: object = Depends(principal)):
        return _jsonable(schema.create_domain(body, context=_context(request, principal)))

    @router.get("/domains/{domain}/tables")
    def tables(domain: str, request: Request, schema: SchemaAdminService = Depends(service),
               principal: object = Depends(principal)):
        return _jsonable(schema.list_tables(domain, context=_context(request, principal)))

    @router.post("/domains/{domain}/tables")
    def register_table(domain: str, body: TableRequest, request: Request,
                       schema: SchemaAdminService = Depends(service),
                       principal: object = Depends(principal)):
        return _jsonable(schema.register_table(domain, body, context=_context(request, principal)))

    @router.post("/domains/{domain}/introspect")
    def introspect(domain: str, request: Request, body: IntrospectRequest | None = None,
                   schema: SchemaAdminService = Depends(service),
                   principal: object = Depends(principal)):
        return _jsonable(schema.introspect(domain, body, context=_context(request, principal)))

    @router.get("/domains/{domain}/tables/{table}/columns")
    def columns(domain: str, table: str, request: Request,
                schema: SchemaAdminService = Depends(service),
                principal: object = Depends(principal)):
        return _jsonable(schema.list_columns(domain, table, context=_context(request, principal)))

    @router.get("/domains/{domain}/joins")
    def joins(domain: str, request: Request, schema: SchemaAdminService = Depends(service),
              principal: object = Depends(principal)):
        return _jsonable(schema.list_joins(domain, context=_context(request, principal)))

    @router.post("/domains/{domain}/publish")
    def publish(domain: str, request: Request, body: PublishRequest | None = None,
                schema: SchemaAdminService = Depends(service),
                principal: object = Depends(principal)):
        return _jsonable(schema.publish(domain, body, context=_context(request, principal)))

    @router.post("/domains/{domain}/columns")
    def register_columns(domain: str, body: ColumnsRequest, request: Request,
                         schema: SchemaAdminService = Depends(service),
                         principal: object = Depends(principal)):
        return _jsonable(schema.register_columns(domain, body, context=_context(request, principal)))

    @router.post("/domains/{domain}/joins")
    def register_joins(domain: str, body: JoinsRequest, request: Request,
                       schema: SchemaAdminService = Depends(service),
                       principal: object = Depends(principal)):
        return _jsonable(schema.register_joins(domain, body, context=_context(request, principal)))

    return router
