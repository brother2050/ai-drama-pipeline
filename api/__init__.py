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


def _ensure_registered():
    """懒加载: 首次调用时导入所有后端模块触发注册（线程安全）

    使用双重检查锁 (DCL)。Python GIL 保证 _loaded 的读写是原子的，
    因此第一次检查在锁外是安全的。如果需要去除 GIL 依赖（如 nogil Python），
    可改用 threading.Event。
    """
    global _loaded, _fail_count
    if _loaded:
        return
    if _fail_count >= _MAX_RETRIES:
        return  # 连续失败超过阈值，不再重试
    with _register_lock:
        if _loaded:
            return
        _loaded = True

        from flow.model_registry import ModelRegistry

        try:
            reg = ModelRegistry()
        except Exception as e:
            _fail_count += 1
            logger.error(f"加载模型注册表失败 ({_fail_count}/{_MAX_RETRIES}): {e}")
            _loaded = False  # 允许重试（有上限）
            return
        _fail_count = 0  # 成功后重置计数

        for _service_type, module_path, _priority in reg.get_backend_modules():
            try:
                importlib.import_module(module_path)
            except ImportError as e:
                logger.debug(f"跳过后端 {module_path}: {e}")
            except Exception as e:
                logger.warning(f"加载后端 {module_path} 失败: {e}")


def get_container(config: dict):
    """获取 DI 容器（触发懒加载）"""
    _ensure_registered()
    from api.registry import Container
    return Container(config)
