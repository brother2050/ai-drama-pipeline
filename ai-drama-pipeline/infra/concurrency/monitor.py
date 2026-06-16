"""任务监控 — 超时检测 + 健康检查缓存

注意：本模块与 watchdog pip 包（文件系统监控）无关。
watchdog pip 包由 infra/file_watcher.py 使用。

核心职责：
1. 跟踪每个后端任务的运行时长，超时自动标记失败
2. 健康检查 TTL 缓存：避免频繁探测外部服务

适用场景：
- ComfyUI 生成卡死（GPU OOM、节点报错但进程不退出）
- TTS/LipSync 服务无响应

用法：
    wd = WatchDog(busy_timeout=300)
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
from typing import Any, Callable, Generator, TypeVar

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
    """后端看门狗 — 超时检测

    Args:
        busy_timeout: 任务最大运行秒数，超时视为卡死（默认 300s）
        check_interval: 超时检测间隔秒数
        on_timeout: 超时回调 (task_handle) -> None
    """

    def __init__(
        self,
        busy_timeout: float = 300.0,
        check_interval: float = 5.0,
        on_timeout: Callable[[TaskHandle], None] | None = None,
    ):
        self._busy_timeout = busy_timeout
        self._check_interval = check_interval
        self._on_timeout = on_timeout

        self._lock = threading.Lock()
        self._active: dict[str, TaskHandle] = {}
        self._watcher_stop = threading.Event()
        self._watcher: threading.Thread | None = None

    def start(self) -> None:
        """启动后台监控线程"""
        if self._watcher and self._watcher.is_alive():
            return
        self._watcher_stop.clear()
        self._watcher = threading.Thread(target=self._watch_loop, daemon=True, name="watchdog")
        self._watcher.start()
        logger.info(f"看门狗启动: busy_timeout={self._busy_timeout}s")

    def stop(self) -> None:
        """停止监控线程"""
        self._watcher_stop.set()
        if self._watcher:
            self._watcher.join(timeout=5)
            self._watcher = None

    @contextmanager
    def track(self, task_id: str, backend: str = "") -> Generator[TaskHandle, None, None]:
        """跟踪一个任务的执行。超时自动标记。

        用法:
            with wd.track("shot001:tts", backend="mimo") as handle:
                result = tts_generate(...)
            print(handle.elapsed, handle.status)
        """
        handle = TaskHandle(task_id=task_id, backend=backend)
        with self._lock:
            self._active[task_id] = handle

        try:
            yield handle
            with self._lock:
                if handle.status == "running":
                    handle.status = "done"
                handle.end_time = time.monotonic()
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

            for handle in timed_out:
                logger.error(f"[WatchDog] 检测到超时任务: {handle.task_id} "
                             f"({handle.elapsed}s, backend={handle.backend})")
                if self._on_timeout:
                    try:
                        self._on_timeout(handle)
                    except Exception as e:
                        logger.error(f"[WatchDog] 超时回调异常: {e}")


class HealthCache:
    """健康检查 TTL 缓存

    避免每次状态查询都打到外部服务。
    缓存命中时直接返回上次结果，超时后才重新探测。

    用法:
        cache = HealthCache(ttl=30)
        result = cache.get_or_check_full("comfyui", lambda: check_comfyui_health())
    """

    def __init__(self, ttl: float = 30.0):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[Any, float]] = {}

    def get_or_check_full(self, key: str, checker: Callable[[], T]) -> T:
        """缓存任意类型结果（如完整 dict），超时则重新检查"""
        now = time.monotonic()
        with self._lock:
            if key in self._cache:
                value, ts = self._cache[key]
                if now - ts < self._ttl:
                    return value

        try:
            value = checker()
        except Exception as e:
            error_result = {"available": False, "reason": str(e), "type": "error"}
            with self._lock:
                self._cache[key] = (error_result, time.monotonic() - self._ttl + 5)
            return error_result
        with self._lock:
            self._cache[key] = (value, time.monotonic())
        return value

    def invalidate(self, key: str | None = None) -> None:
        """清除缓存（key=None 清除全部）"""
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()
