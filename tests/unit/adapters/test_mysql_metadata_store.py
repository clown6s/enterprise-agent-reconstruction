import threading

import pymysql

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
    store._lock = threading.Lock()
    store._ddl_done = True  # 跳过 DDL，测试聚焦业务逻辑
    return store


def _record(store, digest="abc", doc_id="doc1"):
    conn = _FakeConn(store)
    store._last_digest = digest
    store._rows[digest] = {"docId": doc_id, "chunks": 5}
    return conn


class _ClaimConn:
    """模拟 claim 的 INSERT/UPDATE：依据既有状态决定行为与 rowcount。"""

    def __init__(self, existing_status=None):
        self.closed = False
        self.rollbacks = 0
        self.rowcount = None
        self._existing_status = existing_status

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("INSERT"):
            if self._existing_status is not None:
                raise pymysql.err.IntegrityError("duplicate")
            return 1
        if sql.startswith("UPDATE"):
            # 只有 status IN ('failed','processing') 才会命中。
            self.rowcount = 1 if self._existing_status in ("failed", "processing") else 0
            return self.rowcount

    def commit(self):
        pass

    def rollback(self):
        self.rollbacks += 1


def _claim_store(conn):
    store = MySQLMetadataStore.__new__(MySQLMetadataStore)
    store._table = "ingestion_documents"
    store._rows = {}
    store._last_digest = None
    store._acquire = lambda: conn
    store._release = lambda c: None
    store._lock = threading.Lock()
    store._ddl_done = True
    return store


def test_claim_returns_true_when_no_record(monkeypatch):
    conn = _ClaimConn(existing_status=None)
    store = _claim_store(conn)
    assert store.claim("sha", "doc", DocumentSource("a.txt", b"", title="A")) is True


def test_claim_false_when_already_ingested(monkeypatch):
    conn = _ClaimConn(existing_status="ingested")
    store = _claim_store(conn)
    assert store.claim("sha", "doc", DocumentSource("a.txt", b"", title="A")) is False
    assert conn.rowcount == 0


def test_claim_retries_failed_record(monkeypatch):
    conn = _ClaimConn(existing_status="failed")
    store = _claim_store(conn)
    assert store.claim("sha", "doc", DocumentSource("a.txt", b"", title="A")) is True
    assert conn.rowcount == 1


def test_claim_resets_processing_record(monkeypatch):
    conn = _ClaimConn(existing_status="processing")
    store = _claim_store(conn)
    assert store.claim("sha", "doc", DocumentSource("a.txt", b"", title="A")) is True
    assert conn.rowcount == 1


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