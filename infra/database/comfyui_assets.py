"""ComfyUI 资源跟踪 — PostgreSQL 持久化

跟踪哪些文件已上传到哪些 ComfyUI 服务器，避免重复上传或遗漏。
"""
from __future__ import annotations

from infra.database._db import query, row_to_dict, _get_project

__all__ = ["check", "mark", "unmark", "list_assets", "delete_by_project"]


def check(pool, server_url: str, asset_type: str, filename: str, project: str | None = None) -> bool:
    """检查资产是否已记录存在于此服务器"""
    project = project or _get_project()
    with query(pool, commit=False) as cur:
        cur.execute(
            "SELECT 1 FROM comfyui_assets "
            "WHERE project = %s AND server_url = %s AND asset_type = %s AND filename = %s",
            (project, server_url, asset_type, filename),
        )
        return cur.fetchone() is not None


def mark(pool, server_url: str, asset_type: str, filename: str, project: str | None = None):
    """记录资产已存在于此服务器"""
    project = project or _get_project()
    with query(pool) as cur:
        cur.execute(
            "INSERT INTO comfyui_assets (project, server_url, asset_type, filename) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (project, server_url, asset_type, filename) DO NOTHING",
            (project, server_url, asset_type, filename),
        )


def unmark(pool, server_url: str, asset_type: str, filename: str, project: str | None = None):
    """移除资产记录"""
    project = project or _get_project()
    with query(pool) as cur:
        cur.execute(
            "DELETE FROM comfyui_assets "
            "WHERE project = %s AND server_url = %s AND asset_type = %s AND filename = %s",
            (project, server_url, asset_type, filename),
        )


def list_assets(pool, server_url: str | None = None, project: str | None = None) -> list[dict]:
    """列出项目的全部/指定服务器的资产"""
    project = project or _get_project()
    with query(pool, dict_mode=True, commit=False) as cur:
        if server_url:
            cur.execute(
                "SELECT asset_type, filename FROM comfyui_assets "
                "WHERE project = %s AND server_url = %s ORDER BY asset_type, filename",
                (project, server_url),
            )
        else:
            cur.execute(
                "SELECT asset_type, filename FROM comfyui_assets "
                "WHERE project = %s ORDER BY asset_type, filename",
                (project,),
            )
        return [row_to_dict(r) for r in cur.fetchall()]


def delete_by_project(pool, project: str | None = None):
    """删除项目的所有资产记录"""
    project = project or _get_project()
    with query(pool) as cur:
        cur.execute("DELETE FROM comfyui_assets WHERE project = %s", (project,))
