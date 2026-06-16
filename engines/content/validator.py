"""实体校验 — 角色/场景数据校验+补全"""

from __future__ import annotations

import logging

from infra.constants import _BIBLE_STR_FIELDS, _BIBLE_DICT_FIELDS, _BIBLE_LIST_FIELDS
from infra.normalize import normalize_character, normalize_scene as _normalize_scene

logger = logging.getLogger(__name__)

__all__ = ["validate_character", "validate_scene", "check_entity_completeness"]


def validate_character(entity: dict) -> dict:
    """校验+补全角色数据（委托 normalize_character 统一处理）"""
    entity.setdefault("name", "")
    entity.setdefault("gender", "")
    entity.setdefault("appearance", "")

    # 委派给 normalize_character 处理 outfits / bible / bible_en 等深层结构
    return normalize_character(entity)


def validate_scene(entity: dict) -> dict:
    """校验+补全场景数据（委托 normalize_scene 统一处理）"""
    return _normalize_scene(entity)


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
