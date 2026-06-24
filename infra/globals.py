"""全局基础设施实例 — 单一数据源

所有全局看门狗、健康缓存、并发组的统一入口。
进程启动时初始化一次，各模块通过 get_*() 访问。

集成 hooks 系统：init/cleanup 钩子在 init_globals/shutdown_globals 时自动执行。

用法:
    from infra.globals import get_watchdog, get_health_cache, get_concurrency_groups
    wd = get_watchdog()
    with wd.track("shot001:tts", backend="mimo"):
        tts.generate(...)
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infra.concurrency.monitor import WatchDog, HealthCache
    from infra.concurrency_groups import ConcurrencyGroups

logger = logging.getLogger(__name__)

__all__ = ["init_globals", "get_watchdog", "get_health_cache",
           "get_concurrency_groups", "shutdown_globals", "start_file_monitor", "stop_file_monitor"]

_watchdog: WatchDog | None = None
_health_cache: HealthCache | None = None
_concurrency_groups: ConcurrencyGroups | None = None
_lock = threading.Lock()
_file_monitor_config_dir: str | None = None  # 缓存 config_dir 供 start_file_monitor 使用


def init_globals(
    busy_timeout: float = 300.0,
    check_interval: float = 5.0,
    health_ttl: float = 30.0,
    comfyui_slots: int = 1,
    tts_slots: int = 2,
) -> None:
    """初始化全局实例（进程启动时调用一次）"""
    global _watchdog, _health_cache, _concurrency_groups
    with _lock:
        if _watchdog is not None:
            return  # 已初始化

        from infra.concurrency.monitor import WatchDog, HealthCache
        from infra.concurrency_groups import ConcurrencyGroups

        _watchdog = WatchDog(
            busy_timeout=busy_timeout,
            check_interval=check_interval,
            on_timeout=lambda h: logger.error(
                "[WatchDog] 任务超时告警: %s (%ss, backend=%s)", h.task_id, h.elapsed, h.backend),
        )
        _watchdog.start()

        _health_cache = HealthCache(ttl=health_ttl)

        _concurrency_groups = ConcurrencyGroups({
            "comfyui": comfyui_slots,   # ComfyUI GPU 密集，通常 1
            "tts": tts_slots,           # TTS 可以稍多
            "lipsync": 1,               # 口型同步也是 GPU 密集
            "llm": 4,                   # LLM 通常可以并行
        })

    logger.info(f"全局基础设施初始化完成: "
                 f"watchdog(busy={busy_timeout}s), "
                 f"health_cache(ttl={health_ttl}s), "
                 f"concurrency_groups(comfyui={comfyui_slots}, tts={tts_slots})")


def start_file_monitor(config_dir: str | Path) -> None:
    """启动文件系统监控（角色/场景 YAML 变化自动失效缓存）

    在 Web 启动和 Worker 启动时调用。
    """
    global _file_monitor_config_dir
    _file_monitor_config_dir = str(config_dir)
    from infra.storage.file_watcher import start_file_watcher
    start_file_watcher(config_dir)


def stop_file_monitor() -> None:
    """停止文件系统监控"""
    from infra.storage.file_watcher import stop_file_watcher
    stop_file_watcher()


def get_watchdog() -> WatchDog:
    """获取全局看门狗实例"""
    if _watchdog is None:
        init_globals()
    return _watchdog


def get_health_cache() -> HealthCache:
    """获取全局健康缓存实例"""
    if _health_cache is None:
        init_globals()
    return _health_cache


def get_concurrency_groups() -> ConcurrencyGroups:
    """获取全局并发组实例"""
    if _concurrency_groups is None:
        init_globals()
    return _concurrency_groups


def shutdown_globals() -> None:
    """关闭全局资源（进程退出时调用）"""
    # 停止文件系统监控
    try:
        stop_file_monitor()
    except Exception as e:
        logger.debug(f"文件监控关闭失败: {e}")

    # 执行清理钩子（锁外，避免死锁）
    from infra.hooks import run_hooks
    try:
        run_hooks("cleanup")
    except Exception as e:
        logger.error(f"清理钩子执行失败: {e}")

    global _watchdog, _health_cache, _concurrency_groups
    with _lock:
        if _watchdog:
            _watchdog.stop()
            _watchdog = None
        _health_cache = None
        _concurrency_groups = None
        logger.info("全局基础设施已关闭")
