"""视频生成步骤 — 首帧 → video.mp4"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from infra.constants import STEP_VIDEO
from pipeline.tasks.helpers import _skip, _err

logger = logging.getLogger(__name__)


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

    video_comfyui = video_backend
    video_server_url = getattr(video_comfyui, "url", "").rstrip("/")

    from infra.storage.asset_tracker import AssetTracker
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
            raise RuntimeError(f"首帧图上传到视频服务器失败: {e}") from e

    # 更新所有 LoadImage 节点引用（多节点时全部指向首帧）
    for nid in load_nodes:
        if nid in video_wf:
            video_wf[nid]["inputs"]["image"] = server_filename
    return video_wf


def video_core(shot_id: str, cfg, cont, out_dir: Path, *,
               shot: dict | None = None, force: bool = False,
               characters: dict | None = None, scenes: dict | None = None,
               char_name_to_id: dict | None = None) -> dict:
    """视频生成核心逻辑 — 从首帧生成视频"""
    frame_path = out_dir / "frame.png"
    if not frame_path.exists():
        return _skip(shot_id, STEP_VIDEO, "首帧不存在，请先执行 Step 2")

    video_path = out_dir / "video.mp4"
    if not force and video_path.exists():
        return _skip(shot_id, STEP_VIDEO, "视频已存在")

    from engines.workflow.builder import WorkflowBuilder, WorkflowBuilderConfig
    paths = cfg.paths

    # 加载角色/场景数据（视频 prompt 需要外貌和场景描述保持与首帧一致）
    if characters is None or scenes is None:
        from infra.config import load_project_entities
        characters, scenes = load_project_entities(paths)

    # 确保 char_name_to_id 存在（Celery 独立步骤分派路径不会传入）
    if not char_name_to_id:
        from infra.config import load_char_name_to_id
        char_name_to_id = load_char_name_to_id(paths)

    video_comfyui = cont.get("video")
    wb = WorkflowBuilder(WorkflowBuilderConfig(
        config=cfg.data, models=cfg.get("models", {}), project_dir=str(paths.root),
        comfyui=video_comfyui, container=cont,
        char_name_to_id=char_name_to_id or {}))
    wb.load_workflows()
    video_wf = wb.build_video(str(frame_path), shot=shot,
                              characters=characters, scenes=scenes)
    if not video_wf:
        return _err(shot_id, STEP_VIDEO, "视频工作流为空（缺少模板）")

    # 上传首帧到视频服务器
    project_name = paths.root.name or "project"
    ep_tag = ""
    parent = out_dir.parent.name
    if parent.startswith("ep") and parent[2:].isdigit():
        ep_tag = f"_{parent}"
    server_filename = _safe_server_filename(project_name, ep_tag, shot_id)
    video_wf = _upload_first_frame_if_needed(video_wf, frame_path, server_filename, paths, cont.get("video"))

    from pipeline.tasks.helpers import comfyui_generate
    return comfyui_generate(shot_id, STEP_VIDEO, cont.get("video"), video_wf, out_dir, "video.mp4", min_size=10000)
