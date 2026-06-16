"""分镜表数据库操作 — 按项目隔离（project 自动从 .active 获取）"""


from __future__ import annotations

import csv
import logging
from pathlib import Path

from infra.database._db import query, row_to_dict, safe_float, _get_project

logger = logging.getLogger(__name__)


def _sanitize_duration(data: dict) -> None:
    """验证 duration 字段，非法值就地修正为合法范围（就地修改 dict）"""
    from infra.constants import clip_duration
    data["duration"] = clip_duration(data.get("duration"))

__all__ = ["get_episode_shots", "get_shot", "get_all_episodes", "get_episodes_summary", "get_all_shots", "save_episode_shots", "upsert_shot", "batch_upsert_shots", "delete_episode", "batch_delete_shots", "export_to_csv"]

STORYBOARD_FIELDNAMES = [
    "episode", "shot_id", "scene_name", "characters", "action", "dialogue",
    "camera", "shot_type", "duration", "outfit", "emotion",
    "action_en", "dialogue_en",
]

# ── SQL 模板（INSERT/UPDATE 共用）──
_INSERT_COLS = (
    "project", "episode", "shot_id", "scene_name", "characters",
    "action", "dialogue", "action_en", "dialogue_en",
    "camera", "shot_type", "duration", "emotion", "outfit",
)
_UPSERT_SET = ", ".join(
    f"{c}=EXCLUDED.{c}" for c in _INSERT_COLS if c not in ("project", "episode", "shot_id")
) + ", updated_at=CURRENT_TIMESTAMP"


def _values(project: str, episode: int, shot: dict) -> tuple:
    """从镜头字典提取参数元组"""
    return (
        project, episode, shot.get("shot_id", ""), shot.get("scene_name", ""),
        shot.get("characters", ""), shot.get("action", ""), shot.get("dialogue", ""),
        shot.get("action_en", ""), shot.get("dialogue_en", ""),
        shot.get("camera", ""), shot.get("shot_type", ""),
        safe_float(shot.get("duration", 4)), shot.get("emotion", ""),
        shot.get("outfit", ""),
    )


# ── 读取 ──

def get_episode_shots(pool, episode: int) -> list[dict]:
    """获取指定集的所有镜头（按 shot_id 排序）"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT * FROM shots WHERE project = %s AND episode = %s ORDER BY shot_id", (project, episode))
        return [row_to_dict(r) for r in cur.fetchall()]


def get_shot(pool, episode: int, shot_id: str) -> dict | None:
    """获取单个镜头（按 episode + shot_id 精确查询）"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT * FROM shots WHERE project = %s AND episode = %s AND shot_id = %s",
                    (project, episode, shot_id))
        row = cur.fetchone()
        return row_to_dict(row) if row else None


def get_all_episodes(pool) -> list[int]:
    """获取所有有镜头的集数列表"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT DISTINCT episode FROM shots WHERE project = %s ORDER BY episode", (project,))
        return [r["episode"] for r in cur.fetchall()]


def get_episodes_summary(pool) -> list[dict]:
    """批量获取所有集数摘要（镜头数、总时长）"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("""
            SELECT episode, COUNT(*) AS shots, COALESCE(SUM(duration), 0) AS total_duration
            FROM shots WHERE project = %s GROUP BY episode ORDER BY episode
        """, (project,))
        return [{"episode": r["episode"], "shots": r["shots"], "duration": r["total_duration"]} for r in cur.fetchall()]


def get_all_shots(pool) -> list[dict]:
    """获取所有集的所有镜头"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT * FROM shots WHERE project = %s ORDER BY episode, shot_id", (project,))
        return [row_to_dict(r) for r in cur.fetchall()]


# ── 写入 ──

def save_episode_shots(pool, episode: int, shots: list[dict]) -> int:
    """保存某集的镜头列表（覆盖），返回写入数。

    使用 upsert + 清理旧数据，保证原子性：中途崩溃不会丢失已有数据。
    写入前验证数据完整性（NaN/负数/空 shot_id）。
    """
    project = _get_project()
    # 写入前验证 + 过滤无效镜头（复制避免修改调用方的 dict，如 DEFAULT_SHOTS 模块常量）
    valid_shots = []
    for shot in shots:
        shot = {**shot}
        _sanitize_duration(shot)
        if not shot.get("shot_id"):
            logger.warning(f"跳过无 shot_id 的镜头: {shot.get('action', '?')[:50]}")
            continue
        valid_shots.append(shot)
    cols = ", ".join(_INSERT_COLS)
    # execute_values 要求 SQL 中只有一个 %s 占位符（由 execute_values 自动展开为多行）
    sql = f"INSERT INTO shots ({cols}) VALUES %s ON CONFLICT (project, episode, shot_id) DO UPDATE SET {_UPSERT_SET}"
    new_ids = [s.get("shot_id", "") for s in valid_shots if s.get("shot_id")]
    with pool.connection() as conn:
        cur = conn.cursor()
        try:
            # 批量插入（execute_values 比逐行 execute 快 5-10x）
            from psycopg2.extras import execute_values
            values = [_values(project, episode, shot) for shot in valid_shots]
            if values:
                execute_values(cur, sql, values, page_size=100)
            # 仅在有有效镜头时才清理旧数据，防止空列表误删全集
            if valid_shots and new_ids:
                cur.execute(
                    "DELETE FROM shots WHERE project = %s AND episode = %s AND NOT (shot_id = ANY(%s))",
                    (project, episode, new_ids))
                # 同步清理已删除镜头的生成状态（防止孤儿记录）
                cur.execute(
                    "DELETE FROM generation_status WHERE project = %s AND episode = %s AND NOT (shot_id = ANY(%s))",
                    (project, episode, new_ids))
            elif not valid_shots:
                logger.warning(f"所有镜头均无效，跳过删除（防止误清空第{episode}集）")
            conn.commit()
            return len(valid_shots)
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def upsert_shot(pool, episode: int, shot_id: str, data: dict):
    """写入/更新单个镜头（写入前验证数据完整性，不修改原 dict）"""
    project = _get_project()
    # 验证 duration（复制避免修改调用方的 dict）
    data = {**data}
    _sanitize_duration(data)
    cols = ", ".join(_INSERT_COLS)
    ph = ", ".join(["%s"] * len(_INSERT_COLS))
    sql = f"INSERT INTO shots ({cols}) VALUES ({ph}) ON CONFLICT (project, episode, shot_id) DO UPDATE SET {_UPSERT_SET}"
    with query(pool) as cur:
        cur.execute(sql, _values(project, episode, {**data, "shot_id": shot_id}))


def batch_upsert_shots(pool, shots: list[tuple[int, str, dict]]) -> int:
    """批量写入/更新镜头（单连接 + 单事务，execute_values 批量插入）

    Args:
        shots: [(episode, shot_id, data), ...] 列表

    Returns:
        写入数
    """
    project = _get_project()
    cols = ", ".join(_INSERT_COLS)
    # execute_values 要求 SQL 中只有一个 %s 占位符
    sql = f"INSERT INTO shots ({cols}) VALUES %s ON CONFLICT (project, episode, shot_id) DO UPDATE SET {_UPSERT_SET}"
    values = []
    for episode, shot_id, data in shots:
        if not shot_id:
            logger.warning(f"跳过无 shot_id 的镜头 (episode={episode})")
            continue
        data = {**data}
        _sanitize_duration(data)
        values.append(_values(project, episode, {**data, "shot_id": shot_id}))
    if not values:
        return 0
    with query(pool) as cur:
        from psycopg2.extras import execute_values
        execute_values(cur, sql, values, page_size=100)
    return len(values)


def delete_episode(pool, episode: int) -> int:
    """删除某集所有镜头 + 生成状态，返回删除数"""
    project = _get_project()
    with query(pool) as cur:
        cur.execute("DELETE FROM shots WHERE project = %s AND episode = %s", (project, episode))
        deleted = cur.rowcount
        cur.execute("DELETE FROM generation_status WHERE project = %s AND episode = %s", (project, episode))
        return deleted


def batch_delete_shots(pool, episode: int, shot_ids: list[str]) -> int:
    """批量删除镜头 + 对应生成状态，返回删除数"""
    if not shot_ids:
        return 0
    project = _get_project()
    with query(pool) as cur:
        cur.execute("DELETE FROM shots WHERE project = %s AND episode = %s AND shot_id = ANY(%s)", (project, episode, shot_ids))
        deleted = cur.rowcount
        cur.execute("DELETE FROM generation_status WHERE project = %s AND episode = %s AND shot_id = ANY(%s)", (project, episode, shot_ids))
        return deleted


# ── CSV 导出 ──

def export_to_csv(pool, episode: int, path: Path) -> int:
    """导出某集镜头到 CSV 文件，返回镜头数"""
    shots = get_episode_shots(pool, episode)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STORYBOARD_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(shots)
    return len(shots)
