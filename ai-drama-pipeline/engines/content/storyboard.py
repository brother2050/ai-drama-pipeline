"""分镜表引擎 — PostgreSQL 为唯一数据源"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["load_storyboard", "save_storyboard", "append_storyboard",
           "validate_shot", "get_episode_list"]

REQUIRED_FIELDS = ["episode", "shot_id", "scene_name", "characters", "action", "dialogue"]


def _pool():
    from infra.database.pool import get_pool
    return get_pool()


# ── 读取 ──

def load_storyboard(episode: int | None = None, pool=None) -> list[dict[str, Any]]:
    """从 DB 加载分镜表。episode=None 返回全部集。"""
    from infra.database.storyboard_db import get_episode_shots, get_all_shots
    p = pool or _pool()
    shots = get_episode_shots(p, episode) if episode is not None else get_all_shots(p)
    for shot in shots:
        for field in REQUIRED_FIELDS:
            shot.setdefault(field, "")
    logger.info(f"加载分镜: {len(shots)} 个镜头" + (f" (第{episode}集)" if episode else ""))
    return shots


# ── 写入 ──

def save_storyboard(shots: list[dict], episode: int, pool=None) -> None:
    """保存某集分镜到 DB（覆盖）"""
    from infra.database.storyboard_db import save_episode_shots
    count = save_episode_shots(pool or _pool(), episode, shots)
    logger.info(f"保存分镜: 第{episode}集 {count} 个镜头")


def append_storyboard(shots: list[dict], episode: int | None = None, pool=None) -> None:
    """追加镜头到 DB（批量 upsert，单事务保证原子性）

    Args:
        shots: 镜头列表
        episode: 指定集数（None 则从每个 shot 的 episode 字段读取）
        pool: 数据库连接池
    """
    if not shots:
        return
    from infra.database.storyboard_db import batch_upsert_shots
    pool = pool or _pool()
    entries = []
    for shot in shots:
        ep = episode if episode is not None else shot.get("episode", 0)
        try:
            ep = int(ep)
        except (ValueError, TypeError):
            logger.warning(f"跳过镜头 {shot.get('shot_id', '?')}: episode 无效 ({ep!r})")
            continue
        sid = shot.get("shot_id", "")
        if ep < 1 or not sid:
            logger.warning(f"跳过镜头: episode={ep}, shot_id={sid!r}")
            continue
        entries.append((ep, sid, shot))
    if entries:
        count = batch_upsert_shots(pool, entries)
        logger.info(f"追加分镜: {count} 个镜头")


# ── 工具函数 ──

def get_episode_list(pool=None) -> list[int]:
    """获取所有有镜头的集数列表"""
    from infra.database.storyboard_db import get_all_episodes
    return get_all_episodes(pool or _pool())


def validate_shot(shot: dict) -> list[str]:
    """验证镜头数据完整性"""
    if not shot:
        return ["镜头数据为空"]
    errors = [f"缺少必填字段: {f}" for f in REQUIRED_FIELDS if not shot.get(f)]
    if shot.get("duration") is not None:
        try:
            d = float(shot["duration"])
            if d <= 0:
                errors.append("duration 必须为正数")
        except ValueError:
            errors.append(f"duration 格式错误: {shot['duration']}")
    return errors



