"""API 路由 — 资产管理（上传/下载/共享库）"""
from __future__ import annotations
from infra.config import load_yaml_full

import logging
import shutil
import yaml
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from web.routers.deps import (
    _paths,
    _check_id, _check_filename, _check_entity_type, _safe_path,
)

logger = logging.getLogger(__name__)
router = APIRouter()


_MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB


@router.post("/assets/{entity_type}/{entity_id}/upload")
async def upload_entity_image(entity_type: str, entity_id: str, file: UploadFile = File(...)):
    """上传角色/场景参考图"""
    _check_entity_type(entity_type)
    _check_id(entity_id)

    # 校验实体存在
    p = _paths()
    yaml_dir = "characters" if entity_type == "characters" else "scenes"
    entity_key = "character" if entity_type == "characters" else "scene"
    yaml_path = p.config_entity_yaml(yaml_dir, entity_id)
    if not yaml_path.exists():
        raise HTTPException(404, f"{entity_type} {entity_id} 不存在")

    allowed = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"不支持的文件类型: {ext}，允许: {', '.join(allowed)}")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"文件过大（{len(content) / 1024 / 1024:.1f}MB），最大允许 {_MAX_UPLOAD_SIZE // 1024 // 1024}MB")
    if len(content) < 8:
        raise HTTPException(400, "文件过小，不是有效的图片")

    _MAGIC = {
        b"\x89PNG": ".png",
        b"\xff\xd8\xff": ".jpg",
        b"GIF8": ".gif",
    }
    detected = ""
    for magic, mime_ext in _MAGIC.items():
        if content[:len(magic)] == magic:
            detected = mime_ext
            break
    if not detected and len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        detected = ".webp"
    if not detected:
        raise HTTPException(400, "文件内容不是有效的图片格式")
    if detected not in allowed:
        raise HTTPException(400, f"文件内容不是允许的图片格式: {detected}")

    # 使用检测到的扩展名（而非用户上传的原始扩展名），防止伪装文件
    asset_dir = p.assets_entity_dir(entity_type) / entity_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cover{detected}"
    dest = asset_dir / filename
    with open(dest, "wb") as f:
        f.write(content)

    # 更新 YAML reference_images
    if yaml_path.exists():
        try:
            data = load_yaml_full(yaml_path)
        except yaml.YAMLError as e:
            logger.warning(f"YAML 格式错误 {yaml_path}: {e}")
            data = {}
        entity = data.get(entity_key, {})
        imgs = entity.get("reference_images") or []
        img_url = f"/api/assets/{entity_type}/{entity_id}/{filename}"
        prefix = f"/api/assets/{entity_type}/{entity_id}/cover"
        imgs = [u for u in imgs if not u.startswith(prefix)]
        imgs.append(img_url)
        entity["reference_images"] = imgs
        data[entity_key] = entity
        from infra.config import save_yaml
        save_yaml(yaml_path, data)

    return {"status": "ok", "url": f"/api/assets/{entity_type}/{entity_id}/{filename}"}


@router.get("/assets/{entity_type}/{entity_id}/{filename}")
def get_entity_asset(entity_type: str, entity_id: str, filename: str):
    from fastapi.responses import FileResponse
    _check_entity_type(entity_type)
    _check_id(entity_id)
    _check_filename(filename)
    file_path = _paths().assets_entity_file(entity_type, entity_id, filename)
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {filename}")
    ext = file_path.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
    return FileResponse(str(file_path), media_type=media_types.get(ext, "application/octet-stream"))


@router.get("/assets/{entity_type}/{entity_id}/{sub_dir}/{filename}")
def get_entity_sub_asset(entity_type: str, entity_id: str, sub_dir: str, filename: str):
    from fastapi.responses import FileResponse
    _check_entity_type(entity_type)
    _check_id(entity_id)
    _check_filename(sub_dir)
    _check_filename(filename)
    file_path = _safe_path(_paths().assets_entity_dir(entity_type) / entity_id, sub_dir, filename)
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {sub_dir}/{filename}")
    ext = file_path.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
    return FileResponse(str(file_path), media_type=media_types.get(ext, "application/octet-stream"))


# ══════════════════════════════════════════════════════════
# 共享资产库
# ══════════════════════════════════════════════════════════

def _shared_assets_dir() -> Path:
    d = _paths().shared_assets_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/assets/shared/characters")
def list_shared_characters() -> dict:
    from infra.config import load_yaml_entities
    shared_dir = _shared_assets_dir() / "characters"
    shared_dir.mkdir(parents=True, exist_ok=True)
    items = load_yaml_entities(shared_dir, "character")
    return {"assets": items}


@router.get("/assets/shared/scenes")
def list_shared_scenes() -> dict:
    from infra.config import load_yaml_entities
    shared_dir = _shared_assets_dir() / "scenes"
    shared_dir.mkdir(parents=True, exist_ok=True)
    items = load_yaml_entities(shared_dir, "scene")
    return {"assets": items}


@router.post("/assets/shared/{entity_type}/{entity_id}/copy")
def copy_asset_to_project(entity_type: str, entity_id: str) -> dict:
    _check_entity_type(entity_type)
    _check_id(entity_id)
    shared_dir = _shared_assets_dir() / entity_type
    src = shared_dir / f"{entity_id}.yaml"
    if not src.exists():
        raise HTTPException(404, f"主体库中不存在: {entity_id}")
    p = _paths()
    proj_dir = p.config_entity_dir(entity_type)
    proj_dir.mkdir(parents=True, exist_ok=True)
    dst = proj_dir / f"{entity_id}.yaml"
    if dst.exists():
        raise HTTPException(409, f"项目中已存在: {entity_id}")
    shutil.copy2(str(src), str(dst))
    src_img = shared_dir / entity_id
    if src_img.is_dir():
        dst_img = p.assets_entity_dir(entity_type) / entity_id
        dst_img.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(src_img), str(dst_img), dirs_exist_ok=True)
    return {"status": "ok", "message": f"已复制 {entity_id} 到当前项目"}


@router.post("/assets/{entity_type}/{entity_id}/share")
def add_to_shared_library(entity_type: str, entity_id: str) -> dict:
    _check_entity_type(entity_type)
    _check_id(entity_id)
    p = _paths()
    proj_dir = p.config_entity_dir(entity_type)
    src = proj_dir / f"{entity_id}.yaml"
    if not src.exists():
        raise HTTPException(404, f"项目中不存在: {entity_id}")
    shared_dir = _shared_assets_dir() / entity_type
    shared_dir.mkdir(parents=True, exist_ok=True)
    dst = shared_dir / f"{entity_id}.yaml"
    shutil.copy2(str(src), str(dst))
    src_img = p.assets_entity_dir(entity_type) / entity_id
    if src_img.is_dir():
        dst_img = shared_dir / entity_id
        dst_img.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(src_img), str(dst_img), dirs_exist_ok=True)
    return {"status": "ok", "message": f"已添加 {entity_id} 到主体库"}
