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


_VIEW_PREFIX_FALLBACK = {
    "front": "front view portrait, facing directly at camera, looking into camera, centered face, full frontal, both eyes visible, symmetrical face, detailed face, clear eyes, sharp focus, well-lit, high resolution skin texture",
    "left_side": (
        "strict left side profile portrait, head turned exactly 90 degrees to the left, "
        "camera positioned directly to the left of the subject, "
        "only the left side of the face is visible from this angle, "
        "right side of face completely hidden and not visible, "
        "left eye visible and looking left, right eye hidden behind nose bridge, "
        "left ear fully visible and prominent, right ear not visible, "
        "nose profile pointing left, nostril visible from left side, "
        "chin and jawline clearly defined from left angle, "
        "left cheek fully illuminated by light from the left, "
        "right cheek in shadow and not visible, "
        "hair parted showing left temple, "
        "dramatic lighting from the left side casting shadows to the right, "
        "asymmetric composition, single eye visible, profile portrait, shot from the left"
    ),
    "right_side": (
        "strict right side profile portrait, head turned exactly 90 degrees to the right, "
        "camera positioned directly to the right of the subject, "
        "only the right side of the face is visible from this angle, "
        "left side of face completely hidden and not visible, "
        "right eye visible and looking right, left eye hidden behind nose bridge, "
        "right ear fully visible and prominent, left ear not visible, "
        "nose profile pointing right, nostril visible from right side, "
        "chin and jawline clearly defined from right angle, "
        "right cheek fully illuminated by light from the right, "
        "left cheek in shadow and not visible, "
        "hair parted showing right temple, "
        "dramatic lighting from the right side casting shadows to the left, "
        "asymmetric composition, single eye visible, profile portrait, shot from the right"
    ),
    "back": "back view, rear view, seen from behind, facing away from viewer, camera behind the subject, back of head visible, back of body visible, no face visible, facing away, looking away from camera, back of shoulders visible, hair seen from behind",
    "three_quarter": "three-quarter view, head turned approximately 45 degrees to the right, camera positioned slightly to the right of the subject, right side of face more visible than left, right ear partially visible, left ear barely visible, nose angled slightly right, looking slightly to the right, one eye closer to camera than the other, asymmetric face lighting, from the right at 45 degrees",
    "full_body": "full body portrait, head to toe, showing entire body from head to feet, complete figure visible, body proportions visible, clothing fully visible, hair fully visible, standing pose, neutral stance, full body shot, wide angle",
}

_VIEW_NEGATIVE_FALLBACK = {
    "left_side": "front view, facing camera, both sides of face visible, looking at viewer, symmetrical face, forward facing, straight on, right side profile, facing right, both eyes visible, both ears visible, mirror image, flipped, reversed, three-quarter view, 45 degree angle, partial profile",
    "right_side": "front view, facing camera, both sides of face visible, looking at viewer, symmetrical face, forward facing, straight on, left side profile, facing left, both eyes visible, both ears visible, mirror image, flipped, reversed, three-quarter view, 45 degree angle, partial profile",
    "back": "front view, facing camera, face visible, looking at viewer, side view, profile, eyes visible, nose visible, mouth visible, facing forward, both sides of face visible, symmetrical face, three-quarter view",
    "three_quarter": "front view, straight on, back view, full profile, 90 degree turn, symmetrical face, facing directly at camera, both ears equally visible, facing away, both sides of face visible",
    "full_body": "close-up, portrait only, face only, headshot, cropped, half body, upper body, bust, missing legs, missing feet, missing arms",
}


class _ViewPromptDict:
    """从 prompt_templates.yaml 懒加载视角 prompt 的 dict-like 对象"""
    def __init__(self, prefix: str, fallback: dict[str, str]):
        self._prefix = prefix
        self._fallback = fallback
        self._cache: dict[str, str] = {}

    def get(self, key: str, default: str = "") -> str:
        if key in self._cache:
            return self._cache[key]
        val = tpl(f"{self._prefix}_{key}")
        result = val if val else self._fallback.get(key, default)
        self._cache[key] = result
        return result

    def __getitem__(self, key: str) -> str:
        val = self.get(key)
        if not val:
            raise KeyError(key)
        return val

    def __contains__(self, key: str) -> bool:
        return bool(self.get(key))


_VIEW_PREFIX = _ViewPromptDict("view_prefix", _VIEW_PREFIX_FALLBACK)
_VIEW_NEGATIVE = _ViewPromptDict("view_negative", _VIEW_NEGATIVE_FALLBACK)


def build_view_prompt(base_en: str, body_features: str, view: str) -> str:
    """从通用 prompt + 身体特征构建视角专属 prompt"""
    prefix = _VIEW_PREFIX.get(view, _VIEW_PREFIX["front"])

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
