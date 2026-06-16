"""GPU / 生成参数配置 — 从用户配置热读取

项目本身不使用 GPU，GPU 由三方工具（ComfyUI 等）管理。
本模块提供生成参数（分辨率、步数等）的配置读取。
Config 对象支持 mtime 热读取，文件改了即时生效。

当 generation 段未配置时，返回空值，让各后端使用 models_registry.yaml 中的原生默认参数。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["get_generation_config"]


def get_generation_config(config=None) -> dict:
    """从配置读取生成参数（支持热读取）。

    Args:
        config: Config 对象 或 dict。传 Config 对象时自动检测文件变化并重载；
                传 dict 时直接读取；不传则自行实例化 Config。

    Returns:
        包含 resolution / image_steps 等键的字典。
        未配置 generation 段时，resolution 和 image_steps 为 None（不覆盖后端默认值）。
        video_frames 不再由此处决定，由 build_video() 根据镜头 duration 动态计算。
    """
    result: dict[str, Any] = {
        "resolution": None,
        "aspect_ratio": None,
        "image_steps": None,
        "image_backend": None,
        "video_backend": None,
    }

    # 获取配置数据
    if config is None:
        try:
            from infra.config import Config
            config = Config()
        except Exception as e:
            logger.debug(f"无法加载 Config: {e}")
            return result

    # Config 对象：通过 .data 属性触发 mtime 检测 + 自动重载
    if hasattr(config, "data"):
        gen = config.get("generation", {})
    else:
        gen = config.get("generation", {}) if isinstance(config, dict) else {}

    if gen:
        for key in ("resolution", "aspect_ratio", "image_steps",
                     "image_backend", "video_backend"):
            if key in gen and gen[key] is not None:
                result[key] = gen[key]

    return result
