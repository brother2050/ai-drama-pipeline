"""模型注册表 — 配置驱动的后端管理

从 config/models_registry.yaml 加载所有后端定义。
新增模型只需改 YAML，不改代码。

设计原则：
- 所有后端元数据的唯一真相来源（严格依赖 YAML，不设内置兜底）
- 零硬编码后端名
- 通用查询接口，按 service_type/name 访问
"""
from __future__ import annotations

import copy
import logging
import os
import threading

import yaml

logger = logging.getLogger(__name__)

__all__ = ["ModelRegistry"]


class ModelRegistry:
    """配置驱动的模型注册表

    所有后端元数据的唯一查询入口。按 service_type + name 访问。
    严格依赖 models_registry.yaml，配置缺失直接报错。
    """

    # 从 YAML 数据动态推导（见 _build_section_map）
    _SECTION_MAP: dict[str, str] = {}

    _instance: "ModelRegistry | None" = None
    _instance_mtime: float = 0.0
    _instance_lock = threading.Lock()

    @staticmethod
    def _resolve_registry_path() -> str:
        """返回注册表文件路径（固定位置：config/models_registry.yaml）"""
        from infra.config import REGISTRY_PATH
        return REGISTRY_PATH

    def __new__(cls):
        """单例缓存：YAML mtime 未变时复用已有实例"""
        path = cls._resolve_registry_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
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
        # __new__ 已完成初始化，__init__ 无需重复加载
        pass

    @staticmethod
    def _build_section_map(data: dict) -> dict[str, str]:
        """从 YAML 数据动态推导 service_type → section_key 映射

        规则：YAML 中以 '_backends' 结尾的 key，去掉后缀即为 service_type。
        例：tts_backends → tts, lipsync_backends → lipsync
        """
        return {k.removesuffix("_backends"): k
                for k in data if k.endswith("_backends")}

    @staticmethod
    def _load(path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"模型注册表不存在: {path}\n"
                f"请确保 config/models_registry.yaml 文件存在。"
            )
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not data:
            raise ValueError(f"模型注册表为空: {path}")
        return data

    # ══════════════════════════════════════════════════════════
    #  全局默认值
    # ══════════════════════════════════════════════════════════

    def get_defaults(self) -> dict[str, str]:
        """返回全局默认后端名映射 {'tts_backend': 'mimo-voicedesign', ...}"""
        return copy.deepcopy(self._data.get("defaults", {}))

    # ══════════════════════════════════════════════════════════
    #  通用后端查询
    # ══════════════════════════════════════════════════════════

    def get_backend(self, service_type: str, name: str) -> dict | None:
        """查询单个后端的完整元数据

        Args:
            service_type: tts / lipsync / llm / music / image / video
            name: 后端名（如 mimo-voicedesign, sd15, animatediff）

        Returns:
            后端元数据 dict，不存在返回 None（返回副本，修改不影响注册表）
        """
        section = self._SECTION_MAP.get(service_type)
        if not section:
            logger.warning(f"未知服务类型: {service_type}")
            return None
        backend = self._data.get(section, {}).get(name)
        return copy.deepcopy(backend) if backend is not None else None

    def get_backend_meta(self, service_type: str, name: str) -> dict | None:
        """查询后端元数据（兼容 services 段）

        先查后端 section（tts_backends 等），再查 services 段（seko, training 等）。

        Returns:
            后端元数据 dict 或 None（返回副本）
        """
        result = self.get_backend(service_type, name)
        if result is not None:
            return result
        # 查 services 段
        svc = self._data.get("services", {}).get(name)
        return copy.deepcopy(svc) if svc is not None else None

    def get_backends(self, service_type: str) -> dict[str, dict]:
        """返回某服务类型的所有后端 {'name': {metadata}}（返回副本）"""
        section = self._SECTION_MAP.get(service_type)
        if not section:
            return {}
        return copy.deepcopy(self._data.get(section, {}))

    def list_backend_names(self, service_type: str) -> list[str]:
        """返回某服务类型的所有后端名列表（返回副本）"""
        section = self._SECTION_MAP.get(service_type)
        if not section:
            return []
        return list(self._data.get(section, {}).keys())

    # ══════════════════════════════════════════════════════════
    #  健康检查
    # ══════════════════════════════════════════════════════════

    def get_health_check(self, service_type: str, name: str) -> dict | None:
        """返回后端的健康检查配置

        Returns:
            {'type': 'http', 'path': '/', 'config_key': 'models.gpt_sovits.api_url'} 或 None（返回副本）
        """
        backend = self.get_backend(service_type, name)
        if backend:
            hc = backend.get("health_check")
            return copy.deepcopy(hc) if hc is not None else None
        return None

    def get_service_health_check(self, service_name: str) -> dict | None:
        """返回辅助服务的健康检查配置（从 services 段读取）

        Args:
            service_name: comfyui / redis / celery / ffmpeg / seko / training

        Returns:
            健康检查配置 dict 或 None（返回副本）
        """
        hc = self._data.get("services", {}).get(service_name, {}).get("health_check")
        return copy.deepcopy(hc) if hc is not None else None

    def get_all_health_checks(self) -> dict[str, dict]:
        """返回所有需要健康检查的项（后端 + 辅助服务）

        Returns:
            {'tts:mimo-voicedesign': {'type': 'api_key_env', ...},
             'comfyui': {'type': 'http', ...}, ...}
        """
        result = {}

        # 后端的健康检查
        for service_type, section in self._SECTION_MAP.items():
            for name, meta in self._data.get(section, {}).items():
                hc = meta.get("health_check")
                if hc:
                    result[f"{service_type}:{name}"] = hc

        # 辅助服务的健康检查
        for name, meta in self._data.get("services", {}).items():
            hc = meta.get("health_check")
            if hc:
                result[name] = hc

        return result

    # ══════════════════════════════════════════════════════════
    #  图像后端
    # ══════════════════════════════════════════════════════════

    def get_image_workflow(self, backend: str) -> str:
        """返回图像后端的工作流文件名"""
        return self._data.get("image_backends", {}).get(backend, {}).get("workflow", "")

    def get_image_defaults(self, backend: str) -> dict:
        """返回图像后端的默认生成参数（返回副本）"""
        return copy.deepcopy(self._data.get("image_backends", {}).get(backend, {}).get("default_params", {}))

    def get_prompt_style(self, image_backend: str) -> str:
        """返回图像后端的 prompt 风格 ('tag' / 'natural')

        - tag: 逗号分隔短语（SD1.5/SDXL，CLIP 编码器）
        - natural: 自然语言段落（Flux/Cosmos，T5 编码器）
        """
        return self._data.get("image_backends", {}).get(image_backend, {}).get("prompt_style", "tag")

    def get_consistency_default(self, image_backend: str) -> str:
        """返回图像后端的默认一致性方案

        Returns:
            'ip_adapter' / 'pulid_flux' / 'none'
        """
        return self._data.get("image_backends", {}).get(image_backend, {}).get("consistency_default", "none")

    # ══════════════════════════════════════════════════════════
    #  视频后端
    # ══════════════════════════════════════════════════════════

    def get_video_workflow(self, backend: str) -> str:
        """返回视频后端的工作流文件名"""
        return self._data.get("video_backends", {}).get(backend, {}).get("workflow", "")

    def get_video_defaults(self, backend: str) -> dict:
        """返回视频后端的默认生成参数（返回副本）"""
        return copy.deepcopy(self._data.get("video_backends", {}).get(backend, {}).get("default_params", {}))

    def get_frame_params(self, video_backend: str) -> dict | None:
        """返回视频后端的帧数注入规则

        Returns:
            {'node_class': 'ADE_StandardStaticContextOptions', 'input_name': 'context_length'}
            或 None（后端未声明帧数注入规则，返回副本）
        """
        fp = self._data.get("video_backends", {}).get(video_backend, {}).get("frame_params")
        return copy.deepcopy(fp) if fp is not None else None

    def get_sampler_node(self, backend: str) -> str:
        """返回后端的采样器节点类型名（image 或 video）"""
        result = self._data.get("image_backends", {}).get(backend, {}).get("sampler_node")
        if result:
            return result
        return self._data.get("video_backends", {}).get(backend, {}).get("sampler_node", "KSampler")

    def get_video_sampler_node(self, backend: str) -> str:
        """返回视频后端的采样器节点类型名"""
        return self._data.get("video_backends", {}).get(backend, {}).get("sampler_node", "KSampler")

    # ══════════════════════════════════════════════════════════
    #  一致性方案
    # ══════════════════════════════════════════════════════════

    def get_consistency_method(self, name: str) -> dict | None:
        """返回一致性方案的元数据

        Returns:
            {'compatible_backends': ['sd15', 'sdxl'], 'config_key': 'ip_adapter',
             'inject_method': '_inject_ip_adapter_plus'}
            或 None（返回副本）
        """
        method = self._data.get("consistency_methods", {}).get(name)
        return copy.deepcopy(method) if method is not None else None

    def get_compatible_consistency(self, image_backend: str) -> list[str]:
        """返回与某图像后端兼容的所有一致性方案名"""
        methods = self._data.get("consistency_methods", {})
        result = []
        for name, meta in methods.items():
            compat = meta.get("compatible_backends", [])
            if "*" in compat or image_backend.lower() in compat:
                result.append(name)
        return result

    # ══════════════════════════════════════════════════════════
    #  生产步骤编排
    # ══════════════════════════════════════════════════════════

    def get_pipeline_steps(self) -> list[dict]:
        """返回生产步骤编排列表

        Returns:
            [{'name': 'tts', 'task': 'pipeline_step_tts', 'tool': 'tts', 'timeout': 120}, ...]
            （返回副本）
        """
        return copy.deepcopy(self._data.get("pipeline_steps", []))

    def valid_image_backends(self) -> set[str]:
        return set(self._data.get("image_backends", {}).keys())

    def valid_video_backends(self) -> set[str]:
        return set(self._data.get("video_backends", {}).keys())

    def get_tts_backends(self) -> dict:
        """获取所有 TTS 后端及其描述（返回副本）"""
        return copy.deepcopy(self._data.get("tts_backends", {}))

    def get_lipsync_backends(self) -> dict:
        return copy.deepcopy(self._data.get("lipsync_backends", {}))

    def get_llm_backends(self) -> dict:
        return copy.deepcopy(self._data.get("llm_backends", {}))

    def get_music_backends(self) -> dict:
        return copy.deepcopy(self._data.get("music_backends", {}))

    # ══════════════════════════════════════════════════════════
    #  服务类型元数据（toolcheck 等模块使用）
    # ══════════════════════════════════════════════════════════

    def get_service_cfg_key(self, service_type: str) -> str:
        """返回服务类型在 defaults 段中的 key 名

        例: 'tts' → 'tts_backend', 'lipsync' → 'lip_sync_backend'
        从 YAML defaults.config_paths 推导，不硬编码映射。
        """
        # config_paths 的 value 格式为 "models.tts_backend" 或 "llm.backend"
        # 提取最后的 key 部分即为 cfg_key
        paths = self._data.get("defaults", {}).get("config_paths", {})
        if service_type in paths:
            return paths[service_type].rsplit(".", 1)[-1]
        return f"{service_type}_backend"

    def get_config_path(self, service_type: str) -> str:
        """返回服务类型在配置文件中的读取路径

        例: 'tts' → 'models.tts_backend', 'llm' → 'llm.backend'
        用于统一 toolcheck 的配置查询逻辑，消除 if service_type == "llm" 分支。
        """
        paths = self._data.get("defaults", {}).get("config_paths", {})
        if service_type in paths:
            return paths[service_type]
        # 兜底: 按惯例拼接
        cfg_key = self.get_service_cfg_key(service_type)
        return f"models.{cfg_key}"

    def get_service_meta(self, name: str) -> dict | None:
        """返回辅助服务的完整元数据（从 services 段读取）

        Returns:
            {'description': '...', 'health_check': {...}, 'backend': '...', 'type': '...'}
            或 None（返回副本）
        """
        svc = self._data.get("services", {}).get(name)
        return copy.deepcopy(svc) if svc is not None else None

    def get_registered_service_types(self) -> list[str]:
        """返回所有已注册的服务类型名（后端注册表 + 辅助服务）

        Returns:
            ['tts', 'lipsync', 'llm', 'music', 'image', 'video', 'comfyui', 'redis', ...]
        """
        types = list(self._SECTION_MAP.keys())  # 后端类型
        types.extend(self._data.get("services", {}).keys())  # 辅助服务
        return types

    def get_backend_modules(self) -> list[tuple[str, str, int]]:
        """返回所有带 module 字段的后端列表（用于懒加载导入）

        扫描所有后端 section + services 段，收集有 module 字段的条目。

        Returns:
            [(service_type, module_path, priority), ...] 按 priority 排序
        """
        modules: list[tuple[str, str, int]] = []
        seen: set[str] = set()

        # 1. 后端 section（tts_backends, lipsync_backends, ...）
        for service_type, section in self._SECTION_MAP.items():
            for _name, meta in self._data.get(section, {}).items():
                if not isinstance(meta, dict):
                    continue
                mod = meta.get("module")
                if not mod or mod in seen:
                    continue
                modules.append((service_type, mod, meta.get("priority", 99)))
                seen.add(mod)

        # 2. services 段（seko, training 等）
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

    def get_consistency_check_map(self) -> dict[str, dict]:
        """返回一致性方案 → 健康检查配置映射（供 toolcheck 使用）

        Returns:
            {'ip_adapter': {'config_key': 'ip_adapter', ...}, 'pulid_flux': {...}}
        """
        return {name: meta for name, meta in self._data.get("consistency_methods", {}).items()
                if name != "none"}

    # ══════════════════════════════════════════════════════════
    #  LLM 模型限制查询（自适应批处理器使用）
    # ══════════════════════════════════════════════════════════

    # 运行时从 API 错误中学到的限制（进程内缓存）
    _discovered_limits: dict[str, dict] = {}

    def get_model_limits(self, model_name: str) -> dict:
        """查询 LLM 模型的 context_window 和 max_output 限制

        三层查找（优先级递减）：
          1. 运行时发现缓存（从 API 错误中自动学到的真实限制）
          2. 静态注册表（models_registry.yaml 的 llm_models 段）
          3. _default 保守默认值

        Returns:
            {"context_window": int, "max_output": int}
        """
        m = model_name.lower()

        # Layer 1: 运行时发现缓存
        if m in self._discovered_limits:
            discovered = self._discovered_limits[m]
            static = self._lookup_static_limits(model_name)
            return {
                "context_window": discovered.get("context_window", static["context_window"]),
                "max_output": discovered.get("max_output", static["max_output"]),
            }

        # Layer 2 + 3: 静态注册表 → _default
        return self._lookup_static_limits(model_name)

    def _lookup_static_limits(self, model_name: str) -> dict:
        """从 llm_models 段查找（精确匹配 → prefix 匹配 → _default）"""
        models = self._data.get("llm_models", {})
        if not models:
            return {"context_window": 8192, "max_output": 4096}

        # 精确匹配
        m = model_name
        if m in models:
            return {"context_window": models[m].get("context_window", 8192),
                    "max_output": models[m].get("max_output", 4096)}

        # prefix 匹配（按 key 长度降序，长 key 优先）
        m_lower = m.lower()
        sorted_keys = sorted(
            (k for k in models if k != "_default"),
            key=len, reverse=True)
        for key in sorted_keys:
            if m_lower.startswith(key.lower()):
                return {"context_window": models[key].get("context_window", 8192),
                        "max_output": models[key].get("max_output", 4096)}

        # 兜底
        default = models.get("_default", {})
        return {"context_window": default.get("context_window", 8192),
                "max_output": default.get("max_output", 4096)}

    @classmethod
    def cache_discovered_limits(cls, model_name: str, limits: dict) -> None:
        """缓存从 API 错误中发现的模型限制（进程内，重启后重置）

        Args:
            model_name: 模型名
            limits: {"context_window": int} 或 {"max_output": int}
        """
        m = model_name.lower()
        cls._discovered_limits.setdefault(m, {}).update(limits)

    @staticmethod
    def parse_limits_from_error(error_text: str) -> dict | None:
        """从 API 错误消息中解析模型限制

        覆盖主流 API 的错误格式：
          - DeepSeek: "valid range of max_tokens is [1, 8192]"
          - OpenAI:   "maximum context length is 128000 tokens"
          - 智谱:     "max_tokens must be less than or equal to 8192"

        Returns:
            {"max_output": int} 或 {"context_window": int} 或 None
        """
        import re
        result = {}

        # max_tokens 解析
        m = re.search(r'valid\s+range.*?\[\s*\d+\s*,\s*(\d+)\s*\]', error_text, re.I)
        if m:
            result["max_output"] = int(m.group(1))
        else:
            m = re.search(r'max_tokens.*?(?:less than or equal to|<=|不超过|上限为?)\s*(\d{3,6})', error_text, re.I)
            if m:
                result["max_output"] = int(m.group(1))
            else:
                m = re.search(r'max_tokens.*?\b(\d{3,6})\b', error_text, re.I)
                if m:
                    result["max_output"] = int(m.group(1))

        # context_window 解析
        m = re.search(r'context.*?length.*?(\d{4,7})', error_text, re.I)
        if m:
            result["context_window"] = int(m.group(1))
        else:
            m = re.search(r'maximum.*?(\d{4,7})\s*tokens', error_text, re.I)
            if m:
                result["context_window"] = int(m.group(1))

        return result if result else None

    def reload(self):
        with self._instance_lock:
            self._data = self._load(self._resolve_registry_path())
            self._SECTION_MAP = self._build_section_map(self._data)
            # 更新缓存 mtime，避免下次 __new__ 重新加载
            try:
                ModelRegistry._instance_mtime = os.path.getmtime(self._resolve_registry_path())
            except OSError:
                logger.debug("注册表 mtime 更新失败")
