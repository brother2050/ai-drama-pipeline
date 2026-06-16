"""模型注册表扩展 — 图像/视频后端 + 一致性方案查询

从 registry.py 中提取媒体相关查询方法，通过 Mixin 方式保持 ModelRegistry 统一入口。
"""
from __future__ import annotations

import copy
from typing import Any


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
