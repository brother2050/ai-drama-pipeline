"""ComfyUI 节点 Schema 缓存 — 从 /object_info 获取并缓存节点定义

ComfyUISchemaCache: 从 ComfyUI /object_info 端点获取所有节点类型的 schema，
  包括输入定义（名称/类型/可选性/合法值）和输出定义。
  支持本地缓存（JSON 文件）和内存缓存，避免每次预检都请求服务器。

NodeSchema: 单个节点类型的 schema 数据类。
InputDef: 节点输入定义（名称/类型/是否必填/合法值列表）。

用法:
    cache = ComfyUISchemaCache(comfyui_url="http://127.0.0.1:8188")
    cache.refresh()  # 从服务器拉取最新 schema
    schema = cache.get_node_schema("KSampler")  # 获取单个节点 schema
    all_types = cache.get_all_node_types()  # 获取所有已知节点类型
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

__all__ = ["ComfyUISchemaCache", "NodeSchema", "InputDef"]


@dataclass
class InputDef:
    """节点输入定义

    Attributes:
        name: 输入名称（如 "model", "seed", "steps"）
        type: 输入类型（如 "MODEL", "INT", "STRING", "FLOAT", "IMAGE", "LATENT"）
        required: 是否必填
        valid_values: 合法值列表（下拉框选项，如 LoRA 文件名列表），None 表示无限制
        default: 默认值
        min_val: 数值型输入的最小值
        max_val: 数值型输入的最大值
    """

    name: str
    type: str
    required: bool = True
    valid_values: list[str] | None = None
    default: Any = None
    min_val: float | None = None
    max_val: float | None = None


@dataclass
class NodeSchema:
    """单个节点类型的 schema

    Attributes:
        class_type: 节点类型名（如 "KSampler"）
        inputs: 输入定义列表
        output_types: 输出类型列表（如 ["MODEL"] 或 ["IMAGE", "MASK"]）
        output_names: 输出名称列表（可选）
        category: 节点分类（如 "sampling"）
    """

    class_type: str
    inputs: list[InputDef] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    output_names: list[str] = field(default_factory=list)
    category: str = ""

    def get_input(self, name: str) -> InputDef | None:
        """按名称获取输入定义"""
        for inp in self.inputs:
            if inp.name == name:
                return inp
        return None

    def get_required_inputs(self) -> list[InputDef]:
        """获取所有必填输入"""
        return [inp for inp in self.inputs if inp.required]

    def get_output_count(self) -> int:
        """获取输出数量"""
        return len(self.output_types)


class ComfyUISchemaCache:
    """ComfyUI 节点 Schema 缓存

    从 ComfyUI /object_info 端点获取所有节点类型的详细 schema，
    支持本地文件缓存和内存缓存，避免每次预检都请求服务器。

    Attributes:
        comfyui_url: ComfyUI 服务器地址
        cache_file: 本地缓存文件路径（None 时不持久化）
        api_key: ComfyUI API Key（可选）
    """

    def __init__(
        self,
        comfyui_url: str = "",
        cache_file: str | Path | None = None,
        api_key: str = "",
        cache_ttl: int = 3600,
    ) -> None:
        self._url = comfyui_url.rstrip("/")
        self._api_key = api_key
        self._cache_file = Path(cache_file) if cache_file else None
        self._cache_ttl = cache_ttl
        self._schemas: dict[str, NodeSchema] = {}
        self._last_fetch: float = 0.0
        self._loaded = False

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def is_fresh(self) -> bool:
        """检查内存缓存是否仍然有效（未超过 TTL）"""
        if not self._loaded:
            return False
        if self._cache_ttl <= 0:
            return True
        return (time.time() - self._last_fetch) < self._cache_ttl

    def refresh(self, force: bool = False) -> bool:
        """从 ComfyUI 服务器拉取最新 schema

        Args:
            force: 是否强制刷新（忽略缓存）

        Returns:
            True 表示成功刷新，False 表示刷新失败（已加载旧缓存仍可用）
        """
        if not force and self.is_fresh():
            return True

        if not self._url:
            logger.warning("ComfyUI URL 未配置，尝试加载本地缓存")
            return self._load_from_file()

        try:
            r = httpx.get(
                f"{self._url}/object_info",
                headers=self._headers(),
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            self._parse_object_info(data)
            self._last_fetch = time.time()
            self._loaded = True
            self._save_to_file()
            logger.info(f"ComfyUI schema 缓存已刷新: {len(self._schemas)} 个节点类型")
            return True
        except httpx.HTTPError as e:
            logger.warning(f"从 ComfyUI 获取 /object_info 失败: {e}")
            if not self._loaded:
                return self._load_from_file()
            return False
        except (ValueError, KeyError) as e:
            logger.warning(f"解析 ComfyUI /object_info 响应失败: {e}")
            if not self._loaded:
                return self._load_from_file()
            return False

    def _parse_object_info(self, data: dict) -> None:
        """解析 /object_info 响应为 NodeSchema 字典"""
        self._schemas.clear()
        for class_type, info in data.items():
            if not isinstance(info, dict):
                continue
            schema = self._parse_single_node(class_type, info)
            if schema:
                self._schemas[class_type] = schema

    def _parse_single_node(self, class_type: str, info: dict) -> NodeSchema | None:
        """解析单个节点的 object_info"""
        try:
            # 输入定义
            inputs_def = info.get("input", {})
            required_inputs = inputs_def.get("required", {})
            optional_inputs = inputs_def.get("optional", {})

            input_list: list[InputDef] = []

            for name, spec in required_inputs.items():
                inp = self._parse_input_def(name, spec, required=True)
                if inp:
                    input_list.append(inp)

            for name, spec in optional_inputs.items():
                inp = self._parse_input_def(name, spec, required=False)
                if inp:
                    input_list.append(inp)

            # 输出定义
            output_types = info.get("output", [])
            if isinstance(output_types, str):
                output_types = [output_types]
            output_types = [str(t) for t in output_types]

            output_names = info.get("output_name", [])
            if not isinstance(output_names, list):
                output_names = [output_names] if output_names else []
            output_names = [str(n) for n in output_names]

            category = info.get("category", "")

            return NodeSchema(
                class_type=class_type,
                inputs=input_list,
                output_types=output_types,
                output_names=output_names,
                category=category,
            )
        except Exception as e:
            logger.debug(f"解析节点 {class_type} schema 失败: {e}")
            return None

    def _parse_input_def(self, name: str, spec: Any, required: bool) -> InputDef | None:
        """解析单个输入定义

        ComfyUI /object_info 中输入定义格式:
        - ["INT", {"default": 20, "min": 1, "max": 100, "step": 1}]
        - ["STRING", {"default": "", "multiline": True}]
        - ["STRING", {"default": "", "multiline": True}]  # 文本输入
        - [["model1.safetensors", "model2.safetensors"]]  # 下拉框（合法值列表）
        - ["MODEL"]  # 连线输入
        - ["IMAGE"]
        """
        try:
            if not isinstance(spec, list) or len(spec) == 0:
                return None

            type_spec = spec[0]
            constraints = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}

            # 判断类型: 列表表示下拉框（合法值），字符串表示类型名
            if isinstance(type_spec, list):
                # 下拉框: 合法值列表
                valid_values = [str(v) for v in type_spec]
                inp_type = "STRING"
                default = constraints.get("default", valid_values[0] if valid_values else "")
                return InputDef(
                    name=name,
                    type=inp_type,
                    required=required,
                    valid_values=valid_values,
                    default=default,
                )
            elif isinstance(type_spec, str):
                inp_type = type_spec.upper()
                default = constraints.get("default")
                min_val = constraints.get("min")
                max_val = constraints.get("max")

                # 检查是否有合法值列表在 constraints 中
                valid_values = None
                for key in ("values", "options"):
                    if key in constraints and isinstance(constraints[key], list):
                        valid_values = [str(v) for v in constraints[key]]
                        break

                return InputDef(
                    name=name,
                    type=inp_type,
                    required=required,
                    valid_values=valid_values,
                    default=default,
                    min_val=float(min_val) if min_val is not None else None,
                    max_val=float(max_val) if max_val is not None else None,
                )
            else:
                return None
        except Exception as e:
            logger.debug(f"解析输入 {name} 定义失败: {e}")
            return None

    def _load_from_file(self) -> bool:
        """从本地缓存文件加载 schema"""
        if not self._cache_file or not self._cache_file.exists():
            return False
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            self._parse_object_info(data)
            self._last_fetch = self._cache_file.stat().st_mtime
            self._loaded = True
            logger.info(f"从本地缓存加载 ComfyUI schema: {len(self._schemas)} 个节点类型")
            return True
        except Exception as e:
            logger.warning(f"加载本地 schema 缓存失败: {e}")
            return False

    def _save_to_file(self) -> None:
        """将 schema 保存到本地缓存文件"""
        if not self._cache_file:
            return
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            # 保存原始 object_info 格式（便于直接用于 ComfyUI）
            raw_data: dict[str, dict] = {}
            for class_type, schema in self._schemas.items():
                raw_data[class_type] = {
                    "category": schema.category,
                    "output": schema.output_types,
                    "output_name": schema.output_names,
                    "input": {
                        "required": {},
                        "optional": {},
                    },
                }
                for inp in schema.inputs:
                    spec: list = [inp.type]
                    constraints: dict = {}
                    if inp.default is not None:
                        constraints["default"] = inp.default
                    if inp.min_val is not None:
                        constraints["min"] = inp.min_val
                    if inp.max_val is not None:
                        constraints["max"] = inp.max_val
                    if inp.valid_values is not None:
                        spec = [inp.valid_values]
                    if constraints:
                        spec.append(constraints)
                    if inp.required:
                        raw_data[class_type]["input"]["required"][inp.name] = spec
                    else:
                        raw_data[class_type]["input"]["optional"][inp.name] = spec
            self._cache_file.write_text(
                json.dumps(raw_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"保存 schema 缓存到文件失败: {e}")

    def get_node_schema(self, class_type: str) -> NodeSchema | None:
        """获取指定节点类型的 schema"""
        return self._schemas.get(class_type)

    def get_all_node_types(self) -> set[str]:
        """获取所有已知节点类型"""
        return set(self._schemas.keys())

    def has_node_type(self, class_type: str) -> bool:
        """检查节点类型是否已知"""
        return class_type in self._schemas

    def get_model_files(self, input_name: str = "lora_name") -> list[str]:
        """获取指定输入字段的所有合法值（如 LoRA 文件列表）

        用于检查工作流中引用的模型文件是否存在。
        """
        files: list[str] = []
        for schema in self._schemas.values():
            inp = schema.get_input(input_name)
            if inp and inp.valid_values:
                files.extend(inp.valid_values)
        return sorted(set(files))

    def get_lora_files(self) -> list[str]:
        """获取所有可用的 LoRA 文件列表"""
        return self.get_model_files("lora_name")

    def get_checkpoint_files(self) -> list[str]:
        """获取所有可用的 Checkpoint 文件列表"""
        return self.get_model_files("ckpt_name") + self.get_model_files("unet_name")

    def get_vae_files(self) -> list[str]:
        """获取所有可用的 VAE 文件列表"""
        return self.get_model_files("vae_name")

    def get_clip_vision_files(self) -> list[str]:
        """获取所有可用的 CLIP Vision 文件列表"""
        return self.get_model_files("clip_name")
