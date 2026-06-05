"""视频生成步骤 — 首帧 → video.mp4"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from pipeline.tasks.helpers import _skip, _err, _done, _validate_output

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

    from infra.globals import get_watchdog, get_concurrency_groups
    from infra.safe_executor import safe_run
    wd = get_watchdog()
    groups = get_concurrency_groups()

    def _do_generate():
        with groups.acquire("comfyui"):
            with wd.track(f"{shot_id}:video", backend="comfyui"):
                return cont.get("video").generate(video_wf, str(out_dir))

    try:
        files = safe_run(_do_generate, retries=2, base_delay=2.0, task_id=f"{shot_id}:video")
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
