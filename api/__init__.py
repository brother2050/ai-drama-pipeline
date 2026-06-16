"""API 后端层 — 懒加载注册

改为按需 import，避免启动时加载所有后端模块（含重依赖如 torch 等）。
后端模块在首次 Container.get() 时才被导入和注册。

后端模块注册信息从 config/models_registry.yaml 动态读取，
新增后端只需在 YAML 中添加 module + priority 字段，无需改代码。
"""
from __future__ import annotations

import importlib
import logging
import threading

logger = logging.getLogger(__name__)

_loaded = False  # GIL 保证 bool 读写原子性，第一次检查在锁外安全
_register_lock = threading.Lock()
_fail_count = 0  # 连续失败计数，避免日志洪泛
_MAX_RETRIES = 3
_last_fail_time = 0.0  # 上次失败时间戳
_RETRY_COOLDOWN = 60.0  # 失败后冷却秒数，超时后允许重试


def _ensure_registered():
    """懒加载: 首次调用时导入所有后端模块触发注册（线程安全）

    使用双重检查锁 (DCL)。Python GIL 保证 _loaded 的读写是原子的，
    因此第一次检查在锁外是安全的。如果需要去除 GIL 依赖（如 nogil Python），
    可改用 threading.Event。

    失败后进入冷却期，冷却期过后允许重试（长运行进程如 Celery Worker 中，
    YAML 文件可能临时不可用，需要恢复机制）。
    """
    global _loaded, _fail_count, _last_fail_time
    if _loaded:
        return
    with _register_lock:
        if _loaded:
            return
        if _fail_count >= _MAX_RETRIES:
            # 冷却期过后允许重试
            import time
            if time.monotonic() - _last_fail_time < _RETRY_COOLDOWN:
                return
            _fail_count = 0  # 重置计数，允许重试

        from infra.config.registry import ModelRegistry

        try:
            reg = ModelRegistry()
        except Exception as e:
            _fail_count += 1
            import time
            _last_fail_time = time.monotonic()
            logger.error(f"加载模型注册表失败 ({_fail_count}/{_MAX_RETRIES}): {e}")
            return
        _fail_count = 0  # 成功后重置计数

        loaded = 0
        for _service_type, module_path, _priority in reg.get_backend_modules():
            try:
                importlib.import_module(module_path)
                loaded += 1
            except ImportError as e:
                logger.debug(f"跳过后端 {module_path}: {e}")
            except Exception as e:
                logger.warning(f"加载后端 {module_path} 失败: {e}")

        if loaded == 0:
            logger.warning("没有任何后端模块加载成功（所有 import 均失败）")
        _loaded = True  # 注册表加载成功即标记（后端可能缺失依赖，属正常情况）


def get_container(config: dict):
    """获取 DI 容器（触发懒加载）"""
    _ensure_registered()
    from api.registry import Container
    return Container(config)
