"""API 路由 — 分镜表 / 集数 / 镜头资源 / 管线 / LLM 生成"""
from __future__ import annotations

from infra.constants import STATUS_DONE
import logging
import os
import shutil

from fastapi import APIRouter, HTTPException

from web.routers.deps import (
    _cfg_path, _paths, _proj,
    _check_id, _check_filename, _check_episode,
    _safe_path, _submit_task, raise_not_found,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_MEDIA_TYPES = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".mp4": "video/mp4", ".webm": "video/webm",
}

from web.schemas import (  # noqa: E402
    PipelineRequest, PrepareRequest,
    StoryboardGenRequest, EntityGenRequest, CharacterGenRequest, SceneGenRequest,
    ChatEditRequest,
    StoryboardSaveRequest, StoryboardBatchDeleteRequest,
)


def _get_pool():
    """获取 DB 连接池（统一入口，避免各处重复 import）"""
    from infra.database.pool import get_pool
    return get_pool()


# ══════════════════════════════════════════════════════════
# 集数
# ══════════════════════════════════════════════════════════

@router.get("/episodes")
def get_episodes() -> dict:
    from engines.content.storyboard import get_episode_list
    try:
        eps = get_episode_list()
    except Exception:
        return {"episodes": [], "current": 1}
    return {"episodes": eps, "current": min(eps) if eps else 1}


@router.get("/episodes/summary")
def get_episodes_summary() -> dict:
    from infra.database.storyboard_db import get_episodes_summary as db_summary
    try:
        rows = db_summary(_get_pool())
    except Exception:
        return {"episodes": []}

    result = []
    # 从 DB 查询每集已完成的镜头（替代文件系统扫描）
    done_by_ep: dict[int, set[str]] = {}
    try:
        from infra.database.generation import get_episode_statuses
        for row in rows:
            ep = row["episode"]
            statuses = get_episode_statuses(_get_pool(), ep)
            done_by_ep[ep] = {
                s["shot_id"] for s in statuses
                if s.get("stage") in ("first_frame", "video") and s.get("status") == "done"
            }
    except Exception as e:
        logger.warning(f"查询生成状态失败，回退到文件扫描: {e}")

    for row in rows:
        ep = row["episode"]
        shot_count = row["shots"]
        total_dur = int(row["duration"] or 0)
        done_sids = done_by_ep.get(ep)
        if done_sids is None:
            # DB 查询失败时回退到文件系统扫描
            out_base = _paths().episode_dir(ep)
            done_sids = set()
            if out_base.exists():
                try:
                    for entry in os.scandir(out_base):
                        if entry.is_dir() and entry.name.startswith("s"):
                            sid = entry.name[1:]
                            has_frame = os.path.isfile(os.path.join(entry.path, "frame.png"))
                            has_video = os.path.isfile(os.path.join(entry.path, "video.mp4"))
                            if has_frame or has_video:
                                done_sids.add(sid)
                except OSError as e:
                    logger.warning(f"扫描输出目录失败: {e}")
        done_count = len(done_sids)
        status = STATUS_DONE if done_count >= shot_count and shot_count > 0 else "progress" if done_count > 0 else "none"
        result.append({
            "episode": ep, "shots": shot_count, "duration": total_dur,
            "done": done_count, "status": status,
        })
    return {"episodes": result}


@router.delete("/episodes/{episode}")
def delete_episode(episode: int) -> dict:
    _check_episode(episode)
    p = _paths()
    ep_dir = p.episode_dir(episode)
    if not ep_dir.exists():
        raise_not_found(f"第{episode}集")
    # DB 先删（失败则中止，避免文件删了 DB 残留孤儿记录）
    removed_shots = 0
    try:
        from infra.database.storyboard_db import delete_episode as db_delete_ep
        pool = _get_pool()
        removed_shots = db_delete_ep(pool, episode)
    except Exception as e:
        logger.error(f"DB 删除失败，中止文件清理: {e}")
        raise HTTPException(500, f"数据库删除失败: {e}")
    shutil.rmtree(ep_dir, ignore_errors=True)
    return {"status": "ok", "episode": episode, "removed_shots": removed_shots}


@router.post("/episodes/{episode}/clear")
def clear_episode_outputs(episode: int) -> dict:
    _check_episode(episode)
    p = _paths()
    ep_dir = p.episode_dir(episode)
    cleared = 0
    if ep_dir.exists():
        for root_dir, dirs, files in os.walk(ep_dir):
            cleared += len(files)
        shutil.rmtree(ep_dir, ignore_errors=True)
    try:
        from infra.database.generation import clear_episode
        clear_episode(_get_pool(), episode)
    except Exception as e:
        logger.warning(f"数据库清理跳过: {e}")
    return {"status": "ok", "episode": episode, "cleared_files": cleared}


# ══════════════════════════════════════════════════════════
# 分镜表
# ══════════════════════════════════════════════════════════

@router.get("/storyboard/{episode}")
def get_storyboard(episode: int) -> dict:
    _check_episode(episode)
    from engines.content.storyboard import load_storyboard
    try:
        shots = load_storyboard(episode=episode)
    except Exception as e:
        logger.warning(f"加载分镜失败（DB 不可用？）: {e}")
        return {"episode": episode, "shots": []}
    return {"episode": episode, "shots": shots}


@router.post("/storyboard/{episode}")
def save_storyboard(episode: int, req: StoryboardSaveRequest) -> dict:
    _check_episode(episode)
    from engines.utils.shot import postprocess_shots
    shots = [s.model_dump() for s in req.shots]
    shots = postprocess_shots(shots, episode, strict=True)
    from engines.content.storyboard import save_storyboard
    try:
        save_storyboard(shots, episode)
    except Exception as e:
        logger.error(f"保存分镜失败: {e}")
        raise HTTPException(500, f"保存分镜失败（DB 不可用？）: {e}")

    # 一致性校验（非阻断，返回警告）
    warnings = []
    try:
        from engines.consistency.checker import check_consistency
        from infra.config import load_project_entities
        chars, scenes = load_project_entities(_paths())
        errors = check_consistency(shots, list(chars.values()), list(scenes.values()))
        if errors:
            warnings = errors[:10]  # 最多返回 10 条
    except Exception as e:
        logger.warning(f"一致性检查跳过: {e}")

    result = {"status": "ok", "count": len(shots)}
    if warnings:
        result["warnings"] = warnings
    return result


@router.post("/storyboard/{episode}/batch-delete")
def batch_delete_storyboard_shots(episode: int, req: StoryboardBatchDeleteRequest) -> dict:
    _check_episode(episode)
    if not req.shot_ids:
        raise HTTPException(400, "shot_ids 不能为空")
    from infra.database.storyboard_db import batch_delete_shots, get_episode_shots
    try:
        # 验证 shot_id 属于当前 episode，防止误删其他集的镜头
        existing = {s["shot_id"] for s in get_episode_shots(_get_pool(), episode)}
        invalid = [sid for sid in req.shot_ids if sid not in existing]
        if invalid:
            raise HTTPException(400, f"以下 shot_id 不属于第{episode}集: {invalid[:5]}")
        deleted = batch_delete_shots(_get_pool(), episode, req.shot_ids)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"删除失败: {e}")
    # 清理已删除镜头的输出文件（防止孤儿文件）
    p = _paths()
    cleaned = 0
    for sid in req.shot_ids:
        shot_dir = p.shot_dir(episode, sid)
        if shot_dir.exists():
            try:
                shutil.rmtree(shot_dir)
                cleaned += 1
            except OSError as e:
                logger.warning(f"清理镜头输出目录失败 {shot_dir}: {e}")
    return {"status": "ok", "deleted": deleted, "cleaned_files": cleaned}


# ══════════════════════════════════════════════════════════
# 管线 / LLM 生成 / 准备
# ══════════════════════════════════════════════════════════

@router.post("/pipeline/run")
def run_pipeline(req: PipelineRequest) -> dict:
    from pipeline.tasks import preview_task, produce_task, post_task, ai_prepare_task, ai_entities_task, run_all_task
    cfg = _cfg_path()
    dispatch = {
        "preview": lambda: _submit_task(preview_task, cfg, req.episode, req.level, req.force),
        "prepare": lambda: _submit_task(ai_prepare_task, cfg, req.episode, force=req.force, translate=True),
        "entities": lambda: _submit_task(ai_entities_task, cfg, req.episode),
        "produce": lambda: _submit_task(produce_task, cfg, req.episode, force=req.force),
        "post":    lambda: _submit_task(post_task, cfg, req.episode, req.vertical),
        "run_all": lambda: _submit_task(run_all_task, cfg, req.episode, req.vertical, req.force),
    }
    handler = dispatch.get(req.command)
    if not handler:
        raise HTTPException(400, f"未知命令: {req.command}")
    return handler()


@router.get("/pipeline/status/{episode}")
def pipeline_status(episode: int) -> dict:
    from engines.content.episode import get_episode_status
    return get_episode_status(str(_proj()), episode)


@router.post("/prepare")
def run_prepare(req: PrepareRequest) -> dict:
    from pipeline.tasks import ai_prepare_task
    cfg = _cfg_path()
    return _submit_task(ai_prepare_task, cfg, req.episode,
                        force=req.force, translate=req.translate)


@router.post("/llm/storyboard")
def llm_generate_storyboard(req: StoryboardGenRequest) -> dict:
    cfg = _cfg_path()
    from pipeline.tasks import ai_storyboard_task
    return _submit_task(ai_storyboard_task, cfg, req.episode, req.outline, req.duration, req.append)


@router.post("/llm/entities")
def llm_generate_entities(req: EntityGenRequest) -> dict:
    """AI 批量生成分镜引用的角色和场景（只生成缺失的）"""
    cfg = _cfg_path()
    from pipeline.tasks import ai_entities_task
    return _submit_task(ai_entities_task, cfg, req.episode)


@router.post("/llm/characters")
def llm_generate_characters(req: CharacterGenRequest) -> dict:
    cfg = _cfg_path()
    from pipeline.tasks import ai_characters_task
    return _submit_task(ai_characters_task, cfg, req.descriptions)


@router.post("/llm/scenes")
def llm_generate_scenes(req: SceneGenRequest) -> dict:
    cfg = _cfg_path()
    from pipeline.tasks import ai_scenes_task
    return _submit_task(ai_scenes_task, cfg, req.descriptions)


@router.post("/llm/chat-edit")
def llm_chat_edit(req: ChatEditRequest) -> dict:
    _check_episode(req.episode)
    cfg = _cfg_path()
    from pipeline.tasks import ai_chat_edit_task
    return _submit_task(ai_chat_edit_task, cfg, req.episode, req.message, req.shots)


# ══════════════════════════════════════════════════════════
# 镜头资源 / 文件预览
# ══════════════════════════════════════════════════════════

@router.get("/shots/{episode}/{shot_id}/resources")
def get_shot_resources(episode: int, shot_id: str) -> dict:
    _check_episode(episode)
    _check_id(shot_id, "shot_id")
    out_dir = _paths().shot_dir(episode, shot_id)
    if not out_dir.exists():
        return {"shot_id": shot_id, "resources": {}}
    resources = {}
    for fname, key in [("audio.wav", "audio"), ("frame.png", "frame"),
                        ("video.mp4", "video"), ("synced.mp4", "synced")]:
        if (out_dir / fname).exists():
            resources[key] = fname
    return {"shot_id": shot_id, "resources": resources}


@router.get("/files/{episode}/{shot_id}/{filename}")
def get_shot_file(episode: int, shot_id: str, filename: str):
    from fastapi.responses import FileResponse
    _check_episode(episode)
    _check_filename(filename)
    p = _paths()
    if shot_id == "final":
        file_path = _safe_path(p.episode_dir(episode), filename)
    else:
        _check_id(shot_id, "shot_id")
        file_path = _safe_path(p.shot_dir(episode, shot_id), filename)
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {filename}")
    ext = file_path.suffix.lower()
    return FileResponse(str(file_path), media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"))


@router.get("/project-file/{path:path}")
def get_project_file(path: str):
    from fastapi.responses import FileResponse
    proj = _proj()
    file_path = _safe_path(proj, path)
    # 安全白名单：只允许访问 output/ 和 assets/ 目录（防止配置文件泄露）
    rel = file_path.relative_to(proj.resolve())
    allowed_prefixes = ("output", "assets")
    if rel.parts[0] not in allowed_prefixes:
        raise HTTPException(403, "禁止访问此路径")
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {path}")
    ext = file_path.suffix.lower()
    return FileResponse(str(file_path), media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"))


@router.get("/shots/{episode}/final/resources")
def get_final_resources(episode: int) -> dict:
    _check_episode(episode)
    p = _paths()
    out_dir = p.episode_dir(episode)
    final_mp4 = p.episode_final(episode)
    if not final_mp4.exists():
        candidates = list(out_dir.glob("*final*.mp4"))
        if candidates:
            final_mp4 = candidates[0]
        else:
            return {"resources": {}}
    return {"resources": {"final": final_mp4.name}}
