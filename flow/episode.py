"""集管理 — 文件系统 + 数据库双查询"""
from __future__ import annotations
from infra.constants import STATUS_DONE
import logging

logger = logging.getLogger(__name__)

__all__ = ["get_episode_status"]


def get_episode_status(project_dir: str, episode: int) -> dict:
    """获取集状态（文件系统 + 数据库）"""
    from infra.config import ProjectPaths
    paths = ProjectPaths(project_dir)
    out_dir = paths.episode_dir(episode)
    if not out_dir.exists():
        return {"episode": episode, "status": "not_started", "shots": 0}

    shot_dirs = sorted(out_dir.glob("s*"))
    shots_status = []
    for sd in shot_dirs:
        has_frame = (sd / "frame.png").exists()
        has_video = (sd / "video.mp4").exists()
        has_audio = (sd / "audio.wav").exists()
        has_synced = (sd / "synced.mp4").exists()
        shots_status.append({
            "shot_id": sd.name,
            "frame": has_frame, "video": has_video,
            "audio": has_audio, "synced": has_synced,
        })

    # 检查最终产物
    has_final = any(out_dir.glob("*_final.mp4"))
    has_concat = any(out_dir.glob("*_concat.mp4"))

    # 从数据库补充生成状态详情
    db_details = []
    try:
        from infra.database.pool import get_pool
        from infra.database.generation import get_episode_statuses
        pool = get_pool()
        db_rows = get_episode_statuses(pool, episode)
        if db_rows:
            db_details = db_rows
    except Exception as e:
        logger.warning(f"DB 查询跳过: {e}")
    return {"episode": episode,
            "status": STATUS_DONE if has_final else ("in_progress" if has_concat or shot_dirs else "not_started"),
            "shots": len(shots_status),
            "final_video": str(next(out_dir.glob("*_final.mp4"), "")),
            "details": shots_status,
            "db_details": db_details}
