"""安全执行器 — 任务级错误边界 + 恢复策略

核心职责：
1. 结构化异常捕获（区分可重试/不可重试错误）
2. 带退避的重试（指数退避 + 抖动）
3. 降级执行（主方案失败时自动切换备选方案）
4. 批量执行的错误隔离（单个失败不影响整体）

与 infra/retry.py 的区别：
- retry.py 是简单的重试循环
- safe_executor 提供完整的错误边界、降级、批量隔离

用法:
    # 单任务安全执行
    result = safe_run(tts_generate, args=(text,), fallback=silent_audio)

    # 批量隔离执行
    results = safe_map(process_shot, shots, continue_on_error=True)

    # 装饰器
    @safe_task(retries=2, fallback=None)
    def risky_operation(...): ...
"""
from __future__ import annotations

import concurrent.futures
import functools
import logging
import random
import threading
import time
import traceback
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

__all__ = ["safe_run", "safe_map", "safe_task", "SafeExecutionError"]


class SafeExecutionError(Exception):
    """安全执行器包装的异常，保留原始异常链"""
    task_id: str = ""
    attempts: int = 0
    last_error: Exception | None = None


def safe_run(
    fn: Callable[..., T],
    args: tuple = (),
    kwargs: dict | None = None,
    *,
    retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable: tuple[type[Exception], ...] = (Exception,),
    fallback: T | Callable[[], T] | None = None,
    task_id: str = "",
    timeout: float | None = None,
    cancel_event: threading.Event | None = None,
) -> T:
    """安全执行单个任务

    Args:
        fn: 要执行的函数
        args: 位置参数
        kwargs: 关键字参数
        retries: 最大重试次数（含首次执行）
        base_delay: 重试基础延迟（秒）
        max_delay: 重试最大延迟（秒）
        retryable: 可重试的异常类型
        fallback: 全部重试失败后的降级值或生成函数
        task_id: 任务标识（用于日志）
        timeout: 单次执行超时（秒），None 表示不限
        cancel_event: 可选的取消标志。超时后自动 set；
            fn 可通过 kwargs["_cancel_event"] 获取并定期检查 is_set()
            以实现协作式取消。注意：Python 无法强制终止线程，
            仅能通过此机制通知 fn 主动退出。

    Returns:
        fn 的返回值，或 fallback 值
    """
    kwargs = kwargs or {}
    last_exc: Exception | None = None

    # 超时模式下自动创建取消标志，传入 fn 供协作式取消
    # 仅当 fn 接受 **kwargs 或显式声明 _cancel_event 参数时才注入
    _auto_created_event = False
    if timeout and cancel_event is None:
        cancel_event = threading.Event()
        _auto_created_event = True
    if cancel_event:
        import inspect
        sig = inspect.signature(fn)
        accepts_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if accepts_var_keyword or "_cancel_event" in sig.parameters:
            kwargs["_cancel_event"] = cancel_event

    for attempt in range(max(1, retries)):
        # 每次重试前重置自动创建的 cancel_event（避免上一轮超时影响本轮）
        if _auto_created_event and cancel_event is not None:
            cancel_event.clear()
        try:
            if timeout:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as te:
                    future = te.submit(fn, *args, **kwargs)
                    try:
                        return future.result(timeout=timeout)
                    except concurrent.futures.TimeoutError:
                        # 后台线程无法取消（Python 不支持强制终止线程），
                        # 通过 cancel_event 通知 fn 协作退出，线程将在完成后自动回收。
                        if cancel_event:
                            cancel_event.set()
                        logger.warning(
                            f"[SafeExecutor] {task_id or fn.__name__}: "
                            f"执行超时 ({timeout}s)，后台线程继续运行直至完成"
                        )
                        raise
            else:
                return fn(*args, **kwargs)
        except retryable as e:
            last_exc = e
            if isinstance(e, concurrent.futures.TimeoutError):
                last_exc = TimeoutError(f"{task_id or fn.__name__}: 执行超时 ({timeout}s)")
            if attempt < retries - 1:
                delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
                logger.warning(
                    f"[SafeExecutor] {task_id or fn.__name__}: "
                    f"重试 {attempt + 1}/{retries}，{delay:.1f}s 后 — {e}"
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"[SafeExecutor] {task_id or fn.__name__}: "
                    f"{retries} 次全部失败 — {e}\n{traceback.format_exc()}"
                )

    # 全部重试失败，尝试降级
    if fallback is not None:
        value = fallback() if callable(fallback) else fallback
        logger.info(f"[SafeExecutor] {task_id or fn.__name__}: 使用降级方案")
        return value

    # 无降级，抛出包装异常
    wrapped = SafeExecutionError(f"{task_id or fn.__name__}: {retries} 次执行失败")
    wrapped.task_id = task_id
    wrapped.attempts = retries
    wrapped.last_error = last_exc
    raise wrapped from last_exc


def safe_map(
    fn: Callable[..., T],
    items: list[Any],
    *,
    continue_on_error: bool = True,
    retries: int = 1,
    fallback: Any = None,
    task_id_fn: Callable[[Any, int], str] | None = None,
) -> list[T | Exception]:
    """批量安全执行 — 单个失败不影响其他

    Args:
        fn: 对每个元素执行的函数
        items: 输入列表
        continue_on_error: True 时失败项返回 fallback，False 时立即抛出
        retries: 每项的重试次数
        fallback: 失败项的降级值
        task_id_fn: (item, index) -> task_id 生成器

    Returns:
        与 items 等长的结果列表，失败项为 fallback 值或 Exception
    """
    results: list[Any] = []
    errors = 0

    for i, item in enumerate(items):
        tid = task_id_fn(item, i) if task_id_fn else f"item_{i}"
        try:
            result = safe_run(fn, args=(item,), retries=retries, fallback=fallback, task_id=tid)
            results.append(result)
        except SafeExecutionError as e:
            errors += 1
            if continue_on_error:
                results.append(fallback)
                logger.warning(f"[SafeExecutor] {tid}: 失败跳过 — {e}")
            else:
                raise

    if errors:
        logger.warning(f"[SafeExecutor] 批量执行完成: {len(items)} 项, {errors} 项失败")

    return results


def safe_task(
    retries: int = 2,
    base_delay: float = 1.0,
    retryable: tuple[type[Exception], ...] = (Exception,),
    fallback: Any = None,
):
    """装饰器版安全执行器

    用法:
        @safe_task(retries=3, fallback="")
        def fetch_data(url: str) -> str:
            return requests.get(url).text
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return safe_run(
                fn, args, kwargs,
                retries=retries,
                base_delay=base_delay,
                retryable=retryable,
                fallback=fallback,
                task_id=fn.__name__,
            )
        return wrapper
    return decorator
