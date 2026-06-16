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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["run_staggered_sync"]


def run_staggered_sync(
    tasks: list[Callable[[], Any]],
    max_concurrent: int = 2,
    stagger_ms: float = 3000,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[Any]:
    """同步版错开并发执行器"""
    if not tasks:
        return []

    results: list[Any] = [None] * len(tasks)
    completed_count = 0
    lock = threading.Lock()
    last_start = [0.0]  # 上一个任务的启动时间（可变容器，闭包共享）
    start_lock = threading.Lock()

    def _run_one(idx: int):
        nonlocal completed_count
        # 错开：等待距上一个任务启动后 stagger_ms（读+写在同一把锁内，消除竞态）
        if idx > 0:
            with start_lock:
                now = time.monotonic()
                wait = max(0, stagger_ms / 1000 - (now - last_start[0]))
                if wait > 0:
                    last_start[0] = now + wait
                else:
                    last_start[0] = now
            if wait > 0:
                time.sleep(wait)
        else:
            with start_lock:
                last_start[0] = time.monotonic()
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
                logger.warning(f"Future 异常: {e}")
    return results
