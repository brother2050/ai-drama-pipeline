"""生成状态数据库操作 — 按项目隔离（project 自动从 .active 获取）"""
from __future__ import annotations

from dataclasses import dataclass
from infra.constants import STATUS_PENDING
from infra.database._db import query, row_to_dict, _get_project

__all__ = ["upsert_status", "get_shot_status", "get_episode_statuses", "get_pending_shots", "clear_episode"]


@dataclass
class StatusRecord:
    """生成状态记录 — 消除 upsert_status 的 8 个参数"""
    episode: int
    shot_id: str
    stage: str
    status: str = STATUS_PENDING
    path: str = ""
    error: str = ""
    elapsed: float = 0.0


def upsert_status(pool, episode: int, shot_id: str, stage: str,
                  status: str = STATUS_PENDING, path: str = "", error: str = "",
                  elapsed: float = 0.0):
    """写入/更新生成状态

    Args:
        pool: 数据库连接池
        episode: 集数
        shot_id: 镜头 ID
        stage: 阶段名（tts / first_frame / video / lipsync）
        status: 状态（pending / running / done / error / skipped）
        path: 输出文件路径
        error: 错误信息（status 为 error/skipped 时）
        elapsed: 耗时（秒）
    """
    project = _get_project()
    with query(pool) as cur:
        cur.execute("""
            INSERT INTO generation_status (project, episode, shot_id, stage, status, path, error, elapsed, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (project, episode, shot_id, stage) DO UPDATE SET
                status=EXCLUDED.status, path=EXCLUDED.path, error=EXCLUDED.error,
                elapsed=EXCLUDED.elapsed, updated_at=CURRENT_TIMESTAMP
        """, (project, episode, shot_id, stage, status, path, error, elapsed))


def get_shot_status(pool, episode: int, shot_id: str) -> list[dict]:
    """获取镜头的所有步骤状态"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute(
            "SELECT * FROM generation_status WHERE project = %s AND episode = %s AND shot_id = %s ORDER BY stage",
            (project, episode, shot_id),
        )
        return [row_to_dict(r) for r in cur.fetchall()]


def get_episode_statuses(pool, episode: int) -> list[dict]:
    """获取整集所有镜头的生成状态"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute(
            "SELECT * FROM generation_status WHERE project = %s AND episode = %s ORDER BY shot_id, stage",
            (project, episode),
        )
        return [row_to_dict(r) for r in cur.fetchall()]


def get_pending_shots(pool, episode: int, stage: str) -> list[str]:
    """获取指定阶段未完成的镜头 ID"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute(
            "SELECT DISTINCT shot_id FROM generation_status "
            "WHERE project = %s AND episode = %s AND stage = %s AND status != 'done'",
            (project, episode, stage),
        )
        return [r["shot_id"] for r in cur.fetchall()]


def clear_episode(pool, episode: int):
    """清除集的生成状态"""
    project = _get_project()
    with query(pool) as cur:
        cur.execute("DELETE FROM generation_status WHERE project = %s AND episode = %s", (project, episode))
