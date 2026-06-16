"""API 路由 — 资产管理（上传/下载/共享库）"""
from __future__ import annotations
from infra.config import load_yaml_full

import logging
import os
import shutil
import tempfile
import yaml
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from web.routers.deps import (
    _paths,
    raise_not_found,
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
        raise_not_found(entity_type, entity_id)

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
    # 原子写入：先写临时文件再 rename，防并发/崩溃损坏
    fd, tmp = tempfile.mkstemp(dir=str(asset_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, str(dest))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

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


def _upload_single_to_gpt_sovits(char_id: str, local_path: str, role: str) -> str:
    """上传单个音频到 GPT-SoVITS 服务器，返回服务器路径。失败返回空串。"""
    from infra.config import SYSTEM_CONFIG_PATH, load_config
    from api.backends.tts.gpt_sovits import upload_audio
    sys_cfg = load_config(SYSTEM_CONFIG_PATH)
    api_url = (sys_cfg.get("models", {}).get("gpt_sovits", {}) or {}).get("api_url", "").rstrip("/")
    if not api_url:
        return ""
    ext = Path(local_path).suffix
    fname = f"{char_id}_ref{ext}" if role == "primary" else f"{char_id}_aux_{Path(local_path).stem}{ext}"
    try:
        return upload_audio(api_url, local_path, fname)
    except Exception as e:
        logger.debug(f"自动同步到 GPT-SoVITS 失败（不阻断上传）: {e}")
    return ""


@router.post("/assets/characters/{char_id}/voice/upload")
async def upload_voice_reference(
    char_id: str,
    file: UploadFile = File(...),
    role: str = "primary",
):
    """上传角色参考音频（GPT-SoVITS / CosyVoice 等语音克隆后端使用）

    Args:
        role: "primary" = 主参考音频（覆盖 ref.{ext}），"aux" = 辅助参考音频（追加到 aux_{n}.{ext}）
    """
    _check_id(char_id)
    if role not in ("primary", "aux"):
        raise HTTPException(400, "role 必须是 primary 或 aux")
    p = _paths()
    yaml_path = p.character_yaml(char_id)
    if not yaml_path.exists():
        raise_not_found("characters", char_id)

    allowed = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"不支持的音频格式: {ext}，允许: {', '.join(allowed)}")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "音频文件过大，最大 50MB")
    if len(content) < 1000:
        raise HTTPException(400, "文件过小，不是有效的音频")

    # 存储到 assets/characters/{char_id}/voice/
    voice_dir = p.character_asset_dir(char_id) / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)

    if role == "primary":
        filename = f"ref{ext}"
    else:
        # 辅助文件：找到下一个可用编号
        existing = sorted(voice_dir.glob("aux_*"))
        next_idx = len(existing)
        filename = f"aux_{next_idx}{ext}"

    dest = voice_dir / filename

    fd, tmp = tempfile.mkstemp(dir=str(voice_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, str(dest))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    # 更新角色 YAML 的 voice 配置（写入当前 TTS 后端专属段）
    try:
        from infra.config import load_config, SYSTEM_CONFIG_PATH
        sys_cfg = load_config(SYSTEM_CONFIG_PATH)
        from infra.config import cfg_get
        tts_backend = cfg_get(sys_cfg, "models.tts_backend", "mimo-voicedesign")
        backend_key = tts_backend.replace("-", "_")

        data = load_yaml_full(yaml_path) if yaml_path.exists() else {}
        entity = data.get("character", {})
        voice = entity.get("voice") or {}
        backend_cfg = voice.get(backend_key) or {}

        if role == "primary":
            backend_cfg["reference_audio"] = str(dest)
        else:
            aux_paths = backend_cfg.get("aux_ref_audio_paths") or []
            if not isinstance(aux_paths, list):
                aux_paths = []
            aux_paths.append(str(dest))
            backend_cfg["aux_ref_audio_paths"] = aux_paths
        voice[backend_key] = backend_cfg
        entity["voice"] = voice
        data["character"] = entity
        from infra.config import save_yaml
        save_yaml(yaml_path, data)
    except Exception as e:
        logger.warning(f"更新 voice 配置失败: {e}")

    return {"status": "ok", "role": role, "path": str(dest),
            "url": f"/api/assets/characters/{char_id}/voice/{filename}"}


@router.delete("/assets/characters/{char_id}/voice/{filename}")
def delete_voice_file(char_id: str, filename: str) -> dict:
    """删除角色参考音频文件（同时更新 YAML voice 配置）"""
    _check_id(char_id)
    _check_filename(filename)
    p = _paths()
    voice_dir = p.character_asset_dir(char_id) / "voice"
    file_path = _safe_path(voice_dir, filename)
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {filename}")

    file_path.unlink()

    # 更新 YAML：从当前 TTS 后端专属段的 reference_audio 或 aux_ref_audio_paths 中移除
    yaml_path = p.character_yaml(char_id)
    try:
        from infra.config import load_config, SYSTEM_CONFIG_PATH
        sys_cfg = load_config(SYSTEM_CONFIG_PATH)
        from infra.config import cfg_get
        tts_backend = cfg_get(sys_cfg, "models.tts_backend", "mimo-voicedesign")
        backend_key = tts_backend.replace("-", "_")

        data = load_yaml_full(yaml_path) if yaml_path.exists() else {}
        entity = data.get("character", {})
        voice = entity.get("voice") or {}
        backend_cfg = voice.get(backend_key) or {}
        removed_from = ""
        if backend_cfg.get("reference_audio") == str(file_path):
            backend_cfg["reference_audio"] = ""
            removed_from = "primary"
        aux_paths = backend_cfg.get("aux_ref_audio_paths") or []
        if isinstance(aux_paths, list) and str(file_path) in aux_paths:
            aux_paths.remove(str(file_path))
            backend_cfg["aux_ref_audio_paths"] = aux_paths
            removed_from = removed_from or "aux"
        voice[backend_key] = backend_cfg
        entity["voice"] = voice
        data["character"] = entity
        from infra.config import save_yaml
        save_yaml(yaml_path, data)
    except Exception as e:
        logger.warning(f"更新 voice 配置失败: {e}")

    return {"status": "ok", "filename": filename, "removed_from": removed_from}


@router.post("/assets/characters/{char_id}/voice/sync-to-server")
def sync_voice_to_gpt_sovits(char_id: str) -> dict:
    """将角色的参考音频同步到 GPT-SoVITS 服务器（通过 /upload_refer 端点）"""
    _check_id(char_id)
    p = _paths()
    yaml_path = p.character_yaml(char_id)
    if not yaml_path.exists():
        raise_not_found("characters", char_id)

    data = load_yaml_full(yaml_path)
    voice = data.get("character", {}).get("voice") or {}
    backend_cfg = voice.get("gpt_sovits") or {}
    ref_audio = backend_cfg.get("reference_audio", "")
    aux_paths = backend_cfg.get("aux_ref_audio_paths") or []

    if not ref_audio and not aux_paths:
        raise HTTPException(400, "角色未配置参考音频（gpt_sovits 段）")

    # 校验 GPT-SoVITS 可用性（sync 端点需明确报错，upload 端点由 helper 静默处理）
    from infra.config import SYSTEM_CONFIG_PATH, load_config
    sys_cfg = load_config(SYSTEM_CONFIG_PATH)
    api_url = (sys_cfg.get("models", {}).get("gpt_sovits", {}) or {}).get("api_url", "").rstrip("/")
    if not api_url:
        raise HTTPException(400, "GPT-SoVITS api_url 未配置")

    uploaded = []
    errors = []

    all_files = []
    if ref_audio and Path(ref_audio).exists():
        all_files.append(("primary", ref_audio))
    for ap in aux_paths:
        if ap and Path(ap).exists():
            all_files.append(("aux", ap))

    for role, fpath in all_files:
        server_path = _upload_single_to_gpt_sovits(char_id, fpath, role)
        if server_path:
            uploaded.append({"role": role, "local_path": fpath, "server_path": server_path})
        else:
            errors.append(f"{Path(fpath).name}: 上传失败")

    # 不修改 YAML 中的 reference_audio — GPT-SoVITS 后端的 _resolve_path
    # 会自动处理本地→服务器路径转换，避免切换 TTS 后端后路径失效。

    return {"status": "ok", "uploaded": uploaded, "errors": errors}


@router.get("/assets/characters/{char_id}/voice")
def list_voice_files(char_id: str) -> dict:
    """列出角色的参考音频文件"""
    _check_id(char_id)
    voice_dir = _paths().character_asset_dir(char_id) / "voice"
    if not voice_dir.exists():
        return {"files": []}
    files = []
    for f in sorted(voice_dir.iterdir()):
        if f.suffix.lower() in {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}:
            files.append({"name": f.name, "size": f.stat().st_size,
                          "url": f"/api/assets/characters/{char_id}/voice/{f.name}"})
    return {"files": files}


@router.get("/assets/{entity_type}/{entity_id}/{filename}")
def get_entity_asset(entity_type: str, entity_id: str, filename: str):
    from fastapi.responses import FileResponse
    _check_entity_type(entity_type)
    _check_id(entity_id)
    _check_filename(filename)
    base = _paths().assets_entity_dir(entity_type) / entity_id
    file_path = _safe_path(base, filename)
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
