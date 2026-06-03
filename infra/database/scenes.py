"""场景数据库操作 — 按项目隔离（project 自动从 .active 获取）"""


from __future__ import annotations

import json
import logging

from infra.database._db import query, row_to_dict, _get_project

logger = logging.getLogger(__name__)

__all__ = ["get_all", "get_by_id", "upsert", "delete"]


def _deserialize(row: dict) -> dict:
    if "reference_images" in row and isinstance(row["reference_images"], str):
        try:
            row["reference_images"] = json.loads(row["reference_images"])
        except (json.JSONDecodeError, TypeError):
            logger.debug("reference_images JSON 解析跳过")
            pass
    return row


def get_all(pool) -> list[dict]:
    """获取所有场景"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT * FROM scenes WHERE project = %s ORDER BY id", (project,))
        return [_deserialize(row_to_dict(r)) for r in cur.fetchall()]


def get_by_id(pool, scene_id: str) -> dict | None:
    """查询单个场景"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT * FROM scenes WHERE project = %s AND id = %s", (project, scene_id))
        row = cur.fetchone()
        return _deserialize(row_to_dict(row)) if row else None


def upsert(pool, scene_id: str, data: dict):
    """写入/更新场景"""
    project = _get_project()
    ref_images = data.get("reference_images", [])
    ref_json = (
        json.dumps(ref_images, ensure_ascii=False)
        if isinstance(ref_images, list)
        else ref_images if isinstance(ref_images, str) else "[]"
    )
    with query(pool) as cur:
        cur.execute("""
            INSERT INTO scenes (project, id, name, description, lighting, reference_images, depth_map)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project, id) DO UPDATE SET
                name=EXCLUDED.name, description=EXCLUDED.description,
                lighting=EXCLUDED.lighting, reference_images=EXCLUDED.reference_images,
                depth_map=EXCLUDED.depth_map
        """, (project, scene_id, data.get("name", ""), data.get("description", ""),
              data.get("lighting", ""), ref_json, data.get("depth_map", "")))


def delete(pool, scene_id: str):
    """删除场景"""
    project = _get_project()
    with query(pool) as cur:
        cur.execute("DELETE FROM scenes WHERE project = %s AND id = %s", (project, scene_id))
