"""内存 Schema catalog；生产环境可替换为受管控的存储。"""
from dataclasses import dataclass

from ..application.ports import SchemaCatalog


@dataclass(frozen=True)
class SchemaDomain:
    name: str
    description: str
    tables: frozenset[str]
    keywords: tuple[str, ...] = ()
    columns: dict[str, frozenset[str]] | None = None


class MemorySchemaCatalog(SchemaCatalog):
    def __init__(self, domains: list[SchemaDomain] | None = None):
        self._domains = {item.name: item for item in (domains or [])}

    def register(self, domain: SchemaDomain) -> None:
        self._domains[domain.name] = domain

    def domains(self, *, context=None) -> list[str]:
        return list(self._domains)

    def describe(self, domain: str, *, context=None) -> str:
        item = self._domains.get(domain)
        return item.description if item else ""

    def allowed_tables(self, domain: str, *, context=None) -> set[str]:
        item = self._domains.get(domain)
        return set(item.tables) if item else set()

    def allowed_columns(self, domain: str, *, context=None) -> dict[str, set[str]]:
        """按表维护的列白名单；空字典表示不限制列级访问。"""
        item = self._domains.get(domain)
        if item is None or not item.columns:
            return {}
        return {table: set(cols) for table, cols in item.columns.items()}

    def blocked_columns(self, domain: str, *, context=None) -> dict[str, set[str]]:
        return {}

    def row_policies(self, domain: str, table_name: str, *, context=None) -> tuple:
        """内存 catalog 按设计不保存行级权限策略。"""
        return ()

    def domain_limits(self, domain: str, *, context=None) -> tuple[int, int]:
        return 1000, 10

    def resolve_domain(self, query: str, *, context=None) -> str | None:
        lowered = query.lower()
        for item in self._domains.values():
            if any(keyword.lower() in lowered for keyword in item.keywords):
                return item.name
        return None
