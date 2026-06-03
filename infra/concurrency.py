"""并发控制工具 — 错开启动 + 信号量限流

- 每个新任务在前一个启动后至少等待 stagger_ms 才启动
- 同时最多运行 max_concurrent 个任务
- 适合 ComfyUI/TTS 等外部服务的请求间隔控制

用法:
    results = await run_staggered(tasks, max_concurrent=2, stagger_ms=5000)

    # 或同步版本
    results = run_staggered_sync(tasks, max_concurrent=2, stagger_ms=5000)
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["run_staggered_sync", "StaggeredExecutor"]


def run_staggered_sync(
    tasks: list[Callable[[], Any]],
    max_concurrent: int = 2,
    stagger_ms: float = 3000,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[Any]:
    """同步版错开并发执行器"""
    if not tasks:
        return []
    if len(tasks) == 1:
        return _run_single(tasks[0], on_progress)

    results: list[Any] = [None] * len(tasks)
    completed_count = 0
    lock = threading.Lock()

    def _run_one(idx: int):
        nonlocal completed_count
        if idx > 0:
            time.sleep(idx * stagger_ms / 1000)
        try:
            result = tasks[idx]()
            with lock:
                results[idx] = result
                completed_count += 1
                if on_progress:
                    on_progress(completed_count, len(tasks), f"完成 {idx+1}")
        except Exception as e:
            logger.error(f"任务 {idx+1} 失败: {e}")
            with lock:
                completed_count += 1
                if on_progress:
                    on_progress(completed_count, len(tasks), f"任务 {idx+1} 失败")

    with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
        futures = [pool.submit(_run_one, i) for i in range(len(tasks))]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.debug(f"Future 异常: {e}")
    return results


def _run_single(task: Callable, on_progress) -> list:
    """单任务快捷路径"""
    if on_progress:
        on_progress(0, 1, "执行中...")
    try:
        result = task()
        if on_progress:
            on_progress(1, 1, "完成")
        return [result]
    except Exception as e:
        logger.error(f"任务执行失败: {e}")
        if on_progress:
            on_progress(1, 1, "失败")
        return [None]


class StaggeredExecutor:
    """可复用的错开并发执行器

    适合在管线中多次调用，保持并发配置一致。

    用法:
        executor = StaggeredExecutor(max_concurrent=2, stagger_ms=3000)
        results1 = executor.run(tasks_batch1)
        results2 = executor.run(tasks_batch2)
    """

    def __init__(self, max_concurrent: int = 2, stagger_ms: float = 3000):
        self.max_concurrent = max_concurrent
        self.stagger_ms = stagger_ms

    def run(
        self,
        tasks: list[Callable[[], Any]],
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> list[Any]:
        """执行任务列表"""
        return run_staggered_sync(
            tasks, self.max_concurrent, self.stagger_ms, on_progress)

    def __repr__(self) -> str:
        return (f"StaggeredExecutor(max_concurrent={self.max_concurrent}, "
                f"stagger_ms={self.stagger_ms})")
