"""模型注册表 — 配置驱动的后端管理

从 config/models_registry.yaml 加载所有后端定义。
新增模型只需改 YAML，不改代码。

拆分后：
- 生命周期 + 通用查询 → 本文件
- 图像/视频/一致性 → registry_media.py (MediaRegistryMixin)
- LLM 限制查询 → registry_llm.py (LLMRegistryMixin)
"""
from __future__ import annotations

import copy
import logging
import os
import threading
from typing import Any

import yaml

from infra.config.cache import get_mtime_safe
from infra.config.registry_media import MediaRegistryMixin
from infra.config.registry_llm import LLMRegistryMixin

logger = logging.getLogger(__name__)

__all__ = ["ModelRegistry"]


class ModelRegistry(MediaRegistryMixin, LLMRegistryMixin):
    """配置驱动的模型注册表 — 所有后端元数据的唯一查询入口"""

    _SECTION_MAP: dict[str, str] = {}
    _instance: "ModelRegistry | None" = None
    _instance_mtime: float = 0.0
    _instance_lock = threading.Lock()
    _discovered_limits: dict[str, dict] = {}  # 运行时从 API 错误中学到的限制

    # ══════════════════════════════════════════════════════════
    #  生命周期
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _resolve_registry_path() -> str:
        from infra.config import REGISTRY_PATH
        return REGISTRY_PATH

    def __new__(cls):
        path = cls._resolve_registry_path()
        mtime = get_mtime_safe(path)
        if cls._instance is not None and cls._instance_mtime == mtime:
            return cls._instance
        with cls._instance_lock:
            if cls._instance is not None and cls._instance_mtime == mtime:
                return cls._instance
            inst = super().__new__(cls)
            inst._data = cls._load(path)
            inst._SECTION_MAP = cls._build_section_map(inst._data)
            cls._instance = inst
            cls._instance_mtime = mtime
            return inst

    def __init__(self):
        pass  # __new__ 已完成初始化

    @staticmethod
    def _build_section_map(data: dict) -> dict[str, str]:
        return {k.removesuffix("_backends"): k
                for k in data if k.endswith("_backends")}

    @staticmethod
    def _load(path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"模型注册表不存在: {path}")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not data:
            raise ValueError(f"模型注册表为空: {path}")
        return data

    def reload(self) -> None:
        with self._instance_lock:
            path = self._resolve_registry_path()
            self._data = self._load(path)
            self._SECTION_MAP = self._build_section_map(self._data)
            ModelRegistry._instance_mtime = get_mtime_safe(path)

    # ══════════════════════════════════════════════════════════
    #  内部工具
    # ══════════════════════════════════════════════════════════

    def _deepcopy(self, value: Any) -> Any:
        """统一深拷贝入口：dict 则 copy.deepcopy，否则原样返回"""
        return copy.deepcopy(value) if isinstance(value, dict) else value

    def _section(self, key: str) -> dict:
        """获取 YAML 顶层 section（不拷贝，调用方自行处理）"""
        return self._data.get(key, {})

    def _backend_section(self, service_type: str) -> dict:
        """获取后端 section dict"""
        section = self._SECTION_MAP.get(service_type, "")
        return self._data.get(section, {}) if section else {}

    # ══════════════════════════════════════════════════════════
    #  默认值
    # ══════════════════════════════════════════════════════════

    def get_defaults(self) -> dict[str, str]:
        return copy.deepcopy(self._data.get("defaults", {}))

    # ══════════════════════════════════════════════════════════
    #  后端查询
    # ══════════════════════════════════════════════════════════

    def get_backend(self, service_type: str, name: str) -> dict | None:
        section = self._backend_section(service_type)
        if not section:
            logger.warning(f"未知服务类型: {service_type}")
            return None
        return self._deepcopy(section.get(name))

    def get_backend_meta(self, service_type: str, name: str) -> dict | None:
        result = self.get_backend(service_type, name)
        return result or self._deepcopy(self._data.get("services", {}).get(name))

    def get_backends(self, service_type: str) -> dict[str, dict]:
        return copy.deepcopy(self._backend_section(service_type))

    def list_backend_names(self, service_type: str) -> list[str]:
        return list(self._backend_section(service_type).keys())

    def get_health_check(self, service_type: str, name: str) -> dict | None:
        backend = self.get_backend(service_type, name)
        return self._deepcopy(backend.get("health_check")) if backend else None

    def get_service_health_check(self, service_name: str) -> dict | None:
        hc = self._data.get("services", {}).get(service_name, {}).get("health_check")
        return self._deepcopy(hc)

    # ══════════════════════════════════════════════════════════
    #  便捷后端查询
    # ══════════════════════════════════════════════════════════

    def get_tts_backends(self) -> dict:
        return copy.deepcopy(self._data.get("tts_backends", {}))

    def get_lipsync_backends(self) -> dict:
        return copy.deepcopy(self._data.get("lipsync_backends", {}))

    def get_llm_backends(self) -> dict:
        return copy.deepcopy(self._data.get("llm_backends", {}))

    def get_music_backends(self) -> dict:
        return copy.deepcopy(self._data.get("music_backends", {}))

    # ══════════════════════════════════════════════════════════
    #  服务类型元数据
    # ══════════════════════════════════════════════════════════

    def get_service_cfg_key(self, service_type: str) -> str:
        paths = self._data.get("defaults", {}).get("config_paths", {})
        if service_type in paths:
            return paths[service_type].rsplit(".", 1)[-1]
        return f"{service_type}_backend"

    def get_config_path(self, service_type: str) -> str:
        paths = self._data.get("defaults", {}).get("config_paths", {})
        if service_type in paths:
            return paths[service_type]
        return f"models.{self.get_service_cfg_key(service_type)}"

    def get_service_meta(self, name: str) -> dict | None:
        return self._deepcopy(self._data.get("services", {}).get(name))

    def get_registered_service_types(self) -> list[str]:
        types = list(self._SECTION_MAP.keys())
        types.extend(self._data.get("services", {}).keys())
        return types

    def get_backend_modules(self) -> list[tuple[str, str, int]]:
        modules: list[tuple[str, str, int]] = []
        seen: set[str] = set()

        for service_type, section in self._SECTION_MAP.items():
            for _name, meta in self._data.get(section, {}).items():
                if not isinstance(meta, dict):
                    continue
                mod = meta.get("module")
                if not mod or mod in seen:
                    continue
                modules.append((service_type, mod, meta.get("priority", 99)))
                seen.add(mod)

        for name, meta in self._data.get("services", {}).items():
            if not isinstance(meta, dict):
                continue
            mod = meta.get("module")
            if not mod or mod in seen:
                continue
            modules.append((name, mod, meta.get("priority", 99)))
            seen.add(mod)

        modules.sort(key=lambda x: x[2])
        return modules
