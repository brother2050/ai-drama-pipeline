"""口型同步步骤 — 视频 + 音频 → 口型同步视频"""
from __future__ import annotations

import logging
from pathlib import Path

from infra.constants import STEP_LIPSYNC
from pipeline.tasks.helpers import _skip, _err, _done, _validate_output

logger = logging.getLogger(__name__)


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
        return _skip(shot_id, STEP_LIPSYNC, "视频不存在，请先执行 Step 3")
    if not audio_path.exists():
        return _skip(shot_id, STEP_LIPSYNC, "音频不存在，请先执行 Step 1")

    synced_path = out_dir / "synced.mp4"
    if not force and synced_path.exists():
        return _skip(shot_id, STEP_LIPSYNC, "口型同步视频已存在")

    synced_out = str(synced_path)
    from infra.globals import get_watchdog, get_concurrency_groups
    from infra.concurrency.executor import safe_run
    wd = get_watchdog()
    groups = get_concurrency_groups()

    def _do_lipsync():
        with groups.acquire(STEP_LIPSYNC):
            with wd.track(f"{shot_id}:lipsync", backend=STEP_LIPSYNC):
                lipsync_inst, _ = cont.get_with_fallback(STEP_LIPSYNC)
                lipsync_inst.sync(str(video_path), str(audio_path), synced_out)

    try:
        safe_run(_do_lipsync, retries=2, base_delay=1.0, task_id=f"{shot_id}:lipsync")
    except Exception as e:
        return _err(shot_id, STEP_LIPSYNC, f"口型同步失败: {e}")
    err = _validate_output(synced_out, STEP_LIPSYNC, min_size=10000)
    if err:
        return _err(shot_id, STEP_LIPSYNC, err)
    return _done(shot_id, STEP_LIPSYNC, synced_out)
