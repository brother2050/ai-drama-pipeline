"""配置缓存与原子 I/O — YAML 加载/保存/缓存管理 + 深度合并

从 core.py 中提取缓存管理、原子写入和深度合并逻辑，
与 Config 类解耦，保持模块职责单一。
"""
from __future__ import annotations

import copy
import logging
import os
import threading
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

__all__ = ["load_config", "save_config", "save_yaml", "atomic_write_bytes",
           "invalidate_config_cache", "deep_merge", "get_mtime_safe"]

_cache: dict[str, tuple[dict, float]] = {}
_lock = threading.Lock()


def get_mtime_safe(path: str) -> float:
    """安全获取文件 mtime，文件不存在或出错时返回 0.0

    统一 mtime 获取逻辑，消除 load_config / ModelRegistry.__new__ 中的重复。
    """
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _deep_merge_into(base: dict, override: dict) -> None:
    """深度合并 override 到 base 中（就地修改 base，避免 copy.deepcopy 开销）

    供 Config._merge 内部使用（高频路径），以及 deep_merge 复用。
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge_into(base[key], value)
        else:
            base[key] = value


def deep_merge(base: dict, override: dict) -> dict:
    """深度合并 override 到 base 中（返回新 dict，不修改原对象）"""
    result = copy.deepcopy(base)
    _deep_merge_into(result, override)
    return result


# ── YAML 加载/缓存 ──────────────────────────────────────

def load_config(path: str, *, force: bool = False, readonly: bool = False) -> dict[str, Any]:
    """加载 YAML 配置（带 mtime 缓存）

    Args:
        path: YAML 文件路径
        force: 强制重新读取，忽略缓存
        readonly: 调用方承诺不修改返回值时设为 True，跳过 deepcopy（性能优化）
    """
    abspath = str(Path(path).resolve())
    if not os.path.isfile(abspath):
        logger.warning(f"配置文件不存在: {abspath}")
        return {}

    if not force and abspath in _cache:
        data, mtime = _cache[abspath]
        if get_mtime_safe(abspath) == mtime:
            return data if readonly else copy.deepcopy(data)

    with _lock:
        if not force and abspath in _cache:
            data, mtime = _cache[abspath]
            if get_mtime_safe(abspath) == mtime:
                return data if readonly else copy.deepcopy(data)
        try:
            with open(abspath, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.error(f"配置文件 YAML 格式错误: {abspath}: {e}", exc_info=True)
            data = {}
        _cache[abspath] = (data, get_mtime_safe(abspath))
    return data if readonly else copy.deepcopy(data)


def save_config(path: str, data: dict[str, Any]) -> None:
    """保存 YAML 配置（原子写入）"""
    save_yaml(path, data, sort_keys=False)
    abspath = str(Path(path).resolve())
    with _lock:
        _cache[abspath] = (copy.deepcopy(data), os.path.getmtime(abspath))


def invalidate_config_cache(path: str | None = None) -> None:
    """清除配置缓存，强制下次 load_config 重新读取文件

    Args:
        path: 指定要清除的配置文件路径。None 则清除所有缓存。
    """
    with _lock:
        if path:
            abspath = str(Path(path).resolve())
            _cache.pop(abspath, None)
        else:
            _cache.clear()
    logger.debug(f"配置缓存已清除: {path or '全部'}")


# ── 原子 I/O ───────────────────────────────────────────

def save_yaml(path: str | Path, data: Any, *, sort_keys: bool = False) -> None:
    """原子写入 YAML 文件（temp file + rename，防崩溃损坏）"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=sort_keys)
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """原子写入二进制文件（temp file + rename，防崩溃损坏）"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
