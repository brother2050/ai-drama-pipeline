"""后端钩子系统 — 可扩展的初始化/清理/健康检查链

设计原则：
- 新增后端行为只需注册钩子，不改核心代码
- 钩子按优先级排序执行
- 支持全局钩子（所有后端）和类型钩子（特定后端类型）

用法:
    # 注册全局初始化钩子（所有后端启动时执行）
    @on_init(priority=10)
    def setup_http_pool(config):
        init_pool(config.get("http_pool_size", 10))

    # 注册 TTS 类型的初始化钩子
    @on_init(service_type="tts", priority=20)
    def setup_tts_voice(config):
        preload_voice(config.get("voice_id"))

    # 注册清理钩子
    @on_cleanup(priority=100)
    def close_connections():
        http_pool.shutdown()

    # 注册健康检查钩子
    @on_health_check(service_type="image")
    def check_comfyui():
        return comfyui.is_alive()

    # 执行钩子
    run_hooks("init", config, service_type="image")
    run_hooks("cleanup")
    results = run_hooks("health_check", service_type="image")
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["on_init", "on_cleanup", "on_health_check", "run_hooks", "clear_hooks"]


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
    "init": [],
    "cleanup": [],
    "health_check": [],
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


def on_init(priority: int = 100, service_type: str = ""):
    """注册初始化钩子

    Args:
        priority: 优先级（越小越先执行）
        service_type: 限定服务类型（空=全局）
    """
    def decorator(fn):
        _register("init", fn, priority, service_type)
        return fn
    return decorator


def on_cleanup(priority: int = 100, service_type: str = ""):
    """注册清理钩子"""
    def decorator(fn):
        _register("cleanup", fn, priority, service_type)
        return fn
    return decorator


def on_health_check(priority: int = 100, service_type: str = ""):
    """注册健康检查钩子"""
    def decorator(fn):
        _register("health_check", fn, priority, service_type)
        return fn
    return decorator


def run_hooks(hook_type: str, *args, service_type: str = "", **kwargs) -> list[Any]:
    """执行指定类型的钩子

    执行规则：
    1. 全局钩子（service_type=""）始终执行
    2. 类型钩子只在 service_type 匹配时执行
    3. 按 priority 升序执行

    Args:
        hook_type: 钩子类型（init / cleanup / health_check）
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
            if hook_type == "init":
                raise  # 初始化钩子失败应阻断启动

    return results


def clear_hooks(hook_type: str | None = None) -> None:
    """清除钩子（测试用）"""
    with _lock:
        if hook_type:
            _registry.get(hook_type, []).clear()
        else:
            for k in _registry:
                _registry[k].clear()
