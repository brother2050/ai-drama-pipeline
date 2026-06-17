"""数据规范化 — 角色/场景字段补全与格式统一

从 infra/models.py 中提取，保持模块职责单一。
"""
from __future__ import annotations

import copy

from infra.constants import _BIBLE_STR_FIELDS, _BIBLE_DICT_FIELDS, _BIBLE_LIST_FIELDS

__all__ = ["normalize_character", "normalize_scene", "name_to_id", "name_to_safe_id"]

# bible dict 字段必需 key（normalize 时自动补全空值占位）
_BIBLE_REQUIRED_KEYS = {
    "emotional_range": {"happy", "sad", "angry", "surprised", "nervous"},
    "body_language": {"happy", "sad", "nervous"},
}


def _normalize_bible_section(section: dict, *, en_suffix: bool = False) -> dict:
    """规范化 bible 或 bible_en 的字段结构（就地修改）

    类型校验 + dict 字段必需 key 补全（空值占位）。
    en_suffix=True 时，key 带 _en 后缀（用于 bible_en）。
    """
    suffix = "_en" if en_suffix else ""
    for f in _BIBLE_STR_FIELDS:
        section.setdefault(f"{f}{suffix}", "")
    for f in _BIBLE_DICT_FIELDS:
        if not isinstance(section.get(f"{f}{suffix}"), dict):
            section[f"{f}{suffix}"] = {}
    for f in _BIBLE_LIST_FIELDS:
        if not isinstance(section.get(f"{f}{suffix}"), list):
            section[f"{f}{suffix}"] = []

    # 内容要求：dict 字段补全必需 key（空值占位，内容由 LLM 生成）
    req = _BIBLE_REQUIRED_KEYS
    emo = section.get(f"emotional_range{suffix}", {})
    if isinstance(emo, dict):
        for k in req["emotional_range"]:
            emo.setdefault(k, "")
    body = section.get(f"body_language{suffix}", {})
    if isinstance(body, dict):
        for k in req["body_language"]:
            body.setdefault(k, "")

    return section


def name_to_id(name: str) -> str:
    """从 name 生成确定性短 ID（SHA256 前 6 位 hex）

    name 格式: "林夏" 或 "张老板(咖啡店)"（带括号区分同名）
    同名不同角色 → 不同 id（括号内容不同 → hash 不同）
    """
    import hashlib
    return hashlib.sha256(name.encode()).hexdigest()[:6]


def name_to_safe_id(name: str, prefix: str = "item") -> str:
    """中文名 → 安全 ID（仅保留字母数字和 - _），空时返回 prefix"""
    safe = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()
    return safe or prefix


def normalize_character(char: dict) -> dict:
    """规范化角色数据 — 补全缺失字段，统一格式

    bible/bible_en 按需存在：不存在时不创建空壳。
    """
    char = dict(char)

    # 深拷贝嵌套结构
    for key in ("outfits", "bible", "bible_en"):
        if isinstance(char.get(key), dict):
            char[key] = copy.deepcopy(char[key])

    # bible: 只在存在时规范化（不强制创建）
    bible = char.get("bible")
    if isinstance(bible, dict):
        _normalize_bible_section(bible)

    # bible_en: 只在存在时规范化（不强制创建），key 带 _en 后缀
    bible_en = char.get("bible_en")
    if isinstance(bible_en, dict):
        _normalize_bible_section(bible_en, en_suffix=True)

    # 顶级字段
    char.setdefault("appearance_prompt_en", "")
    char.setdefault("body_features", "")
    if not isinstance(char.get("reference_images"), list):
        char["reference_images"] = []

    # outfits: 确保 default 键 + 统一格式
    outfits = char.get("outfits")
    if isinstance(outfits, dict):
        if "default" not in outfits and outfits:
            outfits["default"] = next(iter(outfits.values()))
        for k, v in outfits.items():
            if isinstance(v, str):
                outfits[k] = {"description": v, "reference_images": []}
            elif isinstance(v, dict):
                v.setdefault("description", "")
                v.setdefault("reference_images", [])
    elif outfits is None:
        char["outfits"] = {"default": {"description": "", "reference_images": []}}

    return char


def normalize_scene(scene: dict) -> dict:
    """规范化场景数据 — 补全缺失字段，统一格式"""
    scene = dict(scene)
    scene.setdefault("id", "")
    scene.setdefault("name", "")
    scene.setdefault("description", "")
    scene.setdefault("description_en", "")
    scene.setdefault("lighting", "")
    scene.setdefault("lighting_en", "")
    if not isinstance(scene.get("reference_images"), list):
        scene["reference_images"] = []
    return scene
