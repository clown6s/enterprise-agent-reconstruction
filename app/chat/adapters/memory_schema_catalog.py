"""In-memory schema catalog; production can replace it with a governed store."""
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
        """Per-table column allowlist; {} means no column-level restriction."""
        item = self._domains.get(domain)
        if item is None or not item.columns:
            return {}
        return {table: set(cols) for table, cols in item.columns.items()}

    def blocked_columns(self, domain: str, *, context=None) -> dict[str, set[str]]:
        return {}

    def row_policies(self, domain: str, table_name: str, *, context=None) -> tuple:
        """The memory catalog intentionally has no row-policy storage."""
        return ()

    def domain_limits(self, domain: str, *, context=None) -> tuple[int, int]:
        return 1000, 10

    def resolve_domain(self, query: str, *, context=None) -> str | None:
        lowered = query.lower()
        for item in self._domains.values():
            if any(keyword.lower() in lowered for keyword in item.keywords):
                return item.name
        return None
