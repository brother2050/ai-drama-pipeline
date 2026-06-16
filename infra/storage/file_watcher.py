"""文件系统监控 — 基于 watchdog 库，自动失效缓存

监控角色/场景 YAML 文件变化，自动触发：
1. Config mtime 缓存失效（下次 load_config 重新读文件）
2. Pipeline ctx 缓存失效（下次 _build_ctx 重建 Config + Container）
3. ModelRegistry 单例缓存失效（下次 ModelRegistry() 重新加载 YAML）

用法（由 infra/globals.py 自动管理）：
    watcher = start_file_watcher(config_dir)
    ...
    stop_file_watcher()
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["start_file_watcher", "stop_file_watcher"]

_watcher = None
_lock = threading.Lock()


class _YAMLFileHandler:
    """监控 YAML 文件变化，触发缓存失效"""

    def __init__(self, config_dir: Path, on_change: Callable[[], None] | None = None):
        self._config_dir = config_dir
        self._on_change = on_change
        self._debounce_timer: threading.Timer | None = None
        self._debounce_delay = 1.0  # 秒，防抖动

    def _debounced_notify(self) -> None:
        """防抖通知：短时间多次变化只触发一次"""
        if self._debounce_timer:
            self._debounce_timer.cancel()
        self._debounce_timer = threading.Timer(self._debounce_delay, self._fire)
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def _fire(self) -> None:
        """执行缓存失效回调"""
        try:
            self._invalidate_caches()
            if self._on_change:
                self._on_change()
        except Exception as e:
            logger.error(f"缓存失效回调异常: {e}")

    def _invalidate_caches(self) -> None:
        """失效所有相关缓存"""
        # 1. Config mtime 缓存
        try:
            from infra.config import invalidate_config_cache
            invalidate_config_cache()
        except Exception as e:
            logger.warning(f"Config 缓存失效跳过: {e}")

        # 2. 通过 hooks 通知所有注册的缓存失效回调（pipeline 等上层模块通过 hooks 注册）
        try:
            from infra.hooks import run_hooks
            run_hooks("cache_invalidate")
        except Exception as e:
            logger.warning(f"缓存失效钩子跳过: {e}")

        # 3. ModelRegistry 单例缓存 — 重置 mtime 使下次访问自动重载
        try:
            from infra.config.registry import ModelRegistry
            with ModelRegistry._instance_lock:
                ModelRegistry._instance = None
                ModelRegistry._instance_mtime = 0.0
        except Exception as e:
            logger.warning(f"ModelRegistry 缓存失效跳过: {e}")

        logger.info("文件变化检测 → 缓存已失效")

    def on_created(self, event: Any) -> None:
        if not event.is_directory and event.src_path.endswith((".yaml", ".yml")):
            logger.info(f"检测到新文件: {Path(event.src_path).name}")
            self._debounced_notify()

    def on_modified(self, event: Any) -> None:
        if not event.is_directory and event.src_path.endswith((".yaml", ".yml")):
            logger.info(f"检测到文件修改: {Path(event.src_path).name}")
            self._debounced_notify()

    def on_deleted(self, event: Any) -> None:
        if not event.is_directory and event.src_path.endswith((".yaml", ".yml")):
            logger.info(f"检测到文件删除: {Path(event.src_path).name}")
            self._debounced_notify()


def start_file_watcher(
    config_dir: str | Path,
    on_change: Callable[[], None] | None = None,
) -> Any | None:
    """启动文件系统监控

    Args:
        config_dir: 项目配置目录（如 projects/default/config/）
        on_change: 额外的变化回调（可选）

    Returns:
        Observer 实例（或 None 如果 watchdog 不可用）
    """
    global _watcher
    with _lock:
        if _watcher is not None:
            return _watcher

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            logger.warning("watchdog 库未安装，文件变化监控已禁用。安装: pip install watchdog")
            return None

        config_dir = Path(config_dir).resolve()
        if not config_dir.exists():
            logger.warning(f"配置目录不存在，跳过文件监控: {config_dir}")
            return None

        handler = _YAMLFileHandler(config_dir, on_change)

        # 创建适配 watchdog 的事件处理器
        class _Adapter(FileSystemEventHandler):
            def on_created(self, event):
                handler.on_created(event)

            def on_modified(self, event):
                handler.on_modified(event)

            def on_deleted(self, event):
                handler.on_deleted(event)

        observer = Observer()
        # 监控配置目录本身（project.yaml, system.yaml 等顶层配置文件，ARCH-05 修复）
        observer.schedule(_Adapter(), str(config_dir), recursive=False)
        logger.info(f"文件监控已启用: {config_dir}")

        # 监控 characters/ 和 scenes/ 子目录
        for subdir in ("characters", "scenes"):
            watch_dir = config_dir / subdir
            if watch_dir.exists():
                observer.schedule(_Adapter(), str(watch_dir), recursive=False)
                logger.info(f"文件监控已启用: {watch_dir}")

        observer.daemon = True
        observer.start()
        _watcher = observer

    logger.info(f"文件系统监控已启动: {config_dir}")
    return observer


def stop_file_watcher() -> None:
    """停止文件系统监控"""
    global _watcher
    with _lock:
        if _watcher is None:
            return
        try:
            _watcher.stop()
            _watcher.join(timeout=5)
        except Exception as e:
            logger.debug(f"文件监控停止异常: {e}")
        _watcher = None
        logger.info("文件系统监控已停止")
