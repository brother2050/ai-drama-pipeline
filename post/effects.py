"""特效处理"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

__all__ = ["build_color_grade_filter"]


def build_color_grade_filter(params: dict) -> str | None:
    """构建调色过滤器"""
    filters = []
    if "brightness" in params:
        filters.append(f"eq=brightness={params['brightness']}")
    if "contrast" in params:
        filters.append(f"eq=contrast={params['contrast']}")
    if "saturation" in params:
        filters.append(f"eq=saturation={params['saturation']}")
    return ",".join(filters) if filters else None
