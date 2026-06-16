"""API 路由 — 声线库（1000 种声线选择/试听/分配）"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from web.routers.deps import _check_id, _paths

logger = logging.getLogger(__name__)
router = APIRouter()


def _voices_dir() -> Path:
    """声线库目录（统一入口 get_voices_dir）"""
    from infra.config import get_voices_dir
    d = get_voices_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _voices_json() -> Path:
    return _voices_dir() / "voices.json"


def _load_voices_index() -> dict:
    """加载 voices.json 索引"""
    p = _voices_json()
    if not p.exists():
        return {"version": 1, "voices": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"voices.json 解析失败: {e}")
        return {"version": 1, "voices": []}


@router.get("/voices")
def list_voices(q: str = "", gender: str = "", page: int = 1, page_size: int = 50) -> dict:
    """声线库列表（支持搜索、性别筛选、分页）"""
    data = _load_voices_index()
    voices = data.get("voices", [])

    # 搜索过滤
    if q:
        q_lower = q.lower()
        voices = [v for v in voices if
                  q_lower in v.get("scene", "").lower() or
                  q_lower in v.get("style", "").lower() or
                  q_lower in " ".join(v.get("keywords", [])).lower()]

    # 性别过滤
    if gender:
        voices = [v for v in voices if v.get("gender") == gender]

    total = len(voices)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "voices": voices[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/voices/{voice_id}/audio")
def get_voice_audio(voice_id: str):
    """试听声线音频"""
    data = _load_voices_index()
    voice = next((v for v in data.get("voices", []) if v.get("id") == voice_id), None)
    if not voice:
        raise HTTPException(404, f"声线 {voice_id} 不存在")

    filename = voice.get("filename", "")
    if not filename:
        raise HTTPException(404, f"声线 {voice_id} 无音频文件")

    from web.routers.deps import _safe_path
    audio_path = _safe_path(_voices_dir(), filename)
    if not audio_path.exists():
        raise HTTPException(404, f"音频文件不存在: {filename}")

    return FileResponse(str(audio_path), media_type="audio/wav")


@router.post("/voices/{voice_id}/assign/{char_id}")
def assign_voice_to_char(voice_id: str, char_id: str) -> dict:
    """将声线分配给角色（复制音频到角色资产 + 更新 YAML）"""
    _check_id(char_id)

    # 查找声线
    data = _load_voices_index()
    voice = next((v for v in data.get("voices", []) if v.get("id") == voice_id), None)
    if not voice:
        raise HTTPException(404, f"声线 {voice_id} 不存在")

    filename = voice.get("filename", "")
    src = _voices_dir() / filename
    if not src.exists():
        raise HTTPException(404, f"音频文件不存在: {filename}")

    # 复制到角色资产目录
    p = _paths()
    voice_dir = p.character_asset_dir(char_id) / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    dest = voice_dir / filename
    shutil.copy2(str(src), str(dest))

    # 更新角色 YAML（reference_audio 指向新文件，写入当前 TTS 后端专属段）
    yaml_path = p.character_yaml(char_id)
    if not yaml_path.exists():
        raise HTTPException(404, f"角色 {char_id} 不存在")

    from infra.config import load_yaml_full, save_yaml, load_config, SYSTEM_CONFIG_PATH
    from infra.config import cfg_get
    sys_cfg = load_config(SYSTEM_CONFIG_PATH)
    tts_backend = cfg_get(sys_cfg, "models.tts_backend", "mimo-voicedesign")
    backend_key = tts_backend.replace("-", "_")

    entity_data = load_yaml_full(yaml_path)
    entity = entity_data.get("character", {})
    voice_cfg = entity.get("voice") or {}
    backend_cfg = voice_cfg.get(backend_key) or {}
    backend_cfg["reference_audio"] = str(dest)
    voice_cfg[backend_key] = backend_cfg
    entity["voice"] = voice_cfg
    entity_data["character"] = entity
    save_yaml(yaml_path, entity_data)

    return {"status": "ok", "voice_id": voice_id, "char_id": char_id,
            "path": str(dest), "style": voice.get("style", "")}
