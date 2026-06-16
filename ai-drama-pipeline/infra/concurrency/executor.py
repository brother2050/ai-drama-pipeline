"""安全执行器 — 任务级错误边界 + 恢复策略

核心职责：
1. 结构化异常捕获（区分可重试/不可重试错误）
2. 带退避的重试（指数退避 + 抖动）
3. 降级执行（主方案失败时自动切换备选方案）

用法:
    result = safe_run(tts_generate, args=(text,), fallback=silent_audio)
"""
from __future__ import annotations

import concurrent.futures
import logging
import random
import threading
import time
import traceback
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

__all__ = ["safe_run"]

# 共享线程池（超时模式复用，避免反复创建销毁）
# 注意：Python 线程无法强制终止，超时后仅通过 cancel_event 协作取消。
# 如需强制终止，改用 ProcessPoolExecutor（但要求 fn 可 pickle，实例方法不可）。
_shared_pool: concurrent.futures.ThreadPoolExecutor | None = None
_shared_pool_lock = threading.Lock()

def _shared_executor() -> concurrent.futures.ThreadPoolExecutor:
    """获取共享的单线程 executor（进程级复用）"""
    global _shared_pool
    if _shared_pool is None:
        with _shared_pool_lock:
            if _shared_pool is None:
                _shared_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="safe_exec")
    return _shared_pool


# 注册清理钩子：进程退出时关闭进程池
try:
    from infra.hooks import on_cleanup
    def _shutdown_pool():
        global _shared_pool
        if _shared_pool is not None:
            _shared_pool.shutdown(wait=False, cancel_futures=True)
            _shared_pool = None
    on_cleanup(priority=90)(_shutdown_pool)
except ImportError:
    pass



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
                # 复用线程池：所有重试共享同一个 executor，避免反复创建销毁
                # 注意：不能用 `with _shared_executor() as te:`，因为 __exit__ 会
                # 调用 shutdown(wait=True) 关闭共享池，导致后续调用失败。
                te = _shared_executor()
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

    # 无降级，抛出最后一次异常
    raise last_exc  # type: ignore[misc]
