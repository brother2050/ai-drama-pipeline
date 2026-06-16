"""数据库共享工具 — 单一数据源，所有 DB 模块共用"""
from __future__ import annotations

__all__ = ["project_scope", "_reset_project_cache", "query", "row_to_dict", "safe_float", "_get_project"]

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

import psycopg2.extras

# ── 项目自动解析 ──
from infra.config import get_root as _get_root, get_active_project_dir as _get_active_project_dir

_ROOT = _get_root()

_project_cache: str | None = None
_project_mtime: float = 0.0
_project_cache_lock = threading.Lock()

# 线程本地存储：project_scope 使用 per-thread 上下文，避免多线程互相覆盖
_thread_local = threading.local()


def _active_file() -> Path:
    return _ROOT / "projects" / ".active"


def _get_project() -> str:
    """获取当前项目名。优先级：线程本地 project_scope > 全局缓存。"""
    # 线程本地覆盖（project_scope 设置）
    scoped = getattr(_thread_local, "project", None)
    if scoped is not None:
        return scoped
    # 全局缓存（.active 文件）
    global _project_cache, _project_mtime
    af = _active_file()
    try:
        mtime = os.path.getmtime(af)
    except OSError:
        mtime = 0.0
    with _project_cache_lock:
        if _project_cache is not None and _project_mtime == mtime:
            return _project_cache
        try:
            _project_cache = _get_active_project_dir(_ROOT).name
        except Exception:
            _project_cache = "default"
        _project_mtime = mtime
        return _project_cache


def _reset_project_cache() -> None:
    """清除项目缓存（项目切换后调用）"""
    global _project_cache, _project_mtime
    with _project_cache_lock:
        _project_cache = None
        _project_mtime = 0.0


@contextmanager
def project_scope(project: str) -> Generator[None, None, None]:
    """临时切换项目上下文（线程安全，使用 threading.local）

    用法:
        with project_scope("my_project"):
            delete(pool, char_id)  # 删除 my_project 的记录
    """
    old = getattr(_thread_local, "project", None)
    _thread_local.project = project
    try:
        yield
    finally:
        if old is None:
            _thread_local.project = None
        else:
            _thread_local.project = old


def row_to_dict(row: Any) -> dict[str, Any]:
    """将数据库行转为字典（RealDictRow → dict，None → {}）"""
    if row is None:
        return {}
    return dict(row) if hasattr(row, "keys") else {}


def safe_float(val: Any, default: float = 0.0) -> float:
    """安全 float 转换，处理空字符串、非数字值、NaN、Infinity"""
    try:
        import math
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


@contextmanager
def query(pool: Any, dict_mode: bool = False, commit: bool = True) -> Generator[Any, None, None]:
    """查询/写入上下文管理器 — 自动管理连接、游标、提交。

    用法:
        # 查询
        with query(pool, dict_mode=True) as cur:
            cur.execute("SELECT ...")
            rows = [row_to_dict(r) for r in cur.fetchall()]

        # 写入（自动 commit）
        with query(pool) as cur:
            cur.execute("INSERT ...")

        # 只读（不 commit）
        with query(pool, commit=False) as cur:
            cur.execute("SELECT ...")
    """
    with pool.connection() as conn:
        cur = None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if dict_mode else conn.cursor()
            yield cur
            if commit:
                conn.commit()
        finally:
            if cur is not None:
                cur.close()
