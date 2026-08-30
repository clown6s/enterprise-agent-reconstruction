"""同义词集管理适配器的单元测试：验证增删改查与重新加载的调用顺序。"""
import pytest

from app.ingestion.adapters.elasticsearch_synonyms import ElasticsearchSynonyms


class _FakeSynonymsClient:
    """在内存中模拟 Elasticsearch synonyms API 的增删改查与 reload。"""

    def __init__(self, rules=None):
        self.sets = {"default": [dict(r) for r in (rules or [])]}
        self.put_sets = []
        self.reloaded = None

    def get_synonyms_sets(self):
        return {"count": len(self.sets), "results": [
            {"synonyms_set": sid, "count": len(rules)}
            for sid, rules in self.sets.items()]}

    def get_synonym(self, id):
        if id not in self.sets:
            raise KeyError(f"同义词集不存在: {id}")
        return {"synonyms_set": [dict(r) for r in self.sets[id]]}

    def put_synonym(self, id, synonyms_set=None):
        self.sets[id] = [dict(r) for r in synonyms_set]
        self.put_sets.append([dict(r) for r in synonyms_set])

    def delete_synonym(self, id):
        if id not in self.sets:
            raise KeyError(f"同义词集不存在: {id}")
        self.sets.pop(id)

    def get_index(self):
        pass


class _FakeIndices:
    def __init__(self, client):
        self._client = client

    def reload_search_analyzers(self, index):
        self._client.reloaded = index


class _FakeRootClient:
    """暴露 .synonyms（规则）与 .indices（reload）供适配器使用。"""

    def __init__(self, rules=None):
        self._synonyms = _FakeSynonymsClient(rules)
        self.synonyms = self._synonyms
        self.indices = _FakeIndices(self._synonyms)


def _store(rules=None):
    client = _FakeRootClient(rules)
    store = ElasticsearchSynonyms.__new__(ElasticsearchSynonyms)
    store._client = client
    store._index = "document_chunks"
    store._set = "default"
    return store, client


def test_list_returns_current_rules():
    store, _ = _store([{"id": "a", "synonyms": "x => y"}])
    assert store.list_rules() == [{"id": "a", "synonyms": "x => y"}]


def test_add_appends_rule_and_reloads():
    store, client = _store([{"id": "a", "synonyms": "x => y"}])
    store.add_rule("b", "m => n")
    assert sorted(r["id"] for r in client._synonyms.sets["default"]) == ["a", "b"]
    assert client._synonyms.reloaded == "document_chunks"


def test_add_rejects_duplicate_id():
    store, _ = _store([{"id": "a", "synonyms": "x => y"}])
    with pytest.raises(ValueError, match="已存在"):
        store.add_rule("a", "z => w")


def test_update_replaces_synonyms_and_reloads():
    store, client = _store([{"id": "a", "synonyms": "x => y"}])
    store.update_rule("a", "q => r")
    assert client._synonyms.sets["default"][0]["synonyms"] == "q => r"
    assert client._synonyms.reloaded == "document_chunks"


def test_update_raises_on_missing_id():
    store, _ = _store([{"id": "a", "synonyms": "x => y"}])
    with pytest.raises(KeyError, match="不存在"):
        store.update_rule("zzz", "q => r")


def test_delete_removes_rule_and_reloads():
    store, client = _store([{"id": "a", "synonyms": "x => y"},
                            {"id": "b", "synonyms": "m => n"}])
    store.delete_rule("a")
    assert [r["id"] for r in client._synonyms.sets["default"]] == ["b"]
    assert client._synonyms.reloaded == "document_chunks"


def test_delete_raises_on_missing_id():
    store, _ = _store([{"id": "a", "synonyms": "x => y"}])
    with pytest.raises(KeyError, match="不存在"):
        store.delete_rule("zzz")


def test_replace_all_validates_duplicate_ids():
    store, _ = _store([])
    with pytest.raises(ValueError, match="重复"):
        store.replace_all([{"id": "a", "synonyms": "x => y"},
                           {"id": "a", "synonyms": "m => n"}])


def test_replace_all_validates_blank_synonyms():
    store, _ = _store([])
    with pytest.raises(ValueError):
        store.replace_all([{"id": "a", "synonyms": ""}])


def test_list_sets_returns_all_sets():
    store, client = _store()
    client._synonyms.sets["second"] = [{"id": "b", "synonyms": "m => n"}]
    sets = store.list_sets()
    ids = [s["synonyms_set"] for s in sets]
    assert "default" in ids and "second" in ids


def test_get_set_returns_named_set():
    store, client = _store([{"id": "a", "synonyms": "x => y"}])
    client._synonyms.sets["second"] = [{"id": "b", "synonyms": "m => n"}]
    assert store.get_set("second") == {"synonyms_set": [{"id": "b", "synonyms": "m => n"}]}


def test_delete_set_removes_named_set():
    store, client = _store()
    client._synonyms.sets["todelete"] = [{"id": "b", "synonyms": "m => n"}]
    store.delete_set("todelete")
    assert "todelete" not in client._synonyms.sets


def test_delete_set_raises_on_missing():
    store, _ = _store()
    with pytest.raises(KeyError):
        store.delete_set("missing")


def test_update_set_replaces_rules_of_named_set():
    store, client = _store([{"id": "a", "synonyms": "x => y"}])
    client._synonyms.sets["other"] = [{"id": "b", "synonyms": "m => n"}]
    store.update_set("other", [{"id": "c", "synonyms": "q => r"}])
    assert client._synonyms.sets["other"] == [{"id": "c", "synonyms": "q => r"}]


def test_update_set_validates_rules():
    store, _ = _store()
    with pytest.raises(ValueError):
        store.update_set("other", [{"id": "a", "synonyms": ""}])