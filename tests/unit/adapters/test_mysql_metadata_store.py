from app.ingestion.adapters.mysql_metadata_store import MySQLMetadataStore
from app.ingestion.domain.models import DocumentSource


class _FakeCursor:
    def __init__(self, store):
        self._store = store
        self._executed = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self._executed.append((sql, params))
        if sql.startswith("SELECT"):
            self._row = self._store._rows.get(self._store._last_digest)

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, store):
        self._store = store
        self.closed = False

    def cursor(self):
        return _FakeCursor(self._store)

    def commit(self):
        self._store._commits += 1

    def rollback(self):
        self._store._rollbacks += 1

    def ping(self, reconnect=True):
        return True

    def close(self):
        self.closed = True


def _make_store():
    store = MySQLMetadataStore.__new__(MySQLMetadataStore)
    store._rows = {}
    store._last_digest = None
    store._table = "ingestion_documents"
    store._commits = 0
    store._rollbacks = 0
    store._pool = None
    return store


def _record(store, digest="abc", doc_id="doc1"):
    conn = _FakeConn(store)
    store._last_digest = digest
    store._rows[digest] = {"docId": doc_id, "chunks": 5}
    return conn


def test_find_by_sha_maps_columns(monkeypatch):
    store = _make_store()
    conn = _record(store, digest="sha123", doc_id="d1")
    monkeypatch.setattr(store, "_acquire", lambda: conn)
    monkeypatch.setattr(store, "_release", lambda c: None)
    result = store.find_by_sha("sha123")
    assert result == {"docId": "d1", "chunks": 5}


def test_find_by_sha_returns_none_when_missing(monkeypatch):
    store = _make_store()
    conn = _FakeConn(store)

    monkeypatch.setattr(store, "_acquire", lambda: conn)
    monkeypatch.setattr(store, "_release", lambda c: None)
    assert store.find_by_sha("missing") is None