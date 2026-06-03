"""角色数据库操作 — 按项目隔离（project 自动从 .active 获取）"""


from __future__ import annotations

import json
import logging

from infra.database._db import query, row_to_dict, _get_project

logger = logging.getLogger(__name__)

__all__ = ["get_all", "get_by_id", "upsert", "delete"]

_JSON_FIELDS = ("voice_config", "reference_images", "outfits")


def _deserialize(row: dict) -> dict:
    for field in _JSON_FIELDS:
        if field in row and isinstance(row[field], str):
            try:
                row[field] = json.loads(row[field])
            except (json.JSONDecodeError, TypeError):
                logger.debug("JSON 字段解析跳过")
                pass
    return row


def get_all(pool) -> list[dict]:
    """获取所有角色"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT * FROM characters WHERE project = %s ORDER BY id", (project,))
        return [_deserialize(row_to_dict(r)) for r in cur.fetchall()]


def get_by_id(pool, char_id: str) -> dict | None:
    """获取单个角色"""
    project = _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        cur.execute("SELECT * FROM characters WHERE project = %s AND id = %s", (project, char_id))
        row = cur.fetchone()
        return _deserialize(row_to_dict(row)) if row else None


def upsert(pool, char_id: str, data: dict):
    """写入/更新角色"""
    project = _get_project()
    with query(pool) as cur:
        cur.execute("""
            INSERT INTO characters (project, id, name, gender, appearance, outfits, voice_config, reference_images)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project, id) DO UPDATE SET
                name=EXCLUDED.name, gender=EXCLUDED.gender,
                appearance=EXCLUDED.appearance, outfits=EXCLUDED.outfits,
                voice_config=EXCLUDED.voice_config, reference_images=EXCLUDED.reference_images
        """, (
            project, char_id, data.get("name", ""), data.get("gender", ""),
            data.get("appearance", ""),
            json.dumps(data.get("outfits") or {}, ensure_ascii=False),
            json.dumps(data.get("voice_config") or {}, ensure_ascii=False),
            json.dumps(data.get("reference_images", []), ensure_ascii=False),
        ))


def delete(pool, char_id: str):
    """删除角色"""
    project = _get_project()
    with query(pool) as cur:
        cur.execute("DELETE FROM characters WHERE project = %s AND id = %s", (project, char_id))
