"""数据库 Schema — 面向新用户，干净建表，无迁移逻辑"""
from __future__ import annotations

__all__ = ["init_schema"]

_CREATE_SHOTS = """
CREATE TABLE IF NOT EXISTS shots (
    project TEXT NOT NULL DEFAULT 'default',
    episode INTEGER NOT NULL,
    shot_id TEXT NOT NULL,
    scene_id TEXT DEFAULT '',
    characters TEXT DEFAULT '',
    action TEXT DEFAULT '',
    dialogue TEXT DEFAULT '',
    action_en TEXT DEFAULT '',
    dialogue_en TEXT DEFAULT '',
    camera TEXT DEFAULT '',
    shot_type TEXT DEFAULT '',
    duration REAL DEFAULT 4,
    emotion TEXT DEFAULT 'neutral',
    outfit TEXT DEFAULT 'default',
    language TEXT DEFAULT 'zh',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project, episode, shot_id)
)
"""

_CREATE_GENERATION_STATUS = """
CREATE TABLE IF NOT EXISTS generation_status (
    id SERIAL PRIMARY KEY,
    project TEXT NOT NULL DEFAULT 'default',
    episode INTEGER NOT NULL,
    shot_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    path TEXT DEFAULT '',
    error TEXT DEFAULT '',
    elapsed REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project, episode, shot_id, stage)
)
"""

_CREATE_COMFYUI_ASSETS = """
CREATE TABLE IF NOT EXISTS comfyui_assets (
    id SERIAL PRIMARY KEY,
    project TEXT NOT NULL DEFAULT 'default',
    server_url TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('image', 'lora')),
    filename TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project, server_url, asset_type, filename)
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_shots_project_episode ON shots (project, episode)",
    "CREATE INDEX IF NOT EXISTS idx_generation_status_pending ON generation_status (project, episode, stage, status)",
]

_STATEMENTS = [_CREATE_SHOTS, _CREATE_GENERATION_STATUS, _CREATE_COMFYUI_ASSETS] + _CREATE_INDEXES


def init_schema(conn):
    """初始化数据库 Schema（面向新安装，CREATE IF NOT EXISTS 即可）"""
    with conn.cursor() as cur:
        for stmt in _STATEMENTS:
            cur.execute(stmt)
        conn.commit()
