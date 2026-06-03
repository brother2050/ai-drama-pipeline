"""集数据库操作 — 按项目隔离（project 自动从 .active 获取）"""
from __future__ import annotations

from infra.database._db import query, row_to_dict, _get_project

__all__ = ["get_all", "get_by_episode", "upsert", "update_status", "delete"]


def get_all(pool) -> list[dict]:
    """获取所有集"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT * FROM episodes WHERE project = %s ORDER BY episode", (project,))
        return [row_to_dict(r) for r in cur.fetchall()]


def get_by_episode(pool, episode: int) -> dict | None:
    """查询单集"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT * FROM episodes WHERE project = %s AND episode = %s", (project, episode))
        row = cur.fetchone()
        return row_to_dict(row) if row else None


def update_status(pool, episode: int, status: str, shot_count: int | None = None):
    """更新集状态"""
    project = _get_project()
    with query(pool) as cur:
        if shot_count is not None:
            cur.execute(
                "UPDATE episodes SET status = %s, shot_count = %s WHERE project = %s AND episode = %s",
                (status, shot_count, project, episode))
        else:
            cur.execute(
                "UPDATE episodes SET status = %s WHERE project = %s AND episode = %s",
                (status, project, episode))


def upsert(pool, episode: int, data: dict):
    """写入/更新集"""
    project = _get_project()
    with query(pool) as cur:
        cur.execute("""
            INSERT INTO episodes (project, episode, title, status, shot_count)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (project, episode) DO UPDATE SET
                title=EXCLUDED.title, status=EXCLUDED.status, shot_count=EXCLUDED.shot_count
        """, (project, episode, data.get("title", ""), data.get("status", "pending"), data.get("shot_count", 0)))


def delete(pool, episode: int):
    """删除指定集记录"""
    project = _get_project()
    with query(pool) as cur:
        cur.execute("DELETE FROM episodes WHERE project = %s AND episode = %s", (project, episode))
