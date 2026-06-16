"""后端钩子系统 — 可扩展的清理/健康检查链

设计原则：
- 新增后端行为只需注册钩子，不改核心代码
- 钩子按优先级排序执行
- 支持全局钩子（所有后端）和类型钩子（特定后端类型）

集成点：
- infra/globals.py: shutdown_globals() 执行 cleanup 钩子
- infra/toolcheck.py: 健康检查时执行 health_check 钩子
- infra/http_pool.py: 注册 cleanup 钩子自动关闭 HTTP 连接池
- infra/database/pool.py: 注册 cleanup 钩子自动关闭数据库连接池

用法:
    # 注册清理钩子
    @on_cleanup(priority=100)
    def close_connections():
        http_pool.shutdown()

    # 注册健康检查钩子
    @on_health_check(service_type="image")
    def check_comfyui():
        return comfyui.is_alive()

    # 执行钩子
    run_hooks("cleanup")
    results = run_hooks("health_check", service_type="image")
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["on_cleanup", "on_health_check", "on_cache_invalidate", "run_hooks"]


@dataclass
class HookEntry:
    """单个钩子条目"""
    fn: Callable[..., Any]
    priority: int = 100
    service_type: str = ""  # 空 = 全局钩子
    name: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = self.fn.__name__


# 钩子注册表: hook_type -> [HookEntry]
_registry: dict[str, list[HookEntry]] = {
    "cleanup": [],
    "health_check": [],
    "cache_invalidate": [],
}
_lock = threading.Lock()


def _register(hook_type: str, fn: Callable, priority: int, service_type: str) -> Callable:
    """注册钩子"""
    entry = HookEntry(fn=fn, priority=priority, service_type=service_type)
    with _lock:
        _registry.setdefault(hook_type, []).append(entry)
        _registry[hook_type].sort(key=lambda h: h.priority)
    logger.debug(f"钩子注册: {hook_type}/{service_type or '*'} -> {fn.__name__} (p={priority})")
    return fn


def on_cleanup(priority: int = 100, service_type: str = "") -> Callable[[Callable], Callable]:
    """注册清理钩子"""
    def decorator(fn: Callable) -> Callable:
        _register("cleanup", fn, priority, service_type)
        return fn
    return decorator


def on_health_check(priority: int = 100, service_type: str = "") -> Callable[[Callable], Callable]:
    """注册健康检查钩子"""
    def decorator(fn: Callable) -> Callable:
        _register("health_check", fn, priority, service_type)
        return fn
    return decorator


def on_cache_invalidate(priority: int = 100) -> Callable[[Callable], Callable]:
    """注册缓存失效钩子 — 文件变化时由 file_watcher 触发"""
    def decorator(fn: Callable) -> Callable:
        _register("cache_invalidate", fn, priority, "")
        return fn
    return decorator


def run_hooks(hook_type: str, *args, service_type: str = "", **kwargs) -> list[Any]:
    """执行指定类型的钩子

    执行规则：
    1. 全局钩子（service_type=""）始终执行
    2. 类型钩子只在 service_type 匹配时执行
    3. 按 priority 升序执行

    Args:
        hook_type: 钩子类型（cleanup / health_check）
        *args: 传递给钩子的位置参数
        service_type: 当前服务类型（用于过滤类型钩子）
        **kwargs: 传递给钩子的关键字参数

    Returns:
        所有钩子的返回值列表（cleanup 钩子无返回值）
    """
    hooks = _registry.get(hook_type, [])
    results = []

    with _lock:
        matching = [
            h for h in hooks
            if not h.service_type or h.service_type == service_type
        ]

    for hook in matching:
        try:
            result = hook.fn(*args, **kwargs)
            results.append(result)
        except Exception as e:
            logger.error(f"钩子 {hook.name} ({hook_type}/{hook.service_type or '*'}): {e}")
            # cleanup 钩子不阻断但记录到监控
            if hook_type == "cleanup":
                logger.error(f"清理钩子失败，资源可能泄漏: {hook.name}")

    return results


def clear_hooks(hook_type: str | None = None) -> None:
    """清除钩子（测试用）"""
    with _lock:
        if hook_type:
            _registry.get(hook_type, []).clear()
        else:
            for k in _registry:
                _registry[k].clear()
