from app.ingestion.application.retrieve import RetrieveDocuments


class FakeEmbedder:
    def embed_batch(self, texts):
        return [[1.0, 2.0] for _ in texts]


class FakeVectors:
    def search(self, vector, *, top_k, filter):
        assert vector == [1.0, 2.0]
        return [{"text": "命中", "score": 0.9, "document_id": "d1",
                 "page": 3, "kind": "prose", "section_path": "[\"第一章\"]"}]


def test_retrieves_and_decodes_source_metadata():
    results = RetrieveDocuments(FakeEmbedder(), FakeVectors()).execute("问题", top_k=3)
    assert results[0].text == "命中"
    assert results[0].section_path == ("第一章",)
    assert results[0].page == 3


def test_empty_query_returns_no_results():
    assert RetrieveDocuments(FakeEmbedder(), FakeVectors()).execute("  ") == []
