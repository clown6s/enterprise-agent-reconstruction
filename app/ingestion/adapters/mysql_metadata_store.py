"""MySQL 元数据存储适配器（实现 MetadataStore 端口）。

使用基于 queue 的轻量连接池，业务层只依赖 MetadataStore 接口，
不感知连接协议或资源生命周期。
"""
import queue
import re
import threading
from functools import wraps

import pymysql

from ..application.ports import MetadataStore
from ..domain.exceptions import MetadataStoreError
from ..domain.models import DocumentSource


def _wrap_mysql_errors(fn):
    """把 MySQL 业务方法抛出的异常统一封装成 MetadataStoreError。

    仅包装会与数据库交互的公共方法；构造时的参数校验（ValueError）
    留在 __init__ 中，不被误判为基础设施故障。
    """
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except MetadataStoreError:
            raise
        except Exception as exc:
            raise MetadataStoreError(f"元数据存储(MySQL)调用失败: {type(exc).__name__}") from exc
    return wrapper


class MySQLMetadataStore:
    """基于 pymysql 连接池的文档元数据存储，用于 SHA-256 去重。"""

    def __init__(self, *, host: str, port: int, user: str, password: str,
                 database: str, min_pool: int = 1, max_pool: int = 8,
                 table: str = "ingestion_documents", connect_timeout: float = 10.0):
        self._host, self._port = host, int(port)
        self._user, self._password, self._database = user, password, database
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", table):
            raise ValueError("非法 MySQL 表名")
        self._table = table
        self._min_pool = max(0, int(min_pool))
        self._max_pool = int(max_pool)
        if self._min_pool > self._max_pool or self._max_pool < 1:
            raise ValueError("MySQL 连接池参数无效：需满足 0 <= min_pool <= max_pool")
        self._connect_timeout = connect_timeout
        self._pool: queue.Queue = queue.Queue(maxsize=self._max_pool)
        self._created = 0
        self._active = 0
        self._closed = False
        self._ddl_done = False
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

    def _connect(self) -> pymysql.Connection:
        return pymysql.connect(
            host=self._host, port=self._port, user=self._user,
            password=self._password, database=self._database,
            charset="utf8mb4", connect_timeout=self._connect_timeout,
            cursorclass=pymysql.cursors.DictCursor, autocommit=False,
        )

    def _acquire(self) -> pymysql.Connection:
        with self._lock:
            if self._closed:
                raise RuntimeError("MySQL 元数据存储已关闭")
        try:
            conn = self._pool.get_nowait()
            try:
                conn.ping()
            except Exception:
                self._close(conn)
                with self._lock:
                    self._created = max(0, self._created - 1)
                try:
                    conn = self._connect()
                    with self._lock:
                        self._created += 1
                except Exception:
                    raise
            with self._lock:
                self._active += 1
            return conn
        except queue.Empty:
            with self._lock:
                if self._created < self._max_pool:
                    try:
                        conn = self._connect()
                    except Exception:
                        raise
                    self._created += 1
                    self._active += 1
                    return conn
            conn = self._pool.get(timeout=30.0)
            with self._lock:
                self._active += 1
            return conn

    def _release(self, conn) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()
            if self._closed:
                self._close(conn)
                return
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            self._close(conn)
            with self._lock:
                self._created = max(0, self._created - 1)

    @staticmethod
    def _close(conn) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def _create_table_if_missing(self, conn) -> None:
        with self._lock:
            if self._ddl_done:
                return
        sql = f"""
            CREATE TABLE IF NOT EXISTS `{self._table}` (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                document_id VARCHAR(64) NOT NULL,
                sha256 CHAR(64) NOT NULL,
                filename VARCHAR(512) NOT NULL DEFAULT '',
                title VARCHAR(512) NOT NULL DEFAULT '',
                content_type VARCHAR(128) NOT NULL DEFAULT '',
                file_size BIGINT UNSIGNED NOT NULL DEFAULT 0,
                chunk_count INT UNSIGNED NOT NULL DEFAULT 0,
                status VARCHAR(32) NOT NULL DEFAULT 'ingested',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uk_document_id (document_id),
                UNIQUE KEY uk_sha256 (sha256)
            ) ENGINE=InnoDB
              DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
        with conn.cursor() as cursor:
            cursor.execute(sql)
        conn.commit()
        with self._lock:
            self._ddl_done = True

    @_wrap_mysql_errors
    def find_by_document_id(self, document_id: str) -> dict | None:
        conn = self._acquire()
        try:
            self._create_table_if_missing(conn)
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT sha256, filename FROM `{self._table}` WHERE document_id=%s LIMIT 1", (document_id,))
                return cursor.fetchone() or None
        finally:
            self._release(conn)

    @_wrap_mysql_errors
    def find_by_sha(self, digest: str) -> dict | None:
        conn = self._acquire()
        try:
            self._create_table_if_missing(conn)
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT document_id AS docId, chunk_count AS chunks, status "
                    f"FROM `{self._table}` WHERE sha256 = %s LIMIT 1",
                    (digest,),
                )
                row = cursor.fetchone()
            return row or None
        finally:
            self._release(conn)

    @_wrap_mysql_errors
    def claim(self, digest: str, document_id: str, source: DocumentSource) -> bool:
        """幂等认领摘要：允许对 failed/进行中的记录重新认领重试。

        单机部署下不维护跨实例租约；仅靠 sha256 唯一键去重，并让失败记录
        可被下次重试覆盖。
        """
        conn = self._acquire()
        try:
            self._create_table_if_missing(conn)
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        f"INSERT INTO `{self._table}` (document_id, sha256, filename, title, content_type, file_size, status) "
                        "VALUES (%s, %s, %s, %s, %s, %s, 'processing')",
                        (document_id, digest, source.filename, source.title,
                         source.content_type or "", source.size),
                    )
                    conn.commit()
                    return True
                except pymysql.err.IntegrityError:
                    conn.rollback()
                    # 已存在：ingested 记录不会被命中（返回 False，上层判 DUPLICATE）；
                    # failed/processing 记录重置为 processing，允许重试。
                    cursor.execute(
                        f"UPDATE `{self._table}` SET status='processing', updated_at=CURRENT_TIMESTAMP "
                        f"WHERE sha256=%s AND status IN ('failed','processing')",
                        (digest,),
                    )
                    claimed = cursor.rowcount == 1
                    conn.commit()
                    return claimed
        except Exception:
            conn.rollback()
            raise
        finally:
            self._release(conn)

    @_wrap_mysql_errors
    def record(self, digest: str, document_id: str, source: DocumentSource, chunks: int) -> None:
        conn = self._acquire()
        try:
            self._create_table_if_missing(conn)
            with conn.cursor() as cursor:
                cursor.execute(
                    f"UPDATE `{self._table}` SET status='ingested', chunk_count=%s WHERE sha256=%s AND document_id=%s AND status='processing'",
                    (chunks, digest, document_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("文档状态更新失败：不存在对应的 processing 记录")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._release(conn)

    @_wrap_mysql_errors
    def record_legacy(self, digest: str, document_id: str, source: DocumentSource, chunks: int) -> None:
        conn = self._acquire()
        try:
            self._create_table_if_missing(conn)
            with conn.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO `{self._table}` "
                    f"(document_id, sha256, filename, title, content_type, file_size, chunk_count, status) "
                    f"VALUES (%s, %s, %s, %s, %s, %s, %s, 'ingested')",
                    (document_id, digest, source.filename, source.title,
                     source.content_type or "", source.size, chunks),
                )
            conn.commit()
        except pymysql.err.IntegrityError:
            conn.rollback()
            self._release(conn)
            raise
        except Exception:
            try:
                conn.rollback()
            finally:
                self._release(conn)
            raise
        else:
            self._release(conn)

    @_wrap_mysql_errors
    def mark_failed(self, digest: str, document_id: str) -> None:
        conn = self._acquire()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"UPDATE `{self._table}` SET status='failed' WHERE sha256=%s AND document_id=%s",
                    (digest, document_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._release(conn)

    @_wrap_mysql_errors
    def delete_by_document_id(self, document_id: str) -> int:
        conn = self._acquire()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM `{self._table}` WHERE document_id = %s", (document_id,))
            conn.commit()
            return max(cursor.rowcount, 0)
        except Exception:
            conn.rollback()
            raise
        finally:
            self._release(conn)

    def close(self, wait: bool = True) -> None:
        with self._condition:
            self._closed = True
            if wait:
                # 等待活动连接归还后再关闭；调用方需要保证最终 release。
                self._condition.wait_for(lambda: self._active == 0, timeout=30.0)
        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                break
            self._close(conn)