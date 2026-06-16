"""视角处理 — 角色外貌 prompt 构建"""

from __future__ import annotations

import logging
import re

from engines.prompt.compiler import tpl

logger = logging.getLogger(__name__)


def get_view_appearance(char: dict, shot_type: str, *, view_key: str = "") -> str:
    """获取角色在指定视角的模型友好英文 prompt"""
    if not view_key:
        if "背面" in shot_type:
            view_key = "back"
        elif "侧面" in shot_type:
            view_key = "left_side"
        elif "3/4" in shot_type or "三人" in shot_type:
            view_key = "three_quarter"
        else:
            view_key = "front"

    base_en = char.get("appearance_prompt_en", "")
    if not base_en:
        base_en = char.get("appearance", "")
        if not base_en:
            return ""

    age = char.get("age", "")
    if age and age not in base_en:
        base_en = f"{age} years old, {base_en}"

    from engines.prompt.builder import _ensure_gender_tag
    base_en = _ensure_gender_tag(base_en, char.get("gender", ""))

    body_features = char.get("body_features", "")
    return build_view_prompt(base_en, body_features, view_key)


def get_view_prefix(view: str, default_view: str = "front") -> str:
    """从 prompt_templates.yaml 读取视角前缀 prompt"""
    return tpl(f"view_prefix_{view}") or tpl(f"view_prefix_{default_view}")


def get_view_negative(view_key: str) -> str:
    """从 prompt_templates.yaml 读取视角负面 prompt"""
    return tpl(f"view_negative_{view_key}")


def build_view_prompt(base_en: str, body_features: str, view: str) -> str:
    """从通用 prompt + 身体特征构建视角专属 prompt"""
    prefix = get_view_prefix(view)

    filtered_base = _filter_features_in_text(base_en, view) if base_en else ""
    parts = [prefix, filtered_base]

    if body_features and body_features.strip():
        features = body_features.strip()
        if view == "back":
            features = _filter_back_features(features)
        elif view == "left_side":
            features = _filter_side_features(features, keep_side="left")
        elif view == "right_side":
            features = _filter_side_features(features, keep_side="right")
        if features:
            parts.append(features)

    return ", ".join(parts)


def _filter_back_features(features: str) -> str:
    """从身体特征中移除面部特征（背面不可见）"""
    face_keywords = {"eye", "nose", "mouth", "lip", "brow", "eyebrow", "eyelash", "forehead", "cheek", "chin"}
    parts = [p.strip() for p in features.split(",") if p.strip()]
    filtered = [p for p in parts if not any(kw in p.lower() for kw in face_keywords)]
    return ", ".join(filtered)


_OPPOSITE_SIDE_RE = {
    "left": re.compile(r'(?<![a-zA-Z])right(?![a-zA-Z])', re.IGNORECASE),
    "right": re.compile(r'(?<![a-zA-Z])left(?![a-zA-Z])', re.IGNORECASE),
}


def _filter_features_in_text(text: str, view: str) -> str:
    """从通用 prompt 文本中按视角过滤含对侧信息的身体特征短语"""
    if view == "left_side":
        return _filter_side_features(text, keep_side="left")
    elif view == "right_side":
        return _filter_side_features(text, keep_side="right")
    elif view == "back":
        return _filter_back_features(text)
    return text


def _filter_side_features(features: str, keep_side: str) -> str:
    """过滤身体特征，仅保留指定侧面可见的特征"""
    pattern = _OPPOSITE_SIDE_RE.get(keep_side)
    if not pattern:
        return features
    parts = [p.strip() for p in features.split(",") if p.strip()]
    filtered = [p for p in parts if not pattern.search(p)]
    return ", ".join(filtered)
