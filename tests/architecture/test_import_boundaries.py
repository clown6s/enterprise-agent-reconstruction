from pathlib import Path

ROOT = Path(__file__).parents[2] / "app" / "ingestion"


def test_domain_has_no_infrastructure_imports():
    forbidden = ("fastapi", "pymilvus", "pymysql", "neo4j", "httpx")
    for path in (ROOT / "domain").glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert not any(f"import {name}" in text or f"from {name}" in text for name in forbidden), path


def test_application_has_no_framework_imports():
    for path in (ROOT / "application").glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "fastapi" not in text and "pymilvus" not in text and "pymysql" not in text, path
