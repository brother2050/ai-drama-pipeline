"""集管理 — DB 为唯一数据源"""
from __future__ import annotations

import logging

import psycopg2

from infra.constants import STATUS_DONE

logger = logging.getLogger(__name__)

__all__ = ["get_episode_status"]


def get_episode_status(project_dir: str, episode: int) -> dict:
    """获取集状态（DB 查询，不扫描文件系统）"""
    from infra.database.pool import get_pool
    from infra.database.generation import get_episode_statuses
    from infra.database.storyboard_db import get_episode_shots

    try:
        pool = get_pool()
    except psycopg2.Error:
        return {"episode": episode, "status": "not_started", "shots": 0}

    # 分镜数据
    try:
        shots = get_episode_shots(pool, episode)
    except psycopg2.Error:
        shots = []

    if not shots:
        return {"episode": episode, "status": "not_started", "shots": 0}

    # 生成状态
    try:
        statuses = get_episode_statuses(pool, episode)
    except psycopg2.Error:
        statuses = []

    # 按 shot_id 聚合状态
    shot_map: dict[str, dict] = {}
    for s in statuses:
        sid = s.get("shot_id", "")
        if sid not in shot_map:
            shot_map[sid] = {}
        shot_map[sid][s.get("stage", "")] = s.get("status", "")

    done_count = sum(
        1 for sid, stages in shot_map.items()
        if stages.get("first_frame") == STATUS_DONE and stages.get("video") == STATUS_DONE
    )

    has_final = done_count >= len(shots) and len(shots) > 0
    status = STATUS_DONE if has_final else ("in_progress" if done_count > 0 else "not_started")

    return {
        "episode": episode,
        "status": status,
        "shots": len(shots),
        "done": done_count,
        "details": [
            {"shot_id": s.get("shot_id", ""), **shot_map.get(s.get("shot_id", ""), {})}
            for s in shots
        ],
    }
