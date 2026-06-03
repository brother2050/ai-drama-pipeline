"""数据库连接池 — PostgreSQL（必须）"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()


class PgPool:
    """PostgreSQL 连接池"""

    def __init__(self, dsn: str, minconn: int = 1, maxconn: int = 20):
        from psycopg2 import pool as pg_pool
        self._pool = pg_pool.ThreadedConnectionPool(minconn, maxconn, dsn)
        from infra.database.schema import init_schema
        conn = self._pool.getconn()
        try:
            init_schema(conn)
        finally:
            self._pool.putconn(conn)

    def connect(self):
        conn = self._pool.getconn()
        if getattr(conn, 'closed', False):
            self._put(conn, close=True)
            return self._pool.getconn()
        return conn

    def _put(self, conn, close: bool = False):
        try:
            self._pool.putconn(conn, close=close)
        except Exception:
            logger.debug("连接归还失败")
            pass

    def release(self, conn):
        self._pool.putconn(conn)

    @contextmanager
    def connection(self):
        """连接上下文管理器 — 异常时自动 rollback"""
        conn = self.connect()
        try:
            yield conn
        except Exception:
            try:
                conn.rollback()
            except Exception:
                logger.debug("事务回滚失败")
                pass
            raise
        finally:
            self.release(conn)

    def close(self):
        self._pool.closeall()


def get_pool() -> PgPool:
    """获取 PostgreSQL 连接池（单例）"""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
        if not dsn:
            raise RuntimeError(
                "AI_DRAMA_DB_DSN 未配置。\n"
                "示例: AI_DRAMA_DB_DSN=postgresql://drama:drama123@127.0.0.1:5432/ai_drama"
            )
        maxconn_str = os.environ.get("AI_DRAMA_DB_MAXCONN", "20")
        try:
            maxconn = int(maxconn_str)
        except (ValueError, TypeError):
            maxconn = 20
        _pool = PgPool(dsn, maxconn=maxconn)
        logger.info(f"PostgreSQL 连接池已初始化 (maxconn={maxconn})")
    return _pool


def placeholder() -> str:
    return "%s"
