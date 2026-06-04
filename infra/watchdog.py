"""后端看门狗 — 超时检测 + 空闲淘汰 + 健康检查缓存

核心职责：
1. 跟踪每个后端任务的运行时长，超时自动标记失败
2. 空闲淘汰：后端长时间无任务时清理记录
3. 健康检查 TTL 缓存：避免频繁探测外部服务

适用场景：
- ComfyUI 生成卡死（GPU OOM、节点报错但进程不退出）
- TTS/LipSync 服务无响应
- 多后端争抢有限 GPU 资源

用法：
    wd = WatchDog(busy_timeout=300, idle_timeout=600, max_active=2)
    with wd.track("comfyui:shot001") as handle:
        result = do_comfyui_generation(...)
    # 超时自动标记为 TIMEOUT，handle.elapsed 记录实际耗时
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

__all__ = ["WatchDog", "TaskHandle", "HealthCache"]


@dataclass
class TaskHandle:
    """单个任务的跟踪句柄"""
    task_id: str
    backend: str
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0
    status: str = "running"  # running / done / timeout / error

    @property
    def elapsed(self) -> float:
        end = self.end_time if self.end_time else time.monotonic()
        return round(end - self.start_time, 2)


class WatchDog:
    """后端看门狗 — 超时检测 + LRU 淘汰

    Args:
        busy_timeout: 任务最大运行秒数，超时视为卡死（默认 300s）
        idle_timeout: 后端空闲超时秒数，超时关闭释放资源（默认 600s）
        max_active: 最大同时活跃后端数，超限 LRU 淘汰（0=不限）
        on_timeout: 超时回调 (task_handle) -> None
        on_evict: LRU 淘汰回调 (backend_name) -> None
    """

    def __init__(
        self,
        busy_timeout: float = 300.0,
        idle_timeout: float = 600.0,
        max_active: int = 0,
        check_interval: float = 5.0,
        on_timeout: Callable[[TaskHandle], None] | None = None,
        on_evict: Callable[[str], None] | None = None,
    ):
        self._busy_timeout = busy_timeout
        self._idle_timeout = idle_timeout
        self._max_active = max_active
        self._check_interval = check_interval
        self._on_timeout = on_timeout
        self._on_evict = on_evict

        self._lock = threading.Lock()
        self._active: dict[str, TaskHandle] = {}  # task_id -> handle
        self._last_used: dict[str, float] = {}  # backend -> last used timestamp
        self._watcher_stop = threading.Event()
        self._watcher: threading.Thread | None = None

    def start(self) -> None:
        """启动后台监控线程"""
        if self._watcher and self._watcher.is_alive():
            return
        self._watcher_stop.clear()
        self._watcher = threading.Thread(target=self._watch_loop, daemon=True, name="watchdog")
        self._watcher.start()
        logger.info(f"看门狗启动: busy_timeout={self._busy_timeout}s, "
                     f"idle_timeout={self._idle_timeout}s, max_active={self._max_active}")

    def stop(self) -> None:
        """停止监控线程"""
        self._watcher_stop.set()
        if self._watcher:
            self._watcher.join(timeout=5)
            self._watcher = None

    @contextmanager
    def track(self, task_id: str, backend: str = ""):
        """跟踪一个任务的执行。超时自动标记。

        用法:
            with wd.track("shot001:tts", backend="mimo") as handle:
                result = tts_generate(...)
            logger.info(f"任务完成: elapsed={handle.elapsed}s, status={handle.status}")
        """
        handle = TaskHandle(task_id=task_id, backend=backend)
        with self._lock:
            self._active[task_id] = handle
            if backend:
                self._last_used[backend] = time.monotonic()

        # LRU 淘汰检查
        self._maybe_evict(backend)

        try:
            yield handle
            with self._lock:
                # 仅当未被看门狗标记为 timeout 时才更新为 done
                if handle.status == "running":
                    handle.status = "done"
                handle.end_time = time.monotonic()
                if backend:
                    self._last_used[backend] = time.monotonic()
        except TimeoutError:
            with self._lock:
                handle.status = "timeout"
                handle.end_time = time.monotonic()
            logger.error(f"[WatchDog] 任务超时: {task_id} ({handle.elapsed}s)")
            if self._on_timeout:
                self._on_timeout(handle)
            raise
        except Exception:
            with self._lock:
                handle.status = "error"
                handle.end_time = time.monotonic()
            raise
        finally:
            with self._lock:
                self._active.pop(task_id, None)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def active_tasks(self) -> list[str]:
        with self._lock:
            return list(self._active.keys())

    def _watch_loop(self) -> None:
        """后台监控循环：检测超时任务"""
        while not self._watcher_stop.wait(timeout=self._check_interval):
            now = time.monotonic()
            timed_out = []
            with self._lock:
                for task_id, handle in list(self._active.items()):
                    if handle.status == "running" and (now - handle.start_time) > self._busy_timeout:
                        handle.status = "timeout"
                        handle.end_time = now
                        timed_out.append(handle)
                        self._active.pop(task_id, None)

                # 空闲超时淘汰：后端长时间无新任务
                if self._idle_timeout > 0:
                    idle_backends = [
                        b for b, ts in self._last_used.items()
                        if (now - ts) > self._idle_timeout
                        and not any(h.backend == b for h in self._active.values())
                    ]
                    for b in idle_backends:
                        self._last_used.pop(b, None)
                        logger.info(f"[WatchDog] 空闲超时淘汰后端: {b}")

            for handle in timed_out:
                logger.error(f"[WatchDog] 检测到超时任务: {handle.task_id} "
                             f"({handle.elapsed}s, backend={handle.backend})")
                if self._on_timeout:
                    try:
                        self._on_timeout(handle)
                    except Exception as e:
                        logger.error(f"[WatchDog] 超时回调异常: {e}")

    def _maybe_evict(self, new_backend: str) -> None:
        """LRU 淘汰：当活跃数超限时，关闭最久未使用的后端"""
        if self._max_active <= 0:
            return
        with self._lock:
            if len(self._active) < self._max_active:
                return
            # 找最久未使用的后端（排除当前正在使用的）
            candidates = [(t, b) for t, b in self._last_used.items()
                          if b != new_backend and any(h.backend == b for h in self._active.values())]
            if not candidates:
                return
            candidates.sort(key=lambda x: x[1])  # 按时间升序
            oldest_backend = candidates[0][0]
        logger.warning(f"[WatchDog] LRU 淘汰后端: {oldest_backend}")
        if self._on_evict:
            try:
                self._on_evict(oldest_backend)
            except Exception as e:
                logger.error(f"[WatchDog] 淘汰回调异常: {e}")


class HealthCache:
    """健康检查 TTL 缓存

    避免每次状态查询都打到外部服务。
    缓存命中时直接返回上次结果，超时后才重新探测。

    用法:
        cache = HealthCache(ttl=30)
        ok = cache.get_or_check("comfyui", lambda: check_comfyui_health())
    """

    def __init__(self, ttl: float = 30.0):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[bool, float]] = {}
        self._full_cache: dict[str, tuple[Any, float]] = {}

    def get_or_check(self, key: str, checker: Callable[[], bool]) -> bool:
        """获取缓存的健康状态，超时则重新检查"""
        now = time.monotonic()
        with self._lock:
            if key in self._cache:
                ok, ts = self._cache[key]
                if now - ts < self._ttl:
                    return ok

        # 缓存 miss，执行检查
        try:
            ok = checker()
        except Exception:
            ok = False

        with self._lock:
            self._cache[key] = (ok, time.monotonic())
        return ok

    def get_or_check_full(self, key: str, checker: Callable[[], T]) -> T:
        """缓存任意类型结果（如完整 dict），超时则重新检查

        与 get_or_check 的区别：缓存完整返回值而非仅 bool。
        适合 toolcheck 等需要返回详细信息的场景。
        """
        now = time.monotonic()
        with self._lock:
            if key in self._full_cache:
                value, ts = self._full_cache[key]
                if now - ts < self._ttl:
                    return value

        value = checker()
        with self._lock:
            self._full_cache[key] = (value, time.monotonic())
        return value

    def invalidate(self, key: str | None = None) -> None:
        """清除缓存（key=None 清除全部）"""
        with self._lock:
            if key:
                self._cache.pop(key, None)
                self._full_cache.pop(key, None)
            else:
                self._cache.clear()
                self._full_cache.clear()

    def get_cached(self, key: str) -> bool | None:
        """获取缓存值（不触发检查），无缓存返回 None"""
        now = time.monotonic()
        with self._lock:
            if key in self._cache:
                ok, ts = self._cache[key]
                if now - ts < self._ttl:
                    return ok
        return None
