"""实体校验 — 角色/场景数据校验+补全"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["validate_character", "validate_scene", "check_entity_completeness"]

# bible 子字段定义
_BIBLE_STR_FIELDS = ("core_traits", "speech_patterns", "voice_description")
_BIBLE_DICT_FIELDS = ("relationships", "emotional_range", "body_language")
_BIBLE_LIST_FIELDS = ("habits", "taboos")


def _normalize_bible_en(bible_en: dict) -> None:
    """规范化 bible_en — 兼容 LLM 输出不带 _en 后缀的情况"""
    for f in _BIBLE_STR_FIELDS:
        en_key = f"{f}_en"
        if not bible_en.get(en_key) and bible_en.get(f):
            bible_en[en_key] = bible_en[f]
    for f in _BIBLE_DICT_FIELDS:
        en_key = f"{f}_en"
        if not bible_en.get(en_key) and bible_en.get(f):
            bible_en[en_key] = bible_en[f]
    for f in _BIBLE_LIST_FIELDS:
        en_key = f"{f}_en"
        if not bible_en.get(en_key) and bible_en.get(f):
            bible_en[en_key] = bible_en[f]


def validate_character(entity: dict) -> dict:
    """校验+补全角色数据"""
    entity.setdefault("name", "")
    entity.setdefault("gender", "")
    entity.setdefault("appearance", "")
    entity.setdefault("appearance_prompt_en", "")
    entity.setdefault("body_features", "")

    outfits = entity.get("outfits")
    if not isinstance(outfits, dict) or not outfits:
        outfits = {"default": {"description": "", "description_en": "", "reference_images": []}}
        entity["outfits"] = outfits
    for okey, odata in outfits.items():
        if isinstance(odata, str):
            outfits[okey] = {"description": odata, "description_en": "", "reference_images": []}
        elif isinstance(odata, dict):
            odata.setdefault("description", "")
            odata.setdefault("description_en", "")
            odata.setdefault("reference_images", [])

    bible = entity.get("bible")
    if not isinstance(bible, dict):
        bible = {}
        entity["bible"] = bible
    for f in _BIBLE_STR_FIELDS:
        bible.setdefault(f, "")
    for f in _BIBLE_DICT_FIELDS:
        if not isinstance(bible.get(f), dict):
            bible[f] = {}
    for f in _BIBLE_LIST_FIELDS:
        if not isinstance(bible.get(f), list):
            bible[f] = []

    bible_en = entity.get("bible_en")
    if not isinstance(bible_en, dict):
        bible_en = {}
        entity["bible_en"] = bible_en
    _normalize_bible_en(bible_en)
    for f in _BIBLE_STR_FIELDS:
        bible_en.setdefault(f"{f}_en", "")
    for f in _BIBLE_DICT_FIELDS:
        k = f"{f}_en"
        if not isinstance(bible_en.get(k), dict):
            bible_en[k] = {}
    for f in _BIBLE_LIST_FIELDS:
        k = f"{f}_en"
        if not isinstance(bible_en.get(k), list):
            bible_en[k] = []

    return entity


def validate_scene(entity: dict) -> dict:
    """校验+补全场景数据"""
    entity.setdefault("name", "")
    entity.setdefault("description", "")
    entity.setdefault("description_en", "")
    entity.setdefault("lighting", "")
    entity.setdefault("lighting_en", "")
    return entity


def check_entity_completeness(entity: dict, entity_key: str) -> list[str]:
    """检查实体数据完整性，返回缺失字段名列表"""
    missing = []
    if entity_key == "character":
        if not entity.get("appearance_prompt_en"):
            missing.append("appearance_prompt_en")
        outfits = entity.get("outfits", {})
        for okey, odata in outfits.items():
            if isinstance(odata, dict) and not odata.get("description_en"):
                missing.append(f"outfits.{okey}.description_en")
        bible_en = entity.get("bible_en", {})
        for f in _BIBLE_STR_FIELDS:
            if not bible_en.get(f"{f}_en"):
                missing.append(f"bible_en.{f}_en")
        for f in ("emotional_range", "body_language"):
            en_dict = bible_en.get(f"{f}_en", {})
            if isinstance(en_dict, dict) and not en_dict:
                missing.append(f"bible_en.{f}_en")
    elif entity_key == "scene":
        if not entity.get("description_en"):
            missing.append("description_en")
        if not entity.get("lighting_en"):
            missing.append("lighting_en")
    return missing
