"""生成状态数据库操作 — 按项目隔离（project 自动从 .active 获取）"""
from __future__ import annotations

from infra.constants import STATUS_PENDING
from infra.database._db import query, row_to_dict, _get_project

__all__ = ["upsert_status", "get_episode_statuses", "clear_episode"]


def upsert_status(pool, episode: int, shot_id: str, stage: str,
                  status: str = STATUS_PENDING, path: str = "", error: str = "",
                  elapsed: float = 0.0):
    """写入/更新生成状态"""
    project = _get_project()
    with query(pool) as cur:
        cur.execute("""
            INSERT INTO generation_status (project, episode, shot_id, stage, status, path, error, elapsed, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (project, episode, shot_id, stage) DO UPDATE SET
                status=EXCLUDED.status, path=EXCLUDED.path, error=EXCLUDED.error,
                elapsed=EXCLUDED.elapsed, updated_at=CURRENT_TIMESTAMP
        """, (project, episode, shot_id, stage, status, path, error, elapsed))


def get_episode_statuses(pool, episode: int) -> list[dict]:
    """获取整集所有镜头的生成状态"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute(
            "SELECT * FROM generation_status WHERE project = %s AND episode = %s ORDER BY shot_id, stage",
            (project, episode),
        )
        return [row_to_dict(r) for r in cur.fetchall()]


def clear_episode(pool, episode: int):
    """清除集的生成状态"""
    project = _get_project()
    with query(pool) as cur:
        cur.execute("DELETE FROM generation_status WHERE project = %s AND episode = %s", (project, episode))
