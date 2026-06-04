"""API 路由 — 角色管理"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from web.routers.deps import (
    _cfg_path, _paths,
    _check_id, _submit_task,
    require_tool,
    yaml_list, yaml_save, parse_entity, yaml_delete, yaml_batch_delete,
)

logger = logging.getLogger(__name__)
router = APIRouter()

from web.schemas import CharacterData, BatchDeleteRequest


@router.get("/characters")
def list_characters() -> dict:
    return {"characters": yaml_list("characters", "character")}


@router.post("/characters")
def save_character(req: CharacterData) -> dict:
    char_id, data = parse_entity(req)
    yaml_save("characters", "character", char_id, data)
    return {"status": "ok", "id": char_id}


@router.delete("/characters/{char_id}")
def delete_character(char_id: str) -> dict:
    _check_id(char_id, "角色 ID")
    yaml_delete("characters", char_id, "角色")
    return {"status": "ok", "id": char_id}


@router.post("/characters/batch-delete")
def batch_delete_characters(req: BatchDeleteRequest) -> dict:
    return yaml_batch_delete("characters", req.ids, "角色")


@router.post("/characters/{char_id}/generate-portrait")
def generate_character_portrait(char_id: str) -> dict:
    _check_id(char_id, "角色 ID")
    char_yaml_path = _paths().character_yaml(char_id)
    if not char_yaml_path.exists():
        raise HTTPException(404, f"角色 {char_id} 不存在")
    require_tool("comfyui")
    from pipeline.tasks import portrait_single_task
    return _submit_task(portrait_single_task, _cfg_path(), char_id)


@router.post("/characters/{char_id}/generate-outfit")
def generate_character_outfit(char_id: str, outfit_key: str = "default") -> dict:
    _check_id(char_id, "角色 ID")
    char_yaml_path = _paths().character_yaml(char_id)
    if not char_yaml_path.exists():
        raise HTTPException(404, f"角色 {char_id} 不存在")
    from pipeline.tasks import outfit_single_task
    return _submit_task(outfit_single_task, _cfg_path(), char_id, outfit_key)


@router.post("/characters/{char_id}/generate-outfits")
def generate_character_outfits(char_id: str) -> dict:
    _check_id(char_id, "角色 ID")
    char_yaml_path = _paths().character_yaml(char_id)
    if not char_yaml_path.exists():
        raise HTTPException(404, f"角色 {char_id} 不存在")
    from pipeline.tasks import outfits_batch_task
    return _submit_task(outfits_batch_task, _cfg_path(), char_id)
