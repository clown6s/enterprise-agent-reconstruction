"""面向受管控 SQL schema 管理的 HTTP 适配器。

应用服务由组合根注入。这使 HTTP 适配器与存储解耦（并且允许在不改动本
API 契约的情况下新增服务/端口）。
"""
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..application.context import RequestContext
from .trace_context import resolve_trace_id


class SchemaAdminService(Protocol):
    """本路由器所期望的端口（具体实现属于应用层）。"""

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
    def list_row_policies(self, domain: str, *, context: RequestContext) -> Any: ...
    def register_row_policy(self, domain: str, request: "RowPolicyRequest",
                            *, context: RequestContext) -> Any: ...
    def delete_row_policy(self, domain: str, permission_id: int,
                          *, context: RequestContext) -> Any: ...
    def delete_domain(self, domain: str, *, context: RequestContext) -> Any: ...
    def publish(self, domain: str, request: "PublishRequest | None" = None,
                *, context: RequestContext) -> Any: ...


class PaginationSortRequest(BaseModel):
    column: str = Field(min_length=1, max_length=128)
    direction: str = Field(default="desc", pattern="^(asc|desc)$")


class PaginationConfigRequest(BaseModel):
    enabled: bool = False
    base_table: str | None = Field(default=None, max_length=128)
    sort_columns: list[PaginationSortRequest] = Field(default_factory=list, max_length=4)
    unique_key: str | None = Field(default=None, max_length=128)
    page_size: int = Field(default=5, ge=1, le=100)
    mode: str = Field(default="root", pattern="^(root|join)$")


class DomainCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4000)
    keywords: list[str] = Field(default_factory=list, max_length=100)
    pagination: PaginationConfigRequest | None = None


class TableRequest(BaseModel):
    table: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4000)
    required_tenant_filter: bool = True


class IntrospectRequest(BaseModel):
    tables: list[str] = Field(default_factory=list, max_length=500)
    include_columns: bool = True


class PublishRequest(BaseModel):
    version: int | None = Field(default=None, gt=0, le=1000000)
    comment: str = Field(default="", max_length=4000)


class ColumnEntry(BaseModel):
    column_name: str = Field(min_length=1, max_length=128)
    data_type: str = Field(min_length=1, max_length=64)
    business_name: str = ""
    description: str | None = None
    selectable: bool = True
    filterable: bool = True
    sortable: bool = False
    aggregatable: bool = False
    sensitive: bool = False
    masking_rule: str | None = None


class JoinEntry(BaseModel):
    table: str = Field(min_length=1, max_length=128)
    columns: dict[str, str] = Field(min_length=1)
    join_type: str = "INNER"


class ColumnsRequest(BaseModel):
    table: str = Field(min_length=1, max_length=128)
    columns: list[ColumnEntry] = Field(min_length=1, max_length=500)


class JoinsRequest(BaseModel):
    table: str = Field(min_length=1, max_length=128)
    joins: list[JoinEntry] = Field(default_factory=list, max_length=100)


class RowPolicyRequest(BaseModel):
    table: str = Field(min_length=1, max_length=128)
    subject_type: str = Field(min_length=1, max_length=16)
    subject_id: str = Field(min_length=1, max_length=64)
    predicate_template: str = Field(min_length=1, max_length=2000)
    allowed: bool = True


class _AnonymousPrincipal:
    tenant_id = ""
    user_id = ""
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    expires_at = None
    department_ids: tuple[str, ...] = ()


def _context(request: Request, principal: object) -> RequestContext:
    """从已认证主体构建可信上下文，绝不使用请求体中的身份信息。"""
    return RequestContext(
        trace_id=resolve_trace_id(request),
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
    """仅用于单元测试中的直接构造。"""
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
    """创建 ``/admin/schema`` 路由器。

    ``principal_provider`` 通常应由 ``main.py`` 使用
    ``make_principal_provider(auth, "schema:admin")`` 创建。这里有意采用注入方式，
    使本模块不负责认证策略。
    """
    router = APIRouter(prefix="/admin/schema", tags=["schema-admin"])
    dependency = principal_provider or _anonymous

    def principal(request: Request) -> object:
        # 即使调用方注入一个简单的
        # 无注解可调用对象（单元测试中常见），也保持 FastAPI 签名稳定。
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

    @router.get("/domains/{domain}/policies")
    def list_row_policies(domain: str, request: Request,
                          schema: SchemaAdminService = Depends(service),
                          principal: object = Depends(principal)):
        return _jsonable(schema.list_row_policies(domain, context=_context(request, principal)))

    @router.post("/domains/{domain}/policies")
    def register_row_policy(domain: str, body: RowPolicyRequest, request: Request,
                            schema: SchemaAdminService = Depends(service),
                            principal: object = Depends(principal)):
        return _jsonable(schema.register_row_policy(domain, body, context=_context(request, principal)))

    @router.delete("/domains/{domain}/policies/{permission_id}")
    def delete_row_policy(domain: str, permission_id: int, request: Request,
                          schema: SchemaAdminService = Depends(service),
                          principal: object = Depends(principal)):
        return _jsonable(schema.delete_row_policy(domain, permission_id,
                                                  context=_context(request, principal)))

    @router.delete("/domains/{domain}")
    def delete_domain(domain: str, request: Request,
                      schema: SchemaAdminService = Depends(service),
                      principal: object = Depends(principal)):
        return _jsonable(schema.delete_domain(domain,
                                              context=_context(request, principal)))

    return router
