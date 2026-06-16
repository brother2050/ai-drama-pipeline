"""API 路由 — 角色管理"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from web.routers.deps import (
    yaml_list, yaml_save, parse_entity, yaml_delete, yaml_batch_delete,
    _submit_entity_task,
)

logger = logging.getLogger(__name__)
router = APIRouter()

from web.schemas import CharacterData, BatchDeleteRequest  # noqa: E402


@router.get("/characters")
def list_characters() -> dict:
    return {"characters": yaml_list("characters", "character")}


@router.post("/characters")
def save_character(req: CharacterData) -> dict:
    # 用户可显式清空的 AI 生成字段（前端发空串时允许覆盖）
    _CLEARABLE = {"appearance_prompt_en", "body_features"}
    char_id, data = parse_entity(req, clear_fields=_CLEARABLE)
    yaml_save("characters", "character", char_id, data)
    return {"status": "ok", "id": char_id}


@router.delete("/characters/{char_id}")
def delete_character(char_id: str) -> dict:
    from web.routers.deps import _check_id
    _check_id(char_id, "角色 ID")
    yaml_delete("characters", char_id, "角色")
    return {"status": "ok", "id": char_id}


@router.post("/characters/batch-delete")
def batch_delete_characters(req: BatchDeleteRequest) -> dict:
    return yaml_batch_delete("characters", req.ids, "角色")


@router.post("/characters/{char_id}/generate-portrait")
def generate_character_portrait(char_id: str) -> dict:
    from pipeline.tasks import portrait_single_task
    return _submit_entity_task("characters", char_id, "角色", portrait_single_task, require_comfyui=True)


@router.post("/characters/{char_id}/generate-outfit")
def generate_character_outfit(char_id: str, outfit_key: str = Query("default", max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")) -> dict:
    from pipeline.tasks import outfit_single_task
    return _submit_entity_task("characters", char_id, "角色", outfit_single_task, outfit_key)


@router.post("/characters/{char_id}/generate-outfits")
def generate_character_outfits(char_id: str) -> dict:
    from pipeline.tasks import outfits_batch_task
    return _submit_entity_task("characters", char_id, "角色", outfits_batch_task)
