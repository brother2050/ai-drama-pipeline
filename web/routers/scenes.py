"""API 路由 — 场景管理"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from web.routers.deps import (
    _cfg_path, _paths,
    _check_id, _submit_task,
    yaml_list, yaml_save, parse_entity, yaml_delete, yaml_batch_delete,
)

logger = logging.getLogger(__name__)
router = APIRouter()

from web.schemas import SceneData, BatchDeleteRequest  # noqa: E402


@router.get("/scenes")
def list_scenes() -> dict:
    return {"scenes": yaml_list("scenes", "scene")}


@router.post("/scenes")
def save_scene(req: SceneData) -> dict:
    scene_id, data = parse_entity(req)
    yaml_save("scenes", "scene", scene_id, data)
    return {"status": "ok", "id": scene_id}


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: str) -> dict:
    _check_id(scene_id, "场景 ID")
    yaml_delete("scenes", scene_id, "场景")
    return {"status": "ok", "id": scene_id}


@router.post("/scenes/batch-delete")
def batch_delete_scenes(req: BatchDeleteRequest) -> dict:
    return yaml_batch_delete("scenes", req.ids, "场景")


@router.post("/scenes/{scene_id}/generate-image")
def generate_scene_image(scene_id: str):
    _check_id(scene_id, "场景 ID")
    scene_yaml_path = _paths().scene_yaml(scene_id)
    if not scene_yaml_path.exists():
        raise HTTPException(404, f"场景 {scene_id} 不存在")
    from pipeline.tasks import scene_image_single_task
    return _submit_task(scene_image_single_task, _cfg_path(), scene_id)
