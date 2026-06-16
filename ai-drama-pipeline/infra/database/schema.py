"""数据库 Schema — 面向新用户，干净建表，无迁移逻辑

CHECK 约束：
- shots.duration: [2, 8] — 与 infra.constants.MIN_DURATION/MAX_DURATION 一致
- generation_status.status: 5 种合法状态 — 与 infra.constants.STATUS_* 一致
"""
from __future__ import annotations

__all__ = ["init_schema"]

# 状态值 CHECK 约束（与 infra.constants.STATUS_* 保持一致）
_STATUS_VALUES = "('pending', 'running', 'done', 'error', 'skipped')"

_CREATE_SHOTS = """
CREATE TABLE IF NOT EXISTS shots (
    project TEXT NOT NULL DEFAULT 'default',
    episode INTEGER NOT NULL,
    shot_id TEXT NOT NULL,
    scene_name TEXT DEFAULT '',
    characters TEXT DEFAULT '',
    action TEXT DEFAULT '',
    dialogue TEXT DEFAULT '',
    action_en TEXT DEFAULT '',
    dialogue_en TEXT DEFAULT '',
    camera TEXT DEFAULT '',
    shot_type TEXT DEFAULT '',
    duration REAL DEFAULT 4 CHECK (duration >= 2 AND duration <= 8),
    emotion TEXT DEFAULT 'neutral',
    outfit TEXT DEFAULT 'default',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project, episode, shot_id)
)
"""

_CREATE_GENERATION_STATUS = f"""
CREATE TABLE IF NOT EXISTS generation_status (
    id SERIAL PRIMARY KEY,
    project TEXT NOT NULL DEFAULT 'default',
    episode INTEGER NOT NULL,
    shot_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN {_STATUS_VALUES}),
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
    """初始化数据库 Schema（面向新安装，单事务保证原子性）"""
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for stmt in _STATEMENTS:
                cur.execute(stmt)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
