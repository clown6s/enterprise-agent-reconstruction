"""In-memory schema catalog; production can replace it with a governed store."""
from dataclasses import dataclass

from ..application.ports import SchemaCatalog


@dataclass(frozen=True)
class SchemaDomain:
    name: str
    description: str
    tables: frozenset[str]
    keywords: tuple[str, ...] = ()


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

    def resolve_domain(self, query: str, *, context=None) -> str | None:
        lowered = query.lower()
        for item in self._domains.values():
            if any(keyword.lower() in lowered for keyword in item.keywords):
                return item.name
        return None
