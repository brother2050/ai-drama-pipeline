"""并发组 — 互斥锁按组名管理

解决的问题：
- ComfyUI 同一时间只能处理一张图/一个视频
- 同一 GPU 上的多个后端不能并行
- 不同类型的后端（TTS vs LLM）可以并行

与 infra/concurrency.py 的区别：
- concurrency.py: 信号量限流 + 错开启动（通用并发控制）
- concurrency_groups: 按资源组互斥（GPU 级别的资源管理）

用法:
    groups = ConcurrencyGroups({"comfyui": 1, "tts": 2, "gpu": 1})

    # comfyui 组同时只允许 1 个任务
    with groups.acquire("comfyui"):
        do_comfyui_work()

    # 后端自动注册到组
    groups.register_backend("flux", groups=["comfyui", "gpu"])
    groups.register_backend("sd15", groups=["comfyui", "gpu"])
    groups.register_backend("mimo-tts", groups=["tts"])

    # 通过后端名获取锁
    with groups.acquire_backend("flux"):
        do_flux_work()
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

__all__ = ["ConcurrencyGroups"]


class ConcurrencyGroups:
    """并发组管理器 — 按组名维护互斥锁

    Args:
        limits: 组名 → 最大并发数，如 {"comfyui": 1, "tts": 2}
    """

    def __init__(self, limits: dict[str, int] | None = None):
        self._limits = limits or {}
        self._locks: dict[str, threading.Semaphore] = {}
        self._backend_groups: dict[str, list[str]] = {}  # backend -> [group_names]

        for group, limit in self._limits.items():
            self._locks[group] = threading.Semaphore(limit)

    def register_backend(self, backend: str, groups: list[str]) -> None:
        """注册后端到并发组"""
        self._backend_groups[backend] = groups
        for g in groups:
            if g not in self._locks:
                self._locks[g] = threading.Semaphore(self._limits.get(g, 1))
                self._limits[g] = self._limits.get(g, 1)

    @contextmanager
    def acquire(self, group: str):
        """获取指定组的锁

        Args:
            group: 组名（如 "comfyui"）

        Raises:
            KeyError: 组不存在
        """
        lock = self._locks.get(group)
        if lock is None:
            # 未注册的组，允许通过（不阻塞）
            logger.debug(f"并发组 '{group}' 未注册，跳过限流")
            yield
            return

        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @contextmanager
    def acquire_backend(self, backend: str):
        """获取后端所属的所有组的锁（按组名排序避免死锁）

        Args:
            backend: 后端名（如 "flux"）
        """
        groups = self._backend_groups.get(backend, [])
        if not groups:
            yield
            return

        # 按组名排序获取锁，避免死锁
        sorted_groups = sorted(set(groups))
        acquired = []
        try:
            for g in sorted_groups:
                lock = self._locks.get(g)
                if lock:
                    lock.acquire()
                    acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    def is_available(self, group: str) -> bool:
        """检查组是否有空闲槽位（非阻塞）"""
        lock = self._locks.get(group)
        if lock is None:
            return True
        # Semaphore._value 不是公开 API，但用于监控可接受
        return lock._value > 0

    def stats(self) -> dict[str, dict]:
        """返回各组的状态"""
        result = {}
        for group, limit in self._limits.items():
            lock = self._locks.get(group)
            available = lock._value if lock else limit
            result[group] = {
                "limit": limit,
                "available": available,
                "busy": limit - available,
            }
        return result
