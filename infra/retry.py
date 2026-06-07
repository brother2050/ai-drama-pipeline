"""重试引擎 — 指数退避 + 随机抖动（防雷群效应）"""
from __future__ import annotations
import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

__all__ = ["retry"]


def retry(fn: Callable[..., T], *args, max_retries: int = 3, base_delay: float = 1.0,
          max_delay: float = 60.0, exceptions: tuple = (Exception,), **kwargs) -> T:
    """带指数退避 + 随机抖动的重试（max_retries=0 表示不重试，但仍执行一次）"""
    last_exc = None
    for attempt in range(max(1, max_retries)):
        try:
            return fn(*args, **kwargs)
        except exceptions as e:
            last_exc = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt) * (0.5 + random.random()), max_delay)
                logger.warning(f"重试 {attempt+1}/{max_retries}，{delay:.1f}s 后: {e}")
                time.sleep(delay)
    raise last_exc or RuntimeError(f"重试 {max_retries} 次后仍失败")
