import os

from app.ingestion.bootstrap import container as container_module


def test_uses_noop_when_env_missing(monkeypatch):
    monkeypatch.setattr(container_module, "load_dotenv", lambda *a: None)
    for key in ("SILICONFLOW_API_KEY", "MILVUS_HOST"):
        monkeypatch.delenv(key, raising=False)
    service = container_module.build_ingestion()
    assert type(service.embedder).__name__ == "_NoopEmbedder"
    assert type(service.vectors).__name__ == "_NoopVectors"


def test_selects_siliconflow_when_env_configured(monkeypatch):
    monkeypatch.setattr(container_module, "load_dotenv", lambda *a: None)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    monkeypatch.delenv("MILVUS_HOST", raising=False)
    service = container_module.build_ingestion()
    assert type(service.embedder).__name__ == "SiliconFlowEmbedder"
    assert type(service.vectors).__name__ == "_NoopVectors"


def test_selects_milvus_when_host_configured(monkeypatch):
    monkeypatch.setattr(container_module, "load_dotenv", lambda *a: None)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.setenv("MILVUS_HOST", "10.0.0.1")

    class _FakeMilvus:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(container_module, "MilvusVectorStore", _FakeMilvus)
    service = container_module.build_ingestion()
    assert type(service.embedder).__name__ == "_NoopEmbedder"
    assert type(service.vectors).__name__ == "_FakeMilvus"