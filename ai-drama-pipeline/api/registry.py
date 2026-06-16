"""服务注册表 — 后端自注册 + DI 容器

核心设计:
- BackendMeta: 后端元数据（注册时使用）
- ServiceRegistry: 注册表（单例）
- Container: DI 容器（按需创建 + 缓存 + 热重载）
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["BackendMeta", "ServiceRegistry", "Container", "registry"]


@dataclass
class BackendMeta:
    """后端元数据"""
    name: str
    service_type: str  # tts / lipsync / image / video / music / llm
    factory: Callable[..., Any]
    requires_api_key: bool = False
    api_key_env: str = ""
    description: str = ""
    priority: int = 100
    tags: list[str] = field(default_factory=list)
    test_handler: Callable[..., dict] | None = None  # 连接测试回调 (name, result, cfg) → dict
    deployment: str = "local"  # "local" / "cloud" — 本地模型优先策略使用


class ServiceRegistry:
    """服务注册表"""

    def __init__(self):
        self._backends: dict[str, BackendMeta] = {}

    def register(self, meta: BackendMeta) -> None:
        key = f"{meta.service_type}:{meta.name}"
        self._backends[key] = meta
        # 同时注册规范化名（fish-speech ↔ fish_speech），消除 _resolve 中的重复查找
        normalized = meta.name.replace("-", "_")
        if normalized != meta.name:
            norm_key = f"{meta.service_type}:{normalized}"
            self._backends.setdefault(norm_key, meta)

    def get(self, service_type: str, name: str) -> BackendMeta | None:
        return self._backends.get(f"{service_type}:{name}")

    def find_test_handler(self, name: str) -> Callable[..., dict] | None:
        """按后端名遍历所有服务类型查找测试回调"""
        for meta in self._backends.values():
            if meta.name == name and meta.test_handler:
                return meta.test_handler
        return None

    def list_by_type(self, service_type: str) -> list[str]:
        candidates = [m for m in self._backends.values() if m.service_type == service_type]
        candidates.sort(key=lambda m: m.priority)
        return [m.name for m in candidates]

    def create(self, service_type: str, name: str, config: dict) -> Any:
        meta = self._backends.get(f"{service_type}:{name}")
        if not meta:
            available = self.list_by_type(service_type)
            raise ValueError(f"未注册的 {service_type} 后端: '{name}'，可用: {available}")
        return meta.factory(config)

    def auto_select(self, service_type: str, config: dict) -> str:
        """根据环境自动选择最佳后端（支持本地优先策略）

        优先级:
        1. 配置中显式指定的后端
        2. 本地部署的后端（local_first=True 时）
        3. 任何可用的后端
        """
        local_first = config.get("local_first", False)

        candidates = sorted(
            [m for m in self._backends.values() if m.service_type == service_type],
            key=lambda m: m.priority)

        # 本地优先：先找本地部署的后端
        if local_first:
            for meta in candidates:
                if meta.deployment != "local":
                    continue
                if meta.requires_api_key:
                    key = os.environ.get(meta.api_key_env, "")
                    if not key:
                        continue
                return meta.name

        # 回退：任何可用的后端
        for meta in candidates:
            if meta.requires_api_key:
                key = os.environ.get(meta.api_key_env, "")
                if not key:
                    continue
            return meta.name
        # 列出各后端缺失的环境变量，帮助用户排查
        missing = [f"{m.name} (需要 {m.api_key_env})" for m in candidates if m.requires_api_key]
        detail = f"，缺失: {', '.join(missing)}" if missing else ""
        raise ValueError(f"没有可用的 {service_type} 后端{detail}")


class Container:
    """DI 容器 — 按需创建 + 缓存 + 热重载"""

    @staticmethod
    def _get_type_key() -> dict[str, str]:
        """从 ModelRegistry 动态获取 service_type → config_key 映射"""
        try:
            from infra.config.registry import ModelRegistry
            reg = ModelRegistry()
            result = {}
            for svc_type in reg.get_registered_service_types():
                cfg_key = reg.get_service_cfg_key(svc_type)
                result[svc_type] = cfg_key
            return result
        except Exception:
            try:
                from infra.config import load_config, REGISTRY_PATH
                reg_data = load_config(REGISTRY_PATH, readonly=True)
                cfg_paths = reg_data.get("defaults", {}).get("config_paths", {})
                return {svc_type: cfg_key for svc_type, cfg_key in cfg_paths.items()}
            except Exception:
                logger.warning("模型注册表不可用，Container 类型映射为空")
                return {}

    def __init__(self, config: dict):
        from api import _ensure_registered
        _ensure_registered()
        self._config = config
        self._instances: dict[str, Any] = {}
        self._snapshots: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, service_type: str, name: str | None = None) -> Any:
        if name is None:
            name = self._resolve(service_type)
        key = f"{service_type}:{name}"
        # 快速路径：已缓存
        with self._lock:
            if key in self._instances:
                return self._instances[key]

        # 检查后端是否在注册表中标记为未实现（锁外，避免阻塞）
        try:
            from infra.config.registry import ModelRegistry
            reg = ModelRegistry()
            backend_meta = reg.get_backend_meta(service_type, name)
            if backend_meta and backend_meta.get("status") == "not_implemented":
                available = registry.list_by_type(service_type)
                raise ValueError(
                    f"{service_type} 后端 '{name}' 尚未实现，请选择其他后端。"
                    f"可用: {available}")
        except ImportError:
            logger.debug("后端模块导入跳过")

        # 创建实例（锁外，避免阻塞其他线程）
        cfg = self._backend_config(service_type, name)
        inst = registry.create(service_type, name, cfg)
        
        with self._lock:
            # 双重检查：另一个线程可能已经创建
            if key in self._instances:
                return self._instances[key]
            self._instances[key] = inst
            self._snapshots[key] = cfg
            return inst

    def get_with_fallback(self, service_type: str, name: str | None = None) -> tuple[Any, str]:
        """获取后端实例，主后端不可用时自动 fallback 到同类型其他后端

        Returns:
            (实例, 实际使用的后端名)
        """
        primary = name or self._resolve(service_type)
        try:
            inst = self.get(service_type, primary)
            # 快速健康检查
            if hasattr(inst, "health_check"):
                ok, _ = inst.health_check()
                if ok:
                    return inst, primary
            else:
                return inst, primary
        except Exception as e:
            logger.warning(f"主后端 {service_type}:{primary} 不可用: {e}")

        # 遍历同类型其他后端（按 priority 排序）
        candidates = registry.list_by_type(service_type)
        last_error = None
        for candidate in candidates:
            if candidate == primary:
                continue
            try:
                inst = self.get(service_type, candidate)
                if hasattr(inst, "health_check"):
                    ok, _ = inst.health_check()
                    if not ok:
                        continue
                logger.info(f"Fallback: {service_type}:{primary} → {candidate}")
                return inst, candidate
            except Exception as e:
                last_error = e
                continue

        # 全部失败，抛出明确错误
        raise RuntimeError(
            f"所有 {service_type} 后端均不可用（主后端 {primary}"
            f"{f', 最后错误: {last_error}' if last_error else ''}）"
        )

    def _resolve(self, service_type: str) -> str:
        # 1. 优先从 models 段读取（如 tts_backend, image_backend）
        models = self._config.get("models", {})
        type_key = self._get_type_key()
        cfg_key = type_key.get(service_type, f"{service_type}_backend")
        name = models.get(cfg_key)
        if name:
            # 配置值可能是工作流模板名（如 sd15/flux），而非 API 后端名
            # 检查是否为已注册的 API 后端（规范化名：fish-speech ↔ fish_speech）
            normalized = name.replace("-", "_")
            if registry.get(service_type, name) or registry.get(service_type, normalized):
                return name
            # YAML 注册表中有定义（如 cosmos/flux/sd15）→ 正常回退，降为 debug
            # YAML 中也没有 → 真正的配置错误，用 warning
            if self._is_yaml_variant(service_type, name):
                logger.debug(f"models.{cfg_key}='{name}' 是 YAML 变体，回退到自动选择")
            else:
                logger.warning(
                    f"models.{cfg_key}='{name}' 不是已注册的 {service_type} API 后端，"
                    f"回退到自动选择。请检查配置是否正确。")
        # 2. 从顶层 service_type 段读取（如 llm.backend, training.backend）
        svc_cfg = self._config.get(service_type, {})
        if isinstance(svc_cfg, dict) and svc_cfg.get("backend"):
            name = svc_cfg["backend"]
            normalized = name.replace("-", "_")
            if registry.get(service_type, name) or registry.get(service_type, normalized):
                return name
        # 3. 自动选择（未显式配置时回退）
        auto = registry.auto_select(service_type, self._config)
        logger.info(f"{service_type} 未显式配置，自动选择: {auto}")
        return auto

    @staticmethod
    def _is_yaml_variant(service_type: str, name: str) -> bool:
        """检查 name 是否在 YAML 注册表中定义（如 cosmos/flux/sd15/cosmos-video）"""
        try:
            from infra.config.registry import ModelRegistry
            return ModelRegistry().get_backend(service_type, name) is not None
        except Exception:
            return False

    def _backend_config(self, service_type: str, name: str) -> dict:
        models = self._config.get("models", {})
        # 尝试原始名和规范化名（fish-speech → fish_speech）
        key = name.replace("-", "_")
        cfg = {
            **models.get(name, models.get(key, {})),
            "timeouts": self._config.get("timeouts", {}),
            "project_dir": self._config.get("_project_dir", ""),
        }
        # 也从顶层 service_type 段读取（如 training, llm 等）
        service_cfg = self._config.get(service_type, {})
        if isinstance(service_cfg, dict):
            cfg.update(service_cfg)
        # image/video 后端自动继承 comfyui 顶层配置（url / api_key）
        if service_type in ("image", "video"):
            comfyui_cfg = self._config.get("comfyui", {})
            if isinstance(comfyui_cfg, dict):
                # 不覆盖已有的显式配置
                for field in ("url", "api_key"):
                    if field not in cfg or not cfg[field]:
                        cfg[field] = comfyui_cfg.get(field, "")
                # video 后端需要 comfyui_url
                if service_type == "video" and "comfyui_url" not in cfg:
                    cfg["comfyui_url"] = comfyui_cfg.get("url", "")
        return cfg

    def reload(self, new_config: dict) -> list[str]:
        # 收集需要重建的后端（锁内只做比较）
        to_rebuild = []
        with self._lock:
            self._config = new_config
            for key, inst in list(self._instances.items()):
                stype, bname = key.split(":", 1)
                old = self._snapshots.get(key, {})
                new = self._backend_config(stype, bname)
                if old != new:
                    to_rebuild.append((key, stype, bname, new, inst))
                    # 先从缓存中移除，防止其他线程使用旧实例
                    del self._instances[key]
                    del self._snapshots[key]

        # 锁外执行耗时的 shutdown + create
        changed = []
        for key, stype, bname, new_cfg, old_inst in to_rebuild:
            # 重新检查：可能另一个 reload 已经处理了
            with self._lock:
                if key in self._instances:
                    continue  # 已被其他线程重建

            if hasattr(old_inst, "shutdown"):
                try:
                    old_inst.shutdown()
                except Exception as e:
                    logger.debug(f"后端关闭异常: {type(e).__name__}: {e}")
            new_inst = registry.create(stype, bname, new_cfg)
            with self._lock:
                self._instances[key] = new_inst
                self._snapshots[key] = new_cfg
            changed.append(key)

        return changed

    def shutdown_all(self):
        """关闭所有后端实例并清空缓存

        注意：不关闭全局 http_pool — 它有独立的进程退出钩子管理生命周期。
        关闭全局池会导致其他代码中已获取的 httpx.Client 意外失效。
        """
        with self._lock:
            for inst in self._instances.values():
                if hasattr(inst, "shutdown"):
                    try:
                        inst.shutdown()
                    except Exception as e:
                        logger.debug(f"{type(e).__name__}: {e}")
            self._instances.clear()
            self._snapshots.clear()


# 全局单例
registry = ServiceRegistry()
