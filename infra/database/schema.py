"""数据库 Schema — 面向新用户，干净建表，无迁移逻辑"""
from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS characters (
    project TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    name TEXT DEFAULT '',
    gender TEXT DEFAULT '',
    appearance TEXT DEFAULT '',
    outfits TEXT DEFAULT '{}',
    voice_config TEXT DEFAULT '{}',
    reference_images TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project, id)
);

CREATE TABLE IF NOT EXISTS scenes (
    project TEXT NOT NULL DEFAULT 'default',
    id TEXT NOT NULL,
    name TEXT DEFAULT '',
    description TEXT DEFAULT '',
    lighting TEXT DEFAULT '',
    reference_images TEXT DEFAULT '[]',
    depth_map TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project, id)
);

CREATE TABLE IF NOT EXISTS episodes (
    project TEXT NOT NULL DEFAULT 'default',
    episode INTEGER NOT NULL,
    title TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    shot_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project, episode)
);

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
    PRIMARY KEY (project, episode, shot_id)
);

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
);

CREATE TABLE IF NOT EXISTS comfyui_assets (
    id SERIAL PRIMARY KEY,
    project TEXT NOT NULL DEFAULT 'default',
    server_url TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('image', 'lora')),
    filename TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project, server_url, asset_type, filename)
);

-- 索引：高频查询路径
CREATE INDEX IF NOT EXISTS idx_shots_project_episode ON shots (project, episode);
CREATE INDEX IF NOT EXISTS idx_generation_status_pending ON generation_status (project, episode, stage, status);
CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes (project);
"""


def init_schema(conn):
    """初始化数据库 Schema（面向新安装，CREATE IF NOT EXISTS 即可）"""
    with conn.cursor() as cur:
        for stmt in SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        conn.commit()
