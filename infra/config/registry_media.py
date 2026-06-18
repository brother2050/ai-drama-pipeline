"""模型注册表扩展 — 图像/视频后端 + 一致性方案查询

从 registry.py 中提取媒体相关查询方法，通过 Mixin 方式保持 ModelRegistry 统一入口。
"""
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MediaRegistryMixin:
    """图像/视频后端 + 一致性方案的查询方法"""

    # 由 ModelRegistry 注入
    _data: dict[str, Any]
    _deepcopy: Any  # 实例方法引用

    # ══════════════════════════════════════════════════════════
    #  图像后端
    # ══════════════════════════════════════════════════════════

    def _image_backend(self, backend: str) -> dict[str, Any]:
        return self._data.get("image_backends", {}).get(backend, {})

    def get_image_workflow(self, backend: str) -> str:
        return self._image_backend(backend).get("workflow", "")

    def get_prompt_style(self, image_backend: str) -> str:
        return self._image_backend(image_backend).get("prompt_style", "tag")

    def get_consistency_default(self, image_backend: str) -> str:
        return self._image_backend(image_backend).get("consistency_default", "none")

    def get_consistency_pipeline(self, image_backend: str,
                                  available_nodes: set[str] | None = None) -> list[str]:
        """解析后端的一致性管道，返回方法名列表。

        优先级:
        1. backend.consistency_pipeline → 命名管道 → 展开 layers
        2. backend.consistency_default → 单方法 → [method]
        3. "none" → []

        管道层不可用时自动应用 fallback（单层降级）。
        两层检查: (1) node_graph YAML 定义存在 (2) required_comfyui_nodes 在 ComfyUI 可用
        """
        backend_meta = self._image_backend(image_backend)
        pipe_name = backend_meta.get("consistency_pipeline", "")

        if not pipe_name:
            # 向后兼容: consistency_default
            default = backend_meta.get("consistency_default", "none")
            return [] if default == "none" else [default]

        if pipe_name == "none":
            return []

        pipelines = self._data.get("consistency_pipelines", {})
        if pipe_name in pipelines:
            return self._resolve_pipeline_layers(pipe_name, pipelines[pipe_name], available_nodes)

        # 直接方法名（向后兼容: consistency_pipeline 直接指定单个方法名）
        if pipe_name != "none" and available_nodes is not None:
            required = self.get_layer_required_nodes(pipe_name)
            if required and not required.issubset(available_nodes):
                missing_plugins = required - available_nodes
                logger.warning(f"{pipe_name} 需要 ComfyUI 节点 {missing_plugins}，不可用，跳过")
                return []
        return [pipe_name] if pipe_name != "none" else []

    def _resolve_pipeline_layers(self, pipe_name: str, pipe_def: dict,
                                  available_nodes: set[str] | None = None) -> list[str]:
        """解析管道各层可用性，自动降级

        两层检查:
        1. node_graph YAML 定义是否存在
        2. required_comfyui_nodes 是否在 ComfyUI 服务器可用（仅当 available_nodes 提供时）
        """
        layers = pipe_def.get("layers", [])
        if not layers:
            return []

        # 第一层检查: node_graph YAML 定义是否存在
        yaml_available = [l for l in layers if self.get_node_graph(l) is not None]

        # 第二层检查: ComfyUI 节点是否实际可用
        missing_plugins: set[str] = set()
        available = yaml_available
        if available_nodes is not None:
            available = []
            for l in yaml_available:
                required = self.get_layer_required_nodes(l)
                if required and not required.issubset(available_nodes):
                    missing_plugins.update(required - available_nodes)
                    logger.info(f"管道层 {l} 需要 ComfyUI 节点 {required - available_nodes}，不可用")
                    continue
                available.append(l)

        if len(available) == len(layers):
            return layers  # 全可用

        if missing_plugins:
            missing = set(layers) - set(available)
            logger.info(f"ComfyUI 缺少插件节点 {missing_plugins}，管道层 {missing} 不可用")

        missing = set(layers) - set(available)
        fallback = pipe_def.get("fallback", "")

        if fallback and fallback != "none" and self.get_node_graph(fallback):
            # 回退层也要检查 ComfyUI 可用性
            if available_nodes is not None:
                fb_required = self.get_layer_required_nodes(fallback)
                if fb_required and not fb_required.issubset(available_nodes):
                    logger.warning(f"管道 {pipe_name} 缺少层 {missing}，回退目标 {fallback} 也缺少插件 {fb_required - available_nodes}")
                    if available:
                        logger.warning(f"管道 {pipe_name} 部分层可用 {available}，继续使用")
                        return available
                    logger.warning(f"管道 {pipe_name} 全部不可用，跳过一致性")
                    return []
            logger.warning(f"管道 {pipe_name} 缺少层 {missing}，回退到 {fallback}")
            return [fallback]

        if available:
            logger.warning(f"管道 {pipe_name} 部分层不可用 {missing}，继续使用 {available}")
            return available

        logger.warning(f"管道 {pipe_name} 全部不可用，跳过一致性")
        return []

    def get_layer_required_nodes(self, method: str) -> set[str]:
        """获取一致性方法所需的 ComfyUI 节点类型集合"""
        graph_def = self.get_node_graph(method) or {}
        return set(graph_def.get("required_comfyui_nodes", []))

    def valid_image_backends(self) -> set[str]:
        return set(self._data.get("image_backends", {}).keys())

    def get_sampler_node(self, backend: str) -> str:
        result = self._image_backend(backend).get("sampler_node")
        if result:
            return result
        return self._data.get("video_backends", {}).get(backend, {}).get("sampler_node", "KSampler")

    # ══════════════════════════════════════════════════════════
    #  视频后端
    # ══════════════════════════════════════════════════════════

    def get_video_workflow(self, backend: str) -> str:
        return self._data.get("video_backends", {}).get(backend, {}).get("workflow", "")

    def get_video_defaults(self, backend: str) -> dict[str, Any]:
        return copy.deepcopy(self._data.get("video_backends", {}).get(backend, {}).get("default_params", {}))

    def get_frame_params(self, video_backend: str) -> dict[str, Any] | None:
        fp = self._data.get("video_backends", {}).get(video_backend, {}).get("frame_params")
        return self._deepcopy(fp)

    def get_video_prompts(self) -> dict[str, Any]:
        return copy.deepcopy(self._data.get("video_prompts", {}))

    def get_video_sampler_node(self, backend: str) -> str:
        return self._data.get("video_backends", {}).get(backend, {}).get("sampler_node", "KSampler")

    def valid_video_backends(self) -> set[str]:
        return set(self._data.get("video_backends", {}).keys())

    # ══════════════════════════════════════════════════════════
    #  一致性方案
    # ══════════════════════════════════════════════════════════

    def get_consistency_method(self, name: str) -> dict[str, Any] | None:
        return self._deepcopy(self._data.get("consistency_methods", {}).get(name))

    def get_node_graph(self, name: str) -> dict[str, Any] | None:
        return self._deepcopy(self._data.get("node_graphs", {}).get(name))

    def list_node_graphs(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._data.get("node_graphs", {}))

    def get_consistency_check_map(self) -> dict[str, dict[str, Any]]:
        return {n: m for n, m in self._data.get("consistency_methods", {}).items() if n != "none"}

    def get_consistency_node_types(self) -> set[str]:
        return {m.get("required_comfyui_node", "") for n, m in
                self._data.get("consistency_methods", {}).items()
                if n != "none" and m.get("required_comfyui_node")}
