from pathlib import Path

APP = Path(__file__).parents[2] / "app"
INGESTION = APP / "ingestion"
CHAT = APP / "chat"

_FORBIDDEN = ("fastapi", "pymilvus", "pymysql", "neo4j", "httpx")


def _has_forbidden(text: str, names=_FORBIDDEN) -> bool:
    return any(f"import {name}" in text or f"from {name}" in text for name in names)


def test_domain_has_no_infrastructure_imports():
    for root in (INGESTION / "domain", CHAT / "domain"):
        for path in root.glob("*.py"):
            assert not _has_forbidden(path.read_text(encoding="utf-8").lower()), path


def test_application_has_no_framework_imports():
    for root in (INGESTION / "application", CHAT / "application"):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            assert "fastapi" not in text and "pymilvus" not in text and "pymysql" not in text, path


def test_chat_application_has_no_ingestion_imports():
    """chat application must not couple to ingestion; only adapters/boundary may."""
    for path in (CHAT / "application").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "app.ingestion" not in text, path


def test_chat_domain_application_do_not_import_mcp():
    """MCP SDK must only live in the mcp adapter boundary, never domain/application."""
    for root in (CHAT / "domain", CHAT / "application"):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            assert "import mcp" not in text and "from mcp" not in text, path


def test_mcp_boundary_imports_application_not_ingestion():
    """mcp/ is an adapter; it may import chat application/domain and mcp SDK,
    but must not import ingestion implementation directly."""
    for path in (CHAT / "mcp").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "app.ingestion" not in text, path
