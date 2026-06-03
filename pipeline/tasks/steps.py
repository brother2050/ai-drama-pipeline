"""Celery 任务定义 — 单镜头步骤核心函数 + Celery step 任务"""
from __future__ import annotations

from dataclasses import dataclass
from infra.constants import STATUS_DONE, STATUS_ERROR
import hashlib
import logging
import os
import re
from pathlib import Path


@dataclass
class FirstFrameParams:
    """首帧生成参数 — 消除 first_frame_core 的 8 个参数"""
    shot_id: str
    shot: dict
    cfg: object
    cont: object
    out_dir: Path
    force: bool = False
    characters: dict | None = None
    scenes: dict | None = None

from celery.exceptions import SoftTimeLimitExceeded

from pipeline.celery_app import app
from pipeline.tasks.helpers import (
    _shot_dir,
    _db_record_step,
    _prepare,
    _skip, _err, _done,
    _validate_output,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  核心逻辑函数（可被 preview.py 等模块复用）
# ══════════════════════════════════════════════════════════

def tts_core(shot_id: str, shot: dict, cfg, cont, out_dir: Path, *,
             force: bool = False, characters: dict | None = None) -> dict:
    """TTS 核心逻辑 — 合成台词为音频

    Args:
        shot_id: 镜头 ID
        shot: 镜头数据
        cfg: Config 对象
        cont: DI 容器
        out_dir: 输出目录
        force: True 时覆盖已有文件，False 时跳过
        characters: 预加载的角色字典 {id: char_data}，避免重复读 YAML

    Returns:
        {"status": STATUS_DONE/"skipped"/"error", ...}
    """
    dialogue = shot.get("dialogue", "").strip()
    if not dialogue or set(dialogue) <= {".", "…"}:
        return _skip(shot_id, "tts", "无台词")

    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(out_dir / "audio.wav")

    # 已有文件且非强制模式 → 跳过
    if not force and Path(audio_path).exists():
        return _skip(shot_id, "tts", "音频已存在")

    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]

    # 优先用预加载的角色数据，避免每次创建 ShotManager 读全部 YAML
    if characters:
        char_data = characters.get(char_ids[0], {}) if char_ids else {}
    else:
        from engines.shot_manager import ShotManager
        paths = cfg.paths
        sm = ShotManager(str(paths.config_dir))
        char_data = sm.get_character(char_ids[0]) if char_ids else {}

    if char_ids and not char_data:
        logger.warning(f"[{shot_id}] 角色 {char_ids[0]} 不存在，使用默认声音")
    # TTS 统一读 bible.core_traits 作为声音描述
    core_traits = (char_data.get("bible") or {}).get("core_traits", "")
    voice_config = {"core_traits": core_traits} if core_traits else {}
    emotion = shot.get("emotion", "neutral")
    language = shot.get("language", "zh")

    try:
        tts_inst, tts_name = cont.get_with_fallback("tts")
        tts_inst.synthesize(dialogue, audio_path, voice_config=voice_config,
                            emotion=emotion, language=language)
    except Exception as e:
        return _err(shot_id, "tts", f"TTS 合成失败: {e}")
    err = _validate_output(audio_path, "tts", min_size=1000)
    if err:
        return _err(shot_id, "tts", err)
    return _done(shot_id, "tts", audio_path)


def _check_lora_availability(wf: dict, paths, cfg, comfyui):
    """检查工作流中的 LoRA 文件是否存在于 ComfyUI 服务器"""
    from engines.workflow import find_lora_nodes
    from infra.asset_tracker import AssetTracker
    from urllib.parse import urlparse

    tracker = AssetTracker(str(paths.root))
    image_server_url = comfyui.url
    lora_nodes = find_lora_nodes(wf)

    for node_id, lora_name in lora_nodes:
        if tracker.is_lora_tracked(image_server_url, lora_name):
            continue
        parsed = urlparse(image_server_url)
        is_local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        found = False
        if is_local:
            loras_dir_candidates = []
            comfyui_dir = cfg.get("comfyui", {}).get("models_dir", "")
            if comfyui_dir:
                loras_dir_candidates.append(Path(comfyui_dir) / "loras")
            loras_dir_candidates.append(Path.home() / "ComfyUI" / "models" / "loras")
            for loras_dir in loras_dir_candidates:
                if (loras_dir / lora_name).exists():
                    tracker.mark_lora_tracked(image_server_url, lora_name)
                    found = True
                    break
        if not found:
            logger.warning(f"LoRA '{lora_name}' 未确认存在于服务器 {image_server_url}")


def _upload_reference_images(wf: dict, shot: dict, wb, comfyui, paths) -> dict:
    """并行上传参考图到 ComfyUI 服务器，更新工作流节点引用"""
    from engines.workflow import find_character_load_image_nodes as _find_char_nodes
    from infra.asset_tracker import comfyui_asset_name
    from concurrent.futures import ThreadPoolExecutor, as_completed

    _char_node_set = set(_find_char_nodes(wf))
    upload_map = wb.build_upload_map(shot, wf)
    if not upload_map:
        return wf

    def _upload_one(node_id: str, file_path: str) -> tuple[str, str, str | None]:
        if not Path(file_path).exists():
            return node_id, "", f"文件不存在: {file_path}"
        try:
            if node_id in _char_node_set and "/assets/characters/" in file_path:
                parts = Path(file_path).parts
                char_idx = parts.index("characters") + 1
                cid = parts[char_idx] if char_idx < len(parts) else "unknown"
                remote_name = comfyui_asset_name(str(paths.root), cid, Path(file_path).name)
            else:
                remote_name = Path(file_path).name
            comfyui.upload_image(file_path, filename=remote_name)
            return node_id, remote_name, None
        except Exception as e:
            return node_id, "", f"上传失败: {e}"

    with ThreadPoolExecutor(max_workers=min(len(upload_map), 4)) as pool:
        futures = {pool.submit(_upload_one, nid, fp): nid for nid, fp in upload_map.items()}
        for future in as_completed(futures):
            node_id, remote_name, err = future.result()
            if err:
                logger.warning(f"参考图上传失败 [{node_id}]: {err}")
            elif node_id in wf and remote_name:
                cls = wf[node_id].get("class_type", "")
                if cls in ("LoadImage", "LoadImageFromPath", "ImageLoad"):
                    wf[node_id]["inputs"]["image"] = remote_name
    return wf


def _resolve_shot_context(shot: dict, cfg, characters: dict | None, scenes: dict | None):
    """解析镜头上下文：角色描述、场景描述、多人提示、服装"""
    from engines.prompt import get_view_appearance
    from engines.multi_char import MultiCharacterHandler

    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]
    characters, scenes = _ensure_char_scene_data(cfg, characters, scenes)

    # 角色描述
    shot_type = shot.get("shot_type", "")
    char_descs = []
    for cid in char_ids:
        char = characters.get(cid, {})
        if char:
            desc = get_view_appearance(char, shot_type)
            if not desc:
                from infra.constants import ERR_NOT_PREPARED
                return None, None, None, None, f"角色 {cid} 未生成 AI 绘图 prompt，{ERR_NOT_PREPARED}"
            char_descs.append(desc)

    # 场景描述
    scene = scenes.get(shot.get("scene_id", ""), {})
    scene_desc = ""
    if scene:
        scene_desc = scene.get("description_en", "")
        if not scene_desc and scene.get("description"):
            from infra.constants import ERR_NOT_PREPARED_CN
            return None, None, None, None, f"场景 '{shot.get('scene', '')}' 尚未生成英文描述，{ERR_NOT_PREPARED_CN}"

    # 多人提示
    multi_char_prompt = ""
    if len(char_ids) > 1:
        multi_char_prompt = MultiCharacterHandler().generate_multi_char_prompt(
            [c for c in (characters.get(cid, {}) for cid in char_ids) if c])

    shot = _auto_match_outfit(shot, char_ids, characters)
    shot = _resolve_scene_ref(shot, scene, cfg)
    return shot, char_descs, scene_desc, multi_char_prompt, None


def _ensure_char_scene_data(cfg, characters, scenes):
    """确保角色/场景数据已加载"""
    if characters is not None and scenes is not None:
        return characters, scenes
    from engines.shot_manager import ShotManager
    sm = ShotManager(str(cfg.paths.config_dir))
    return characters if characters is not None else sm.characters, \
           scenes if scenes is not None else sm.scenes


def _auto_match_outfit(shot, char_ids, characters):
    """服装自动匹配（outfit 为空时回退到 default 或第一个）"""
    if shot.get("outfit", "").strip() or not char_ids:
        return shot
    primary_char = characters.get(char_ids[0], {})
    if not primary_char:
        return shot
    char_outfits = primary_char.get("outfits", {})
    if not isinstance(char_outfits, dict) or not char_outfits:
        return shot
    outfit = "default" if "default" in char_outfits else next(iter(char_outfits))
    logger.info(f"outfit 为空，自动回退到 '{outfit}'")
    shot = dict(shot)
    shot["outfit"] = outfit
    return shot


def _resolve_scene_ref(shot, scene, cfg):
    """解析场景参考图路径"""
    if not scene:
        return shot
    scene_refs = scene.get("reference_images", [])
    if not scene_refs or shot.get("scene_ref"):
        return shot
    ref_url = scene_refs[0]
    if ref_url.startswith("/api/assets/"):
        local_path = cfg.paths.assets_dir / ref_url.removeprefix("/api/assets/")
        if local_path.exists():
            shot = dict(shot)
            shot["scene_ref"] = str(local_path)
    return shot


def first_frame_core(p: FirstFrameParams) -> dict:
    """首帧生成核心逻辑 — ComfyUI 工作流构建 + 执行"""
    p.out_dir.mkdir(parents=True, exist_ok=True)
    frame_path = p.out_dir / "frame.png"
    if not p.force and frame_path.exists():
        return _skip(p.shot_id, "first_frame", "首帧已存在")

    from engines.workflow_builder import WorkflowBuilder, WorkflowBuilderConfig

    shot, char_descs, scene_desc, multi_char_prompt, err = _resolve_shot_context(
        p.shot, p.cfg, p.characters, p.scenes)
    if err:
        return _err(p.shot_id, "first_frame", err)

    paths = p.cfg.paths
    wb = WorkflowBuilder(WorkflowBuilderConfig(
        config=p.cfg.data, models=p.cfg.get("models", {}), project_dir=str(paths.root),
        comfyui=p.cont.get("image"), container=p.cont, force=p.force))
    wb.load_workflows()
    prompt, wf = wb.build_first_frame(
        shot, character_desc=", ".join(char_descs),
        scene_desc=scene_desc, multi_char_prompt=multi_char_prompt)
    if not wf:
        return _err(p.shot_id, "first_frame", "首帧工作流为空（缺少模板）")

    comfyui = p.cont.get("image")
    _check_lora_availability(wf, paths, p.cfg, comfyui)
    wf = _upload_reference_images(wf, shot, wb, comfyui, paths)

    try:
        files = comfyui.generate(wf, str(p.out_dir))
    except Exception as e:
        return _err(p.shot_id, "first_frame", f"ComfyUI 首帧生成失败: {e}")
    if not files:
        return _err(p.shot_id, "first_frame", "ComfyUI 未返回任何图片")

    frame_path = str(p.out_dir / "frame.png")
    os.replace(files[0], frame_path)
    err = _validate_output(frame_path, "first_frame", min_size=500)
    if err:
        return _err(p.shot_id, "first_frame", err)
    return _done(p.shot_id, "first_frame", frame_path, prompt=prompt.get("positive", ""))


def _safe_server_filename(project_name: str, ep_tag: str, shot_id: str) -> str:
    """生成 ComfyUI 服务端安全文件名（纯 ASCII）"""
    import hashlib
    if re.search(r'[^\x00-\x7f]', project_name):
        ascii_name = "proj_" + hashlib.md5(project_name.encode("utf-8")).hexdigest()[:8]
    else:
        ascii_name = project_name
    return f"{ascii_name}{ep_tag}_{shot_id}_frame.png"


def _upload_first_frame_if_needed(video_wf: dict, frame_path: Path, server_filename: str,
                                  paths, video_backend) -> dict:
    """检查并上传首帧到视频 ComfyUI 服务器，更新工作流节点引用"""
    from engines.workflow import find_load_image_nodes
    load_nodes = find_load_image_nodes(video_wf)
    if not load_nodes:
        return video_wf

    video_comfyui = video_backend._get_comfyui() if hasattr(video_backend, "_get_comfyui") else video_backend
    video_server_url = getattr(video_comfyui, "url", "").rstrip("/")

    from infra.asset_tracker import AssetTracker
    tracker = AssetTracker(str(paths.root))
    already_tracked = tracker.is_image_tracked(video_server_url, server_filename)

    need_upload = True
    if already_tracked:
        try:
            if video_comfyui.check_image_exists(server_filename, asset_type="input"):
                logger.debug(f"首帧图 {server_filename} 已在视频服务器，跳过上传")
                need_upload = False
            else:
                tracker.untrack_image(video_server_url, server_filename)
        except Exception as e:
            logger.debug(f"检查首帧图存在性失败: {e}，回退上传")

    if need_upload:
        try:
            video_comfyui.upload_image(str(frame_path), filename=server_filename)
            tracker.mark_image_tracked(video_server_url, server_filename)
        except Exception as e:
            logger.warning(f"首帧图上传失败: {e}")

    if load_nodes[0] in video_wf:
        video_wf[load_nodes[0]]["inputs"]["image"] = server_filename
    return video_wf


def video_core(shot_id: str, cfg, cont, out_dir: Path, *, shot: dict | None = None, force: bool = False) -> dict:
    """视频生成核心逻辑 — 从首帧生成视频"""
    frame_path = out_dir / "frame.png"
    if not frame_path.exists():
        return _skip(shot_id, "video", "首帧不存在，请先执行 Step 2")

    video_path = out_dir / "video.mp4"
    if not force and video_path.exists():
        return _skip(shot_id, "video", "视频已存在")

    from engines.workflow_builder import WorkflowBuilder, WorkflowBuilderConfig
    paths = cfg.paths
    wb = WorkflowBuilder(WorkflowBuilderConfig(
        config=cfg.data, models=cfg.get("models", {}), project_dir=str(paths.root),
        comfyui=cont.get("image"), container=cont))
    wb.load_workflows()
    video_wf = wb.build_video(str(frame_path), shot=shot)
    if not video_wf:
        return _err(shot_id, "video", "视频工作流为空（缺少模板）")

    # 上传首帧到视频服务器
    project_name = paths.root.name or "project"
    ep_tag = ""
    parent = out_dir.parent.name
    if parent.startswith("ep") and parent[2:].isdigit():
        ep_tag = f"_{parent}"
    server_filename = _safe_server_filename(project_name, ep_tag, shot_id)
    video_wf = _upload_first_frame_if_needed(video_wf, frame_path, server_filename, paths, cont.get("video"))

    try:
        files = cont.get("video").generate(video_wf, str(out_dir))
    except Exception as e:
        return _err(shot_id, "video", f"视频生成失败: {e}")

    if not files:
        return _err(shot_id, "video", "ComfyUI 未返回任何视频")
    video_path = str(out_dir / "video.mp4")
    os.replace(files[0], video_path)
    err = _validate_output(video_path, "video", min_size=10000)
    if err:
        return _err(shot_id, "video", err)
    return _done(shot_id, "video", video_path)


def lipsync_core(shot_id: str, cont, out_dir: Path, *, force: bool = False) -> dict:
    """口型同步核心逻辑 — 视频 + 音频 → 口型同步视频

    Args:
        shot_id: 镜头 ID
        cont: DI 容器
        out_dir: 输出目录
        force: True 时覆盖已有文件，False 时跳过

    Returns:
        {"status": STATUS_DONE/"skipped"/"error", ...}
    """
    video_path, audio_path = out_dir / "video.mp4", out_dir / "audio.wav"
    if not video_path.exists():
        return _skip(shot_id, "lipsync", "视频不存在，请先执行 Step 3")
    if not audio_path.exists():
        return _skip(shot_id, "lipsync", "音频不存在，请先执行 Step 1")

    # 已有文件且非强制模式 → 跳过
    synced_path = out_dir / "synced.mp4"
    if not force and synced_path.exists():
        return _skip(shot_id, "lipsync", "口型同步视频已存在")

    synced_path = str(out_dir / "synced.mp4")
    try:
        lipsync_inst, lipsync_name = cont.get_with_fallback("lipsync")
        lipsync_inst.sync(str(video_path), str(audio_path), synced_path)
    except Exception as e:
        return _err(shot_id, "lipsync", f"口型同步失败: {e}")
    err = _validate_output(synced_path, "lipsync", min_size=10000)
    if err:
        return _err(shot_id, "lipsync", err)
    return _done(shot_id, "lipsync", synced_path)


# ── Celery 任务包装（_prepare 防重复 + 核心逻辑）──

def _run_tts(config_path: str, episode: int, shot_id: str, *,
             force: bool = False,
             cfg=None, cont=None, shot: dict | None = None,
             characters: dict | None = None, **kw) -> dict:
    from pipeline.tasks.helpers import PrepareParams
    cfg, cont, shot, err = _prepare(PrepareParams(
        config_path=config_path, episode=episode, shot_id=shot_id,
        step="tts", tool="tts", force=force, cfg=cfg, cont=cont, shot=shot))
    if err:
        return err
    return tts_core(shot_id, shot, cfg, cont, _shot_dir(config_path, episode, shot_id),
                    force=force, characters=characters)


def _run_first_frame(config_path: str, episode: int, shot_id: str, *,
                     force: bool = False,
                     cfg=None, cont=None, shot: dict | None = None,
                     characters: dict | None = None,
                     scenes: dict | None = None, **kw) -> dict:
    from pipeline.tasks.helpers import PrepareParams
    cfg, cont, shot, err = _prepare(PrepareParams(
        config_path=config_path, episode=episode, shot_id=shot_id,
        step="first_frame", tool="comfyui", force=force, cfg=cfg, cont=cont, shot=shot))
    if err:
        return err
    return first_frame_core(FirstFrameParams(
        shot_id=shot_id, shot=shot, cfg=cfg, cont=cont,
        out_dir=_shot_dir(config_path, episode, shot_id),
        force=force, characters=characters, scenes=scenes))


def _run_video(config_path: str, episode: int, shot_id: str, *,
               force: bool = False,
               cfg=None, cont=None, shot: dict | None = None, **kw) -> dict:
    from pipeline.tasks.helpers import PrepareParams
    cfg, cont, shot, err = _prepare(PrepareParams(
        config_path=config_path, episode=episode, shot_id=shot_id,
        step="video", tool="comfyui", need_shot=True, force=force, cfg=cfg, cont=cont, shot=shot))
    if err:
        return err
    return video_core(shot_id, cfg, cont, _shot_dir(config_path, episode, shot_id),
                      shot=shot, force=force)


def _run_lipsync(config_path: str, episode: int, shot_id: str, *,
                 force: bool = False,
                 cfg=None, cont=None, **kw) -> dict:
    from pipeline.tasks.helpers import PrepareParams
    cfg, cont, _, err = _prepare(PrepareParams(
        config_path=config_path, episode=episode, shot_id=shot_id,
        step="lipsync", tool="lipsync", need_shot=False, force=force, cfg=cfg, cont=cont))
    if err:
        return err
    return lipsync_core(shot_id, cont, _shot_dir(config_path, episode, shot_id), force=force)


# ══════════════════════════════════════════════════════════
#  Celery 任务包装
# ══════════════════════════════════════════════════════════

def _step_task(self, step: str, fn, config_path: str, episode: int, shot_id: str, *, force: bool = False):
    """通用 Celery 步骤任务包装"""
    self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 10, "message": f"[{shot_id}] {step} 开始..."})
    try:
        result = fn(config_path, episode, shot_id, force=force)
    except SoftTimeLimitExceeded:
        logger.warning(f"[{shot_id}] {step} 超时（soft_time_limit）")
        _db_record_step(episode, shot_id, step, {"status": STATUS_ERROR, "reason": "执行超时"})
        return {"shot_id": shot_id, "step": step, "status": STATUS_ERROR, "reason": "执行超时"}
    except Exception as e:
        logger.error(f"[{shot_id}] {step} 异常: {e}", exc_info=True)
        _db_record_step(episode, shot_id, step, {"status": STATUS_ERROR, "reason": str(e)})
        return {"shot_id": shot_id, "step": step, "status": STATUS_ERROR, "reason": str(e)}
    # 立即同步 DB 状态（D-01：先写 DB 再返回，防止崩溃后状态不一致）
    _db_record_step(episode, shot_id, step, result)
    if result.get("status") == STATUS_DONE:
        self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 100, "message": f"[{shot_id}] {step} 完成"})
    elif result.get("status") == STATUS_ERROR:
        self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 100, "message": f"[{shot_id}] {step} 失败: {result.get('reason', '')}"})
    return result


@app.task(bind=True, name="pipeline_step_tts", soft_time_limit=120)
def step_tts(self, config_path, episode, shot_id, force=False): return _step_task(self, "tts", _run_tts, config_path, episode, shot_id, force=force)

@app.task(bind=True, name="pipeline_step_first_frame", soft_time_limit=300)
def step_first_frame(self, config_path, episode, shot_id, force=False): return _step_task(self, "first_frame", _run_first_frame, config_path, episode, shot_id, force=force)

@app.task(bind=True, name="pipeline_step_video", soft_time_limit=600)
def step_video(self, config_path, episode, shot_id, force=False): return _step_task(self, "video", _run_video, config_path, episode, shot_id, force=force)

@app.task(bind=True, name="pipeline_step_lipsync", soft_time_limit=300)
def step_lipsync(self, config_path, episode, shot_id, force=False): return _step_task(self, "lipsync", _run_lipsync, config_path, episode, shot_id, force=force)
